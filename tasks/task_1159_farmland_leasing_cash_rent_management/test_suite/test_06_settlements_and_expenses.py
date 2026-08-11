"""Harvest settlement economics and lifecycle: flex bonus trigger/cap math,
share per-line rounding, provisional-vs-final divergence, the countersign
true-up, dispute/refinalize, expense review, and type/state guards."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_iso_instant_equal,
    create_settlement_payload,
    get_lease,
    get_settlement,
    list_lease_installments,
    make_tenant_headers,
    setup_active_lease,
    setup_finalized_settlement_scenario,
    setup_settlement_scenario,
    setup_share_lease_with_approved_expenses,
    create_settlement,
    submit_expense,
    validate_error,
    validate_success,
)

MGR = TEST_USERS["farm_manager_headers"]
MGR_1 = TEST_USERS["mgr_1_headers"]
MGR_2 = TEST_USERS["mgr_2_headers"]
MGR_3 = TEST_USERS["mgr_3_headers"]

# Shared FLEX economics used across this file: 100 acres, base 20000/acre
# (annual 2000000), bonus 20%, cap 500000, trigger 9000000.


class TestFlexComputation:
    def test_flex_bonus_zero_at_exact_trigger(self, api):
        """PRD §3.6: "For a `FLEX` lease, the base total is the lease's `base_rent_cents_per_acre` multiplied by the field's `acres`, and a bonus applies only when gross revenue strictly exceeds the lease's `revenue_trigger_cents` — at exact equality there is no bonus."

        Design: Difficulty/boundary_precision_check/flex_bonus_zero_at_exact_trigger
        """
        ctx = setup_settlement_scenario(
            "FLEX", price_source="ACTUAL", yield_bu_per_acre=180,
            harvest_price_cents_per_bu=500,
        )
        settlement = ctx["settlement"]
        # gross = 180 * 500 * 100 = 9000000 == trigger exactly
        assert settlement["gross_revenue_cents"] == 9000000
        assert settlement["landlord_amount_cents"] == 2000000, (
            "strict > semantics: at equality the bonus is zero, base only"
        )

    def test_flex_bonus_applies_one_step_above_trigger(self, api):
        """PRD §3.6: "a bonus applies only when gross revenue strictly exceeds the lease's `revenue_trigger_cents`"
        PRD §3.6: "The raw bonus is the excess of gross revenue over the trigger, multiplied by the lease's `landlord_bonus_pct`; the charged bonus is zero when that raw value is not positive, and otherwise the smaller of the lease's `flex_cap_cents` and the raw bonus rounded half up to whole cents, the rounding applied before the cap."

        Design: Difficulty/boundary_precision_check/flex_bonus_zero_at_exact_trigger
        """
        ctx = setup_settlement_scenario(
            "FLEX", price_source="ACTUAL", yield_bu_per_acre=182,
            harvest_price_cents_per_bu=500,
        )
        settlement = ctx["settlement"]
        # gross = 9100000 > trigger; bonus = round_half_up(100000 * 0.2) = 20000.
        assert settlement["gross_revenue_cents"] == 9100000
        assert settlement["landlord_amount_cents"] == 2020000

    def test_flex_bonus_clamped_by_cap(self, api):
        """PRD §3.6: "The computed amounts begin with `gross_revenue_cents`, the yield per acre multiplied by the price per bushel multiplied by the field's `acres`."
        PRD §3.6: "the charged bonus is zero when that raw value is not positive, and otherwise the smaller of the lease's `flex_cap_cents` and the raw bonus rounded half up to whole cents, the rounding applied before the cap. The `landlord_amount_cents` is the base total plus the bonus."

        Design: Difficulty/combinatorial_formula/flex_bonus_cap_and_trigger_nesting
        """
        ctx = setup_settlement_scenario(
            "FLEX", price_source="ACTUAL", yield_bu_per_acre=400,
            harvest_price_cents_per_bu=500,
        )
        settlement = ctx["settlement"]
        # gross = 400*500*100 = 20000000; raw bonus = 11000000*0.2 = 2200000,
        # clamped by min() to the 500000 cap; landlord_amount = 2000000 + 500000.
        assert settlement["gross_revenue_cents"] == 20000000
        assert settlement["landlord_amount_cents"] == 2500000, (
            "min(cap, raw bonus) clamps the bonus to 500000, not the uncapped 2200000"
        )

    def test_flex_capped_settlement_net_without_input_sharing(self, api):
        """PRD §3.6: "For a `FLEX` lease the same per-line sum runs with the lease's `input_share_pct`, treated as zero when the lease carries none. The `net_settlement_cents` is the `landlord_amount_cents` minus the `input_share_total_cents`."

        Design: Difficulty/combinatorial_formula/flex_bonus_cap_and_trigger_nesting
        """
        ctx = setup_settlement_scenario(
            "FLEX", price_source="ACTUAL", yield_bu_per_acre=400,
            harvest_price_cents_per_bu=500,
        )
        settlement = ctx["settlement"]
        assert settlement["input_share_total_cents"] == 0, (
            "no input_share_pct on this FLEX lease and no approved expenses"
        )
        assert settlement["landlord_amount_cents"] == 2500000
        assert settlement["net_settlement_cents"] == 2500000


class TestProvisionalVsFinal:
    def test_provisional_and_final_prices_diverge_on_same_lease(self, api):
        """PRD §3.6: "A settlement created with the `ESTIMATED` price source is provisional and informational; only an `ACTUAL` settlement can be finalized."
        PRD §3.6: "The computed amounts begin with `gross_revenue_cents`, the yield per acre multiplied by the price per bushel multiplied by the field's `acres`."

        Design: Difficulty/dual_variant_calc/flex_settlement_provisional_vs_final_price
        """
        ctx = setup_active_lease("FLEX")
        provisional = create_settlement(
            ctx, price_source="ESTIMATED", yield_bu_per_acre=200,
            harvest_price_cents_per_bu=450,
        )
        # gross = 200*450*100 = 9000000 == trigger -> bonus 0 -> base only.
        assert provisional["gross_revenue_cents"] == 9000000
        assert provisional["landlord_amount_cents"] == 2000000

        final = create_settlement(
            ctx, price_source="ACTUAL", yield_bu_per_acre=200,
            harvest_price_cents_per_bu=500,
        )
        # gross = 10000000 > trigger -> bonus round_half_up(1000000*0.2) = 200000.
        assert final["gross_revenue_cents"] == 10000000
        assert final["landlord_amount_cents"] == 2200000
        assert final["landlord_amount_cents"] - provisional["landlord_amount_cents"] == 200000, (
            "identical lease parameters, different price_source: the variants diverge"
        )

    def test_new_settlement_supersedes_provisional_sibling_to_void(self, api):
        """PRD §3.6: "Only one non-`VOID` settlement may exist for a lease and crop year: an existing sibling in `FINALIZED`, `DISPUTED`, or `COUNTERSIGNED` blocks creation with `ERR_SETTLEMENT_YEAR_FINAL_EXISTS`, while an existing `PROVISIONAL` sibling is superseded to `VOID` by the newcomer."

        Design: Difficulty/dual_variant_calc/flex_settlement_provisional_vs_final_price
        """
        ctx = setup_active_lease("FLEX")
        provisional = create_settlement(
            ctx, price_source="ESTIMATED", yield_bu_per_acre=200,
            harvest_price_cents_per_bu=450,
        )
        assert provisional["status"] == "PROVISIONAL"
        final = create_settlement(
            ctx, price_source="ACTUAL", yield_bu_per_acre=200,
            harvest_price_cents_per_bu=500,
        )
        assert final["status"] == "PROVISIONAL"
        superseded = get_settlement(provisional["id"])
        assert superseded["status"] == "VOID", (
            "the newcomer supersedes the PROVISIONAL sibling to VOID"
        )


class TestShareSettlement:
    def test_share_input_sharing_rounds_per_line_then_sums(self, api):
        """PRD §3.6: "The `input_share_total_cents` is the sum of the `landlord_share_cents` over the lease's expense records for the same `crop_year` that are in `APPROVED` status — submitted or rejected expenses are excluded — with each line rounded half up to whole cents first and the rounded lines then summed; summing first and rounding once is forbidden because it produces a different cent total on half-cent lines."
        PRD §3.6: "computes its `landlord_share_cents` as the total cost multiplied by that percentage, rounded half up to whole cents per line and pinned at that value"

        Design: Difficulty/combinatorial_formula/share_settlement_per_line_rounding
        """
        ctx = setup_share_lease_with_approved_expenses((100001, 100001))
        exp1, exp2 = ctx["expenses"]
        # round_half_up(100001 * 0.5) = 50001 per line.
        assert exp1["landlord_share_cents"] == 50001
        assert exp2["landlord_share_cents"] == 50001

        settlement = create_settlement(ctx, price_source="ACTUAL")
        # Per-line-then-sum: 50001 + 50001 = 100002 (sum-then-round of
        # 200002*0.5 would give 100001 and is forbidden).
        assert settlement["input_share_total_cents"] == 100002

    def test_share_landlord_amount_and_net(self, api):
        """PRD §3.6: "For a `SHARE` lease, the `landlord_amount_cents` is simply the gross revenue multiplied by the lease's `landlord_share_pct`, rounded half up to whole cents."
        PRD §3.6: "The `net_settlement_cents` is the `landlord_amount_cents` minus the `input_share_total_cents`."

        Design: Difficulty/combinatorial_formula/share_settlement_per_line_rounding
        """
        ctx = setup_share_lease_with_approved_expenses((100001, 100001))
        settlement = create_settlement(ctx, price_source="ACTUAL")
        # gross = 200*500*100 = 10000000; landlord share = round(10000000*0.4).
        assert settlement["gross_revenue_cents"] == 10000000
        assert settlement["landlord_amount_cents"] == 4000000
        assert settlement["net_settlement_cents"] == 3899998, (
            "4000000 - 100002 input-share total"
        )


class TestTrueUp:
    def _countersigned(self, api):
        ctx = setup_settlement_scenario(
            "FLEX", price_source="ACTUAL", yield_bu_per_acre=200,
            harvest_price_cents_per_bu=500, clock="2027-11-15T00:00:00Z",
        )
        settlement = ctx["settlement"]
        validate_success(api.finalize_settlement(settlement["id"], MGR_1))
        return ctx, validate_success(
            api.countersign_settlement(settlement["id"], MGR_2)
        )

    def test_true_up_excludes_own_adjustment(self, api):
        """PRD §3.6: "The `billed_amount_cents` is the sum of `amount_cents` over the lease's installments belonging to the term whose `term_index` maps to the settlement's `crop_year`, excluding any adjustment installment created by this settlement itself, while adjustment installments created by earlier settlements do count. The `true_up_cents` is the `net_settlement_cents` minus the `billed_amount_cents`."
        PRD §3.6: "A manager whose `X-User-ID` differs from `finalized_by` — else `ERR_DUTY_SEGREGATION_VIOLATION` — countersigns a `FINALIZED` settlement, moving it to the terminal `COUNTERSIGNED` state."

        Design: Difficulty/combinatorial_formula/settlement_true_up_excludes_own_adjustment
        """
        ctx, settlement = self._countersigned(api)
        # net = 2200000 (gross 10000000 -> bonus 200000 + base 2000000);
        # billed = the two term-1 installments (1000000 + 1000000); the
        # adjustment created by THIS countersign is excluded from that sum.
        assert settlement["billed_amount_cents"] == 2000000
        assert settlement["true_up_cents"] == 200000
        assert settlement["status"] == "COUNTERSIGNED"

    def test_positive_true_up_creates_adjustment_installment(self, api):
        """PRD §3.6: "When the true-up is positive, an adjustment installment is created for the difference: its amount is the true-up, its due date is thirty days after the current clock, it bills the current `term_index`, it starts `SCHEDULED`, and it never feeds back into its own settlement's billed sum."

        Design: Difficulty/combinatorial_formula/settlement_true_up_excludes_own_adjustment
        """
        ctx, settlement = self._countersigned(api)
        assert settlement["true_up_cents"] == 200000
        installments = list_lease_installments(ctx["lease"]["id"])
        adjustments = [
            i for i in installments
            if i["amount_cents"] == 200000 and i["status"] == "SCHEDULED"
        ]
        assert len(adjustments) == 1, "exactly one adjustment installment created"
        assert_iso_instant_equal(adjustments[0]["due_date"], "2027-12-15T00:00:00Z")
        # Re-reading the settlement: the adjustment never fed back into billed.
        reread = get_settlement(settlement["id"])
        assert reread["billed_amount_cents"] == 2000000


class TestSettlementLifecycle:
    def test_settlement_dispute_refinalize_cycle_recomputes(self, api):
        """PRD §3.6: "Either lease party may dispute a `FINALIZED` settlement: the caller's `X-User-ID` must equal the lease's `tenant_id` or `landlord_id`, else `ERR_NOT_RESOURCE_OWNER`, and a successful dispute moves the settlement to `DISPUTED`."
        PRD §3.6: "A manager then re-finalizes from `DISPUTED` back to `FINALIZED` by supplying corrected `yield_bu_per_acre` and `harvest_price_cents_per_bu` values; every computed amount is recomputed and `finalized_by` is set anew."

        Design: Corner/state_machines/settlement_dispute_refinalize_cycle_recomputes
        """
        ctx = setup_finalized_settlement_scenario()  # ACTUAL 200/500, mgr-1
        settlement = ctx["settlement"]
        assert settlement["status"] == "FINALIZED"
        assert settlement["finalized_by"] == "mgr-1"

        disputed = validate_success(
            api.dispute_settlement(
                settlement["id"], make_tenant_headers(ctx["tenant"]["id"])
            )
        )
        assert disputed["status"] == "DISPUTED"

        refinalized = validate_success(
            api.refinalize_settlement(
                settlement["id"],
                {"yield_bu_per_acre": 210, "harvest_price_cents_per_bu": 500},
                MGR_3,
            )
        )
        assert refinalized["status"] == "FINALIZED"
        # gross = 210*500*100 = 10500000; bonus = round(1500000*0.2) = 300000.
        assert refinalized["landlord_amount_cents"] == 2300000
        assert refinalized["finalized_by"] == "mgr-3", (
            "refinalizer replaces the original finalizer"
        )

    def test_countersign_by_finalizing_manager_forbidden(self, api):
        """PRD §2.11: "A harvest settlement finalized by one manager must be countersigned by a different manager: the countersigning request's `X-User-ID` must differ from the settlement's `finalized_by`, or it is rejected with `ERR_DUTY_SEGREGATION_VIOLATION` (HTTP 403)."

        Design: Corner/cross_cutting_layers/countersign_by_finalizing_manager_forbidden
        """
        ctx = setup_finalized_settlement_scenario()  # finalized by mgr-1
        settlement = ctx["settlement"]
        same = api.countersign_settlement(settlement["id"], MGR_1)
        validate_error(same, ApiErrorId.ERR_DUTY_SEGREGATION_VIOLATION)
        other = validate_success(api.countersign_settlement(settlement["id"], MGR_2))
        assert other["status"] == "COUNTERSIGNED"

    def test_settlement_finalize_estimated_rejected(self, api):
        """PRD §3.6: "Finalization moves a `PROVISIONAL` settlement to `FINALIZED`, requires the `price_source` to be `ACTUAL` — an attempt on an estimated settlement fails with `ERR_PRICE_NOT_FINAL`"

        Design: Corner/errors/settlement_finalize_estimated_rejected
        """
        ctx = setup_settlement_scenario(
            "FLEX", price_source="ESTIMATED", yield_bu_per_acre=200,
            harvest_price_cents_per_bu=450,
        )
        settlement = ctx["settlement"]
        assert settlement["status"] == "PROVISIONAL"
        resp = api.finalize_settlement(settlement["id"], MGR)
        validate_error(resp, ApiErrorId.ERR_PRICE_NOT_FINAL)
        assert get_settlement(settlement["id"])["status"] == "PROVISIONAL"

    def test_settlement_second_final_year_rejected(self, api):
        """PRD §3.6: "Only one non-`VOID` settlement may exist for a lease and crop year: an existing sibling in `FINALIZED`, `DISPUTED`, or `COUNTERSIGNED` blocks creation with `ERR_SETTLEMENT_YEAR_FINAL_EXISTS`, while an existing `PROVISIONAL` sibling is superseded to `VOID` by the newcomer."

        Design: Corner/errors/settlement_second_final_year_rejected
        """
        ctx = setup_finalized_settlement_scenario()  # FINALIZED for 2027
        lease = get_lease(ctx["lease"]["id"])
        resp = api.create_settlement(
            create_settlement_payload(
                lease["id"],
                expected_lease_version=lease["version"],
                yield_bu_per_acre=195,
                harvest_price_cents_per_bu=505,
            ),
            MGR,
        )
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_YEAR_FINAL_EXISTS)


class TestSettlementAndExpenseGuards:
    def test_settlement_create_on_cash_lease_rejected(self, api):
        """PRD §3.6: "Creation requires the lease to be `ACTIVE`, `TERMINATION_PENDING`, or `TERMINATED`, else `ERR_LEASE_NOT_ACTIVE`; a `CASH` lease is rejected with `ERR_SETTLEMENT_NOT_APPLICABLE`"

        Design: Corner/errors/settlement_create_on_cash_lease_rejected
        """
        ctx = setup_active_lease("CASH")
        lease = get_lease(ctx["lease"]["id"])
        resp = api.create_settlement(
            create_settlement_payload(
                lease["id"], expected_lease_version=lease["version"]
            ),
            MGR,
        )
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_NOT_APPLICABLE)

    def test_expense_rejection_from_submitted(self, api):
        """PRD §3.6: "Managers then review: approval moves the record to `APPROVED` and stamps `approved_at` from the clock; rejection moves it to `REJECTED`. Both are terminal."
        PRD §3.6: "The `input_share_total_cents` is the sum of the `landlord_share_cents` over the lease's expense records for the same `crop_year` that are in `APPROVED` status — submitted or rejected expenses are excluded"

        Design: Corner/state_machines/expense_rejection_from_submitted
        """
        ctx = setup_active_lease("SHARE")
        expense = submit_expense(
            ctx, category="FUEL", total_cost_cents=100001
        )
        assert expense["status"] == "SUBMITTED"
        rejected = validate_success(api.reject_expense(expense["id"], MGR))
        assert rejected["status"] == "REJECTED"

        settlement = create_settlement(ctx, price_source="ACTUAL")
        assert settlement["input_share_total_cents"] == 0, (
            "the REJECTED expense is excluded from the input-share sum"
        )
        assert settlement["landlord_amount_cents"] == 4000000
        assert settlement["net_settlement_cents"] == 4000000
