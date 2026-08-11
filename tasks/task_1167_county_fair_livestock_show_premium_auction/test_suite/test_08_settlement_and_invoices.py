"""Settlement sweep and invoicing: dual-variant premium and payout
calculations, per-line premium rounding order, invoice issue/payment
lifecycle, segregation of duties, and affidavit gates (PRD §3.5, §3.7).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_posture,
    api_client,
    assert_invoice_totals,
    award_for_entry,
    build_show_state,
    create_buyer,
    create_disposition,
    generate_lots,
    get_add_on,
    get_buyer_invoice,
    get_disposition,
    get_fair,
    get_lot,
    issue_invoice,
    list_premium_awards,
    make_admin_headers,
    make_buyer_headers,
    make_treasurer_headers,
    open_lot,
    close_sold,
    post_payment,
    setup_issued_invoice,
    setup_not_sold_entry,
    setup_sold_lot,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin"]
TREASURER = TEST_USERS["treasurer"]


def _awards_by_entry():
    return {a["entry_id"]: a for a in list_premium_awards()}


class TestInvoicePremiumRounding:
    def _two_species_sold_to_one_buyer(self, name, hammer_1, hammer_2):
        """One steer and one lamb, each rank 1 NONE, sold to one buyer."""
        ctx = build_show_state(
            fair_overrides={"name": name},
            entries=[
                {"species": "MARKET_STEER", "tag_number": "S-001",
                 "weight_lbs": 1200},
                {"species": "MARKET_LAMB", "tag_number": "L-001",
                 "weight_lbs": 100},
            ],
            classes=[
                {"species": "MARKET_STEER", "class_code": "STEER-A",
                 "weight_min_lbs": 1000, "weight_max_lbs": 1500,
                 "capacity": 5},
                {"species": "MARKET_LAMB", "class_code": "LAMB-A",
                 "weight_min_lbs": 90, "weight_max_lbs": 120, "capacity": 5},
            ],
            entry_class_map={0: 0, 1: 1},
            judges=[{"qualified_species": ["MARKET_STEER", "MARKET_LAMB"]}],
            slots=[
                {"class_index": 0, "judge_index": 0, "ring_name": "MAIN",
                 "starts_at": "2026-07-10T09:00:00Z",
                 "ends_at": "2026-07-10T10:00:00Z"},
                {"class_index": 1, "judge_index": 0, "ring_name": "MAIN",
                 "starts_at": "2026-07-10T10:15:00Z",
                 "ends_at": "2026-07-10T11:00:00Z"},
            ],
            placings=[
                {"slot_index": 0,
                 "lines": [{"entry_index": 0, "rank": 1, "award": "NONE"}]},
                {"slot_index": 1,
                 "lines": [{"entry_index": 1, "rank": 1, "award": "NONE"}]},
            ],
            advance_to="AUCTION",
        )
        buyer = create_buyer(ctx["fair"]["id"], credit_limit_cents=1000000)
        gen = generate_lots(ctx["fair"]["id"])
        lots = {}
        for lot_id in gen["lot_ids"]:
            lot = get_lot(lot_id)
            lots[lot["lot_number"]] = lot
        open_lot(lots[1]["id"])
        close_sold(lots[1]["id"], buyer["id"], hammer_1)
        open_lot(lots[2]["id"])
        close_sold(lots[2]["id"], buyer["id"], hammer_2)
        advance_posture(ctx["fair"]["id"], "SETTLEMENT")
        return ctx, buyer

    def test_invoice_per_line_premium_rounding_order(self, api):
        """PRD §3.7: "The premium rounding order is pinned: for each hammer
        line, the line premium is the line's hammer price multiplied by the
        fair's `buyer_premium_rate`, rounded half-up to whole cents, and
        `buyer_premium_cents` is the sum of those rounded line values; add-on
        lines carry no buyer premium. The alternative order — rounding the
        premium on the summed hammer — can differ by cents and is not the
        contract."

        Design: Difficulty/combinatorial_formula/invoice_per_line_premium_rounding_order
        """
        _ctx, buyer = self._two_species_sold_to_one_buyer("Fair R2B", 1010, 1040)
        invoice = get_buyer_invoice(buyer["id"])
        issued = issue_invoice(invoice["id"])
        assert_invoice_totals(issued)
        assert issued["hammer_subtotal_cents"] == 2050
        assert issued["addon_subtotal_cents"] == 0
        assert issued["buyer_premium_cents"] == 61, (
            "round_half_up(1010*0.03)=30 plus round_half_up(1040*0.03)=31; "
            "the pooled-rounding alternative would give 62"
        )
        assert issued["total_due_cents"] == 2111

    def test_invoice_add_on_lines_carry_no_buyer_premium(self, api):
        """PRD §3.7: "The premium rounding order is pinned: for each hammer
        line, the line premium is the line's hammer price multiplied by the
        fair's `buyer_premium_rate`, rounded half-up to whole cents, and
        `buyer_premium_cents` is the sum of those rounded line values; add-on
        lines carry no buyer premium."
        PRD §3.7: "`line_count` counts the swept lines of both kinds — each
        swept lot contributes a hammer line and each swept pledge an add-on
        line."

        Design: Difficulty/combinatorial_formula/invoice_per_line_premium_rounding_order
        """
        ctx = setup_issued_invoice(
            fair_overrides={"name": "Fair R2B-addon"},
            hammer_price_cents=1010, credit_limit_cents=1000000,
            add_on_amounts=[5000],
        )
        invoice = ctx["invoice"]
        assert_invoice_totals(invoice)
        assert invoice["hammer_subtotal_cents"] == 1010
        assert invoice["addon_subtotal_cents"] == 5000
        assert invoice["buyer_premium_cents"] == 30, (
            "premium only on the hammer line: round_half_up(1010*0.03)"
        )
        assert invoice["total_due_cents"] == 6040
        assert invoice["line_count"] == 2, "one hammer line + one add-on line"


class TestInvoicePayments:
    def test_invoice_partial_then_full_payment_and_addon_cascade(self, api):
        """PRD §3.7: "A payment smaller than the balance moves `ISSUED` →
        `PARTIALLY_PAID`, and further partial payments keep the invoice in
        `PARTIALLY_PAID`; each payment recomputes `amount_paid_cents` as the
        sum of posted payments and `balance_cents` as `total_due_cents` minus
        that sum. A payment exactly equal to the balance — from `ISSUED` or
        from `PARTIALLY_PAID` — moves the invoice to `PAID`, drives
        `balance_cents` to zero, and cascades every swept pledge from
        `INVOICED` to `PAID`."

        Design: Corner/state_machines/invoice_partial_then_full_payment_and_addon_cascade
        """
        ctx = setup_issued_invoice(
            fair_overrides={"name": "Fair S8"}, hammer_price_cents=50000,
            add_on_amounts=[5000],
        )
        invoice = ctx["invoice"]
        assert invoice["status"] == "ISSUED"
        assert invoice["total_due_cents"] == 56500, (
            "50000 hammer + 5000 add-on + 1500 buyer premium"
        )
        assert get_add_on(ctx["addons"][0]["id"])["status"] == "INVOICED"

        partial = post_payment(invoice["id"], 20000)
        assert partial["status"] == "PARTIALLY_PAID"
        assert partial["balance_cents"] == 36500

        paid = post_payment(invoice["id"], 36500)
        assert paid["status"] == "PAID"
        assert paid["balance_cents"] == 0
        assert get_add_on(ctx["addons"][0]["id"])["status"] == "PAID"

    def test_addon_void_only_while_pledged(self, api):
        """PRD §3.7: "While still `PLEDGED`, a pledge can be voided by the
        pledging buyer or an admin with an optional `reason`, moving it to
        `VOIDED` and removing it from the draft totals; once invoiced it can
        no longer be voided."

        Design: Corner/state_machines/addon_void_only_while_pledged
        """
        ctx = setup_sold_lot(
            fair_overrides={"name": "Fair S9"}, hammer_price_cents=50000,
            add_on_amounts=[5000, 7000],
        )
        addon_1, addon_2 = ctx["addons"][0], ctx["addons"][1]
        buyer_id = ctx["buyer"]["id"]

        voided = validate_success(
            api_client.void_add_on(addon_1["id"],
                                   make_buyer_headers(buyer_id),
                                   reason="donor changed mind"),
            200,
        )
        assert voided["status"] == "VOIDED"

        advance_posture(ctx["fair"]["id"], "SETTLEMENT")
        invoice = issue_invoice(get_buyer_invoice(buyer_id)["id"])
        assert invoice["addon_subtotal_cents"] == 7000, (
            "the voided 5000 pledge is excluded from the sweep"
        )
        assert get_add_on(addon_2["id"])["status"] == "INVOICED"

        too_late = api_client.void_add_on(
            addon_2["id"],
            make_buyer_headers(buyer_id),
            reason="too late",
        )
        validate_error(too_late, ApiErrorId.ERR_INVALID_STATE)

    def test_overpayment_beyond_balance_returns_error(self, api):
        """PRD §3.7: "The amount must be greater than zero (else
        `ERR_INVALID_AMOUNT`) and must not exceed the invoice's
        `balance_cents` (else `ERR_OVERPAYMENT`, HTTP 422); positivity is
        checked before the overpayment bound."

        Design: Corner/validations/overpayment_beyond_balance_returns_error
        """
        ctx = setup_issued_invoice(fair_overrides={"name": "Fair V16"},
                                   hammer_price_cents=50000)
        invoice = ctx["invoice"]
        assert invoice["balance_cents"] == 51500

        resp = api_client.post_payment(invoice["id"], 51501, TREASURER)
        validate_error(resp, ApiErrorId.ERR_OVERPAYMENT)

        fresh = validate_success(api_client.get_invoice(invoice["id"], TREASURER))
        assert fresh["status"] == "ISSUED"
        assert fresh["balance_cents"] == 51500
        assert fresh["amount_paid_cents"] == 0

    def test_invoice_issue_twice_returns_invalid_state(self, api):
        """PRD §2.7: "state validity for the requested transition, including
        terminal-state lockdown, non-adjacent posture advance, settlement and
        closure guards, reoffer from a non-`PASSED` lot, double issue or
        double void, and lots opened out of order (failure:
        `ERR_INVALID_STATE`)".

        Design: Corner/validations/invoice_issue_twice_returns_invalid_state
        """
        ctx = setup_issued_invoice(fair_overrides={"name": "Fair V17"},
                                   hammer_price_cents=50000)
        invoice = ctx["invoice"]
        assert invoice["total_due_cents"] == 51500

        resp = api_client.issue_invoice(invoice["id"], TREASURER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        fresh = validate_success(api_client.get_invoice(invoice["id"], TREASURER))
        assert fresh["status"] == "ISSUED"
        assert fresh["total_due_cents"] == 51500, "no double sweep"


class TestSettlementSweepDualVariants:
    def _two_placed_steers_settlement(self, name):
        """Two steers ranked 1 and 2 (no large-class bonus: class size 2 < 8),
        fair walked to SETTLEMENT with no auction lots generated."""
        return build_show_state(
            fair_overrides={"name": name, "premium_budget_cents": 10000},
            entries=[
                {"species": "MARKET_STEER", "tag_number": "S-001",
                 "weight_lbs": 1200, "exhibitor_index": 0},
                {"species": "MARKET_STEER", "tag_number": "S-002",
                 "weight_lbs": 1250, "exhibitor_index": 1},
            ],
            classes=[{"species": "MARKET_STEER", "class_code": "STEER-A",
                      "weight_min_lbs": 1000, "weight_max_lbs": 1500,
                      "capacity": 5}],
            entry_class_map={0: 0, 1: 0},
            judges=[{"qualified_species": ["MARKET_STEER"]}],
            slots=[{"class_index": 0, "judge_index": 0}],
            placings=[{
                "slot_index": 0,
                "lines": [
                    {"entry_index": 0, "rank": 1, "award": "NONE"},
                    {"entry_index": 1, "rank": 2, "award": "NONE"},
                ],
            }],
            advance_to="SETTLEMENT",
        )

    def test_premium_provisional_vs_final_under_purse_shortfall(self, api):
        """PRD §3.5: "For every award still `ACCRUED` or `APPROVED`, the
        server totals the outstanding reservations, computes a scale as the
        ratio of `premium_budget_cents` to that outstanding total capped at 1
        (an outstanding total of zero scales at 1 vacuously), and sets each
        award's `final_amount_cents` to its `provisional_amount_cents`
        multiplied by the scale and rounded down to whole cents. The final
        amount therefore differs from the provisional amount whenever the
        purse is oversubscribed."

        Design: Difficulty/dual_variant_calc/premium_provisional_vs_final_under_purse_shortfall
        """
        ctx = self._two_placed_steers_settlement("Fair R1A")
        fair_id = ctx["fair"]["id"]
        entry_a = ctx["entries"][0]["id"]
        entry_b = ctx["entries"][1]["id"]

        validate_success(api_client.run_settlement(fair_id, ADMIN), 200)
        awards = _awards_by_entry()
        award_a, award_b = awards[entry_a], awards[entry_b]
        assert award_a["provisional_amount_cents"] == 12000
        assert award_a["final_amount_cents"] == 5454, (
            "floor(12000 * 10000/22000)"
        )
        assert award_b["provisional_amount_cents"] == 10000
        assert award_b["final_amount_cents"] == 4545, (
            "floor(10000 * 10000/22000)"
        )
        assert award_a["final_amount_cents"] != award_a["provisional_amount_cents"]
        assert award_b["final_amount_cents"] != award_b["provisional_amount_cents"]

    def test_purse_goes_negative_then_sweep_scales_finals(self, api):
        """PRD §3.5: "At every moment, `available_premium_pool_cents` equals
        `premium_budget_cents` minus the sum of `provisional_amount_cents`
        across all of the fair's awards in `ACCRUED`, `APPROVED`, or `PAID`
        status; `FORFEITED` awards are excluded because their reservation has
        returned to the pool. When placings outrun the purse, the pool may
        transiently go negative; the settlement sweep brings payouts back
        within budget."

        Design: Difficulty/dual_variant_calc/premium_provisional_vs_final_under_purse_shortfall
        """
        ctx = self._two_placed_steers_settlement("Fair R1A-neg")
        fair_id = ctx["fair"]["id"]
        # Outstanding reservations 12000 + 10000 = 22000 against a 10000 purse.
        assert get_fair(fair_id)["available_premium_pool_cents"] == -12000, (
            "pool is budget minus outstanding reservations, even negative"
        )

        validate_success(api_client.run_settlement(fair_id, ADMIN), 200)
        # The sweep scales finals; the provisional reservations are untouched.
        assert get_fair(fair_id)["available_premium_pool_cents"] == -12000
        for award in list_premium_awards():
            assert award["final_amount_cents"] < award["provisional_amount_cents"]

    def test_payout_provisional_vs_final_with_addon_sweep(self, api):
        """PRD §3.7: "Each `SOLD` lot's `final_payout_cents` is the hammer
        price plus the sum of `amount_cents` across the lot's pledges in any
        status other than `VOIDED`, minus the same rounded commission, minus
        `yardage_fee_cents`. The final payout therefore differs from
        `provisional_payout_cents` whenever any non-void add-on pledge exists
        on the lot."

        Design: Difficulty/dual_variant_calc/payout_provisional_vs_final_with_addon_sweep
        """
        ctx = setup_sold_lot(
            fair_overrides={"name": "Fair R1B"}, hammer_price_cents=100000,
            credit_limit_cents=200000, add_on_amounts=[20000],
            advance_to_settlement=True,
        )
        lot = ctx["lot"]
        assert lot["provisional_payout_cents"] == 93500, (
            "100000 - round_half_up(100000*0.05)=5000 - 1500"
        )

        validate_success(api_client.run_settlement(ctx["fair"]["id"], ADMIN), 200)
        settled = get_lot(lot["id"])
        assert settled["final_payout_cents"] == 113500, (
            "100000 + 20000 non-void add-on - 5000 - 1500"
        )
        assert settled["final_payout_cents"] != settled["provisional_payout_cents"]

    def test_payout_final_excludes_voided_addons(self, api):
        """PRD §3.7: "Each `SOLD` lot's `final_payout_cents` is the hammer
        price plus the sum of `amount_cents` across the lot's pledges in any
        status other than `VOIDED`, minus the same rounded commission, minus
        `yardage_fee_cents`."

        Design: Difficulty/dual_variant_calc/payout_provisional_vs_final_with_addon_sweep
        """
        ctx = setup_sold_lot(
            fair_overrides={"name": "Fair R1B-void"}, hammer_price_cents=100000,
            credit_limit_cents=200000, add_on_amounts=[20000],
        )
        lot_id = ctx["lot"]["id"]
        buyer_id = ctx["buyer"]["id"]
        addon = ctx["addons"][0]
        validate_success(
            api_client.void_add_on(
                addon["id"],
                make_buyer_headers(buyer_id),
                reason="donor withdrew",
            ),
            200,
        )
        advance_posture(ctx["fair"]["id"], "SETTLEMENT")
        validate_success(api_client.run_settlement(ctx["fair"]["id"], ADMIN), 200)

        settled = get_lot(lot_id)
        assert settled["provisional_payout_cents"] == 93500
        assert settled["final_payout_cents"] == 93500, (
            "the VOIDED pledge contributes nothing to the final payout"
        )


class TestAwardSegregationAndAffidavitGate:
    def test_segregation_of_duties_premium_approver_cannot_pay(self, api):
        """PRD §3.5: "Payment moves `APPROVED` → `PAID` and must be executed
        by a different treasurer: the caller's `X-User-ID` must differ from
        `approved_by_user_id`, else the payment is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The paying treasurer is
        recorded in `paid_by_user_id`, and the paid amount is
        `final_amount_cents` when it has been set, otherwise
        `provisional_amount_cents`."

        Design: Corner/rbac/segregation_of_duties_premium_approver_cannot_pay
        """
        ctx = build_show_state(
            fair_overrides={"name": "Fair B6"},
            entries=[{"species": "MARKET_STEER", "tag_number": "S-001",
                      "weight_lbs": 1200}],
            classes=[{"species": "MARKET_STEER", "class_code": "STEER-A",
                      "weight_min_lbs": 1000, "weight_max_lbs": 1500,
                      "capacity": 5}],
            entry_class_map={0: 0},
            judges=[{"qualified_species": ["MARKET_STEER"]}],
            slots=[{"class_index": 0, "judge_index": 0}],
            placings=[{"slot_index": 0,
                       "lines": [{"entry_index": 0, "rank": 1,
                                  "award": "NONE"}]}],
            affidavit_entries=[0],
            advance_to="SETTLEMENT",
        )
        award = award_for_entry(ctx["entries"][0]["id"])
        assert award["provisional_amount_cents"] == 12000

        approved = validate_success(
            api_client.approve_premium_award(
                award["id"], make_treasurer_headers("treas-1")
            ),
            200,
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "treas-1"

        same_user = api_client.pay_premium_award(
            award["id"], make_treasurer_headers("treas-1")
        )
        validate_error(same_user, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert award_for_entry(ctx["entries"][0]["id"])["status"] == "APPROVED"

        paid = validate_success(
            api_client.pay_premium_award(
                award["id"], make_treasurer_headers("treas-2")
            ),
            200,
        )
        assert paid["status"] == "PAID"
        assert paid["paid_by_user_id"] == "treas-2"

    def test_disposition_approve_blocked_without_signed_affidavit(self, api):
        """PRD §3.8: "Approval is a `FairBoardAdmin` checker step on a
        `REQUESTED` order, and its checks fire in order: the entry must carry
        a `SIGNED` affidavit (else `ERR_AFFIDAVIT_MISSING`) — the same
        requirement that guards premium approval — then the approver must
        differ from `created_by_user_id` unless the creator is `SYSTEM` (else
        `ERR_SEGREGATION_OF_DUTIES`), then type compatibility."

        Design: Difficulty/cross_entity_state_dependency/disposition_approve_blocked_without_signed_affidavit
        """
        ctx = setup_not_sold_entry(fair_overrides={"name": "Fair R7B"})
        entry_id = ctx["entries"][0]["id"]
        order = create_disposition(
            entry_id, creator_headers=make_admin_headers("admin-a"),
            disposition_type="RETURN", destination="Home Farm",
        )
        resp = api_client.approve_disposition(
            order["id"], make_admin_headers("admin-b")
        )
        validate_error(resp, ApiErrorId.ERR_AFFIDAVIT_MISSING)
        assert get_disposition(order["id"])["status"] == "REQUESTED"

    def test_premium_approve_blocked_without_signed_affidavit(self, api):
        """PRD §3.5: "A `Treasurer` approves an `ACCRUED` award only while the
        fair is in `SETTLEMENT` (else `ERR_POSTURE_FORBIDS`) and only when the
        entry has an affidavit in `SIGNED` status (else
        `ERR_AFFIDAVIT_MISSING`, HTTP 409); approval records the caller in
        `approved_by_user_id` and moves the award `ACCRUED` → `APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/disposition_approve_blocked_without_signed_affidavit
        """
        ctx = build_show_state(
            fair_overrides={"name": "Fair R7B-premium"},
            entries=[{"species": "MARKET_STEER", "tag_number": "S-001",
                      "weight_lbs": 1200}],
            classes=[{"species": "MARKET_STEER", "class_code": "STEER-A",
                      "weight_min_lbs": 1000, "weight_max_lbs": 1500,
                      "capacity": 5}],
            entry_class_map={0: 0},
            judges=[{"qualified_species": ["MARKET_STEER"]}],
            slots=[{"class_index": 0, "judge_index": 0}],
            placings=[{"slot_index": 0,
                       "lines": [{"entry_index": 0, "rank": 1,
                                  "award": "NONE"}]}],
            advance_to="SETTLEMENT",
        )
        award = award_for_entry(ctx["entries"][0]["id"])
        resp = api_client.approve_premium_award(
            award["id"], make_treasurer_headers("treas-1")
        )
        validate_error(resp, ApiErrorId.ERR_AFFIDAVIT_MISSING)
        assert award_for_entry(ctx["entries"][0]["id"])["status"] == "ACCRUED"
