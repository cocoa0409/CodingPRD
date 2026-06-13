"""Money calculations: recurring tuition, pro-shop pricing, buyout, dual-variant
discount divergence, and rounding-order discipline.

Covers difficulty rules dual_variant_calc and combinatorial_formula plus the
non-stub calculation corner instances.
"""
import pytest
from test_helpers import (
    validate_success, get_success_data,
    set_clock, create_program, create_member, create_family,
    setup_family_with_members, setup_contract, sign_contract, run_billing,
    run_billing_and_pay,
    get_invoices, setup_member_at_rank_order, place_pro_shop_order,
    member_version, TEST_USERS,
)
from test_helpers import api_client

FD = TEST_USERS["front_desk_headers"]


class TestDualVariantBuyoutDiscount:
    """The provisional buyout quote uses the LIVE family tier; the final BUYOUT
    invoice uses the contract's PINNED locked_family_discount_pct."""

    def _setup_2member_then_grow_to_4(self):
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program(base_monthly_tuition_cents=12000)
        fam = create_family(surname="Sato", billing_email="sato2@x.com")
        m1 = create_member(full_name="Aki", family_id=fam["id"], waiver_signed=True)
        create_member(full_name="Beni", family_id=fam["id"], waiver_signed=True)
        # Sign at the 2-member tier -> pinned 0.10.
        contract = sign_contract(m1["id"], prog["id"], m1["version"],
                                 term_months=6, billing_anchor_day=1)
        # Grow the family to 4 ACTIVE members -> live tier rises to 0.20.
        create_member(full_name="Ceni", family_id=fam["id"], waiver_signed=True)
        create_member(full_name="Deni", family_id=fam["id"], waiver_signed=True)
        return prog, m1, contract

    def test_provisional_quote_uses_live_family_tier(self, api):
        """PRD §3.6: "The provisional figure follows the same evaluation order as
        the final buyout, but projects the monthly tuition using the *live* family
        discount tier (the current roster) rather than the pinned percentage, so a
        provisional quote can legitimately differ from the eventual authoritative
        charge."

        Design: Difficulty/dual_variant_calc/buyout_provisional_live_vs_final_pinned_discount
        """
        prog, m1, contract = self._setup_2member_then_grow_to_4()
        quote = validate_success(api.get_buyout_quote(contract["id"], FD), 200)
        # Live 0.20: monthly 9600, 6 months remaining, 0.5 rate -> 28800.
        assert quote["provisional_buyout_cents"] == 28800, quote
        assert quote["live_discount_pct"] == pytest.approx(0.20), quote

    def test_final_buyout_invoice_uses_pinned_discount(self, api):
        """PRD §3.6: "then compute the monthly tuition value exactly as the
        recurring tuition charge would (which itself uses the contract's pinned
        `locked_family_discount_pct`); then multiply the remaining months by that
        monthly value and by the buyout rate of 50 percent, rounding half up; then
        cap the result so the buyout never exceeds 50000 cents."

        Design: Difficulty/dual_variant_calc/buyout_provisional_live_vs_final_pinned_discount
        """
        prog, m1, contract = self._setup_2member_then_grow_to_4()
        terminated = validate_success(
            api.terminate_contract(contract["id"], {"expected_contract_version": contract["version"]}, FD), 200)
        assert terminated["status"] == "TERMINATED"
        buyouts = get_invoices(m1["id"], kind="BUYOUT")
        assert len(buyouts) == 1, buyouts
        # Pinned 0.10: monthly 10800, 6 months, 0.5 rate -> 32400.
        assert buyouts[0]["amount_due_cents"] == 32400, buyouts[0]


class TestFamilyTierLiveVsPinned:
    """Family.active_member_count and its live tier recompute on a withdraw, but a
    signed contract keeps its pinned locked_family_discount_pct."""

    def test_family_count_recomputes_but_contract_pin_holds(self, api):
        """PRD §3.2: "The **pinned** tier is a snapshot: at the moment a contract is
        signed, the then-current live discount is frozen onto the contract as
        `locked_family_discount_pct`, and every recurring invoice that contract ever
        generates uses that pinned value regardless of any later change in family size."

        Design: Difficulty/dual_variant_calc/family_tier_live_recompute_vs_contract_pinned
        """
        prog = create_program(base_monthly_tuition_cents=10000)
        fam, members = setup_family_with_members(3, surname="Kim")
        m1, m2 = members[0], members[1]
        # m1 signs while the family has 3 ACTIVE members -> pinned 0.15.
        contract = sign_contract(m1["id"], prog["id"], m1["version"], term_months=12)
        # Withdraw m2 -> live tier drops to 2-member 0.10.
        get_success_data(api.withdraw_member(m2["id"], {"expected_member_version": m2["version"]}, FD))
        fam_after = validate_success(api.get_family(fam["id"], FD), 200)
        assert fam_after["active_member_count"] == 2, fam_after
        ctr_after = validate_success(api.get_contract(contract["id"], FD), 200)
        assert ctr_after["locked_family_discount_pct"] == pytest.approx(0.15), ctr_after

    def test_contract_pins_two_member_tier_at_signing(self, api):
        """PRD §3.2: "exactly two counted members earns 10 percent ... The boundary
        is inclusive on the low side of each tier — two members yields exactly 10
        percent, not the solo rate."

        Design: Difficulty/dual_variant_calc/family_tier_live_recompute_vs_contract_pinned
        """
        prog = create_program(base_monthly_tuition_cents=10000)
        fam, members = setup_family_with_members(2, surname="Two")
        m1 = members[0]
        contract = sign_contract(m1["id"], prog["id"], m1["version"], term_months=12)
        assert contract["locked_family_discount_pct"] == pytest.approx(0.10), contract


class TestProShopRoundingOrder:
    """Pro-shop pricing rounds each line item's discount BEFORE summing."""

    def test_round_per_line_then_sum_two_lines(self, api):
        """PRD §2.8: "for each line, the system multiplies `unit_price_cents` by
        `qty`, computes the discount as that product times the discount percentage
        rounded half up to whole cents, subtracts the rounded discount from the line
        total, and then sums the discounted line totals. Rounding is applied per line
        item *before* summing — never sum-then-round."

        Design: Difficulty/combinatorial_formula/pro_shop_round_per_line_then_sum
        """
        # Member at rank_order 2 -> 0.10 belt-loyalty discount.
        prog, member, enrollment, instructor = setup_member_at_rank_order(2)
        order = place_pro_shop_order(member["id"], [
            {"sku": "PATCH", "unit_price_cents": 105, "qty": 1},
            {"sku": "STRIPE", "unit_price_cents": 105, "qty": 1},
        ])
        assert order["gross_cents"] == 210, order
        # Per line: 105 - rhu(10.5)=11 -> 94 each; summed -> 188 (NOT 189).
        assert order["net_cents"] == 188, order
        assert order["net_cents"] != 189, order

    def test_round_per_line_diverges_from_sum_then_round(self, api):
        """PRD §2.8: "Rounding is applied per line item *before* summing — never
        sum-then-round."

        Design: Difficulty/combinatorial_formula/pro_shop_round_per_line_then_sum
        """
        # Member at rank_order 2 -> 0.10 belt-loyalty discount.
        prog, member, enrollment, instructor = setup_member_at_rank_order(2)
        order = place_pro_shop_order(member["id"], [
            {"sku": "A", "unit_price_cents": 15, "qty": 1},
            {"sku": "B", "unit_price_cents": 15, "qty": 1},
        ])
        assert order["gross_cents"] == 30, order
        # Per line: 15 - rhu(1.5)=2 -> 13 each; summed -> 26 (sum-then-round would be 27).
        assert order["net_cents"] == 26, order
        assert order["net_cents"] != 27, order

    def test_high_belt_15pct_per_line_discount(self, api):
        """PRD §2.8: "If that highest rank order is at least 5, the member's discount
        is 15 percent; otherwise, if it is at least 2, the discount is 10 percent;
        otherwise it is 0 percent."

        Design: Corner/calculations/proshop_high_belt_15pct_discount
        """
        prog, member, enrollment, instructor = setup_member_at_rank_order(5)
        order = place_pro_shop_order(member["id"], [
            {"sku": "GI", "unit_price_cents": 2500, "qty": 1},
            {"sku": "RASH", "unit_price_cents": 1999, "qty": 2},
        ])
        assert order["gross_cents"] == 6498, order
        # 0.15 per line: 2500 - 375 = 2125 ; 3998 - rhu(599.7)=600 -> 3398 ; sum 5523.
        assert order["net_cents"] == 5523, order


class TestBuyoutEvaluationOrder:
    """Buyout: compute monthly (with pinned discount), then rate-multiply, then cap."""

    def test_cap_applied_after_rate_multiply(self, api):
        """PRD §3.6: "then multiply the remaining months by that monthly value and by
        the buyout rate of 50 percent, rounding half up; then cap the result so the
        buyout never exceeds 50000 cents."

        Design: Difficulty/combinatorial_formula/buyout_evaluation_order_monthly_then_cap
        """
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program(base_monthly_tuition_cents=12000)
        fam, members = setup_family_with_members(2, surname="Wu")
        m1 = members[0]
        contract = sign_contract(m1["id"], prog["id"], m1["version"], term_months=12)
        # Settle each invoice so the member stays ACTIVE (balance below the 10000-cent
        # suspension threshold) and the contract stays ACTIVE/terminable across runs.
        run_billing_and_pay(contract["id"], m1["id"])
        contract = run_billing_and_pay(contract["id"], m1["id"])
        assert contract["months_billed"] == 2, contract
        terminated = validate_success(
            api.terminate_contract(contract["id"], {"expected_contract_version": contract["version"]}, FD), 200)
        assert terminated["status"] == "TERMINATED"
        buyouts = get_invoices(m1["id"], kind="BUYOUT")
        assert len(buyouts) == 1, buyouts
        # remaining 10, monthly 10800 (pinned 0.10), raw rhu(10*10800*0.5)=54000 -> capped 50000.
        assert buyouts[0]["amount_due_cents"] == 50000, buyouts[0]

    def test_buyout_raw_value_capped_not_truncated_early(self, api):
        """PRD §3.6: "the monthly tuition value exactly as the recurring tuition
        charge would (which itself uses the contract's pinned
        `locked_family_discount_pct`)."

        Design: Difficulty/combinatorial_formula/buyout_evaluation_order_monthly_then_cap
        """
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program(base_monthly_tuition_cents=12000)
        fam, members = setup_family_with_members(2, surname="Wu2")
        m1 = members[0]
        contract = sign_contract(m1["id"], prog["id"], m1["version"], term_months=12)
        # Settle each invoice so the contract stays ACTIVE/terminable across runs.
        run_billing_and_pay(contract["id"], m1["id"])
        contract = run_billing_and_pay(contract["id"], m1["id"])
        validate_success(
            api.terminate_contract(contract["id"], {"expected_contract_version": contract["version"]}, FD), 200)
        buyouts = get_invoices(m1["id"], kind="BUYOUT")
        # Confirm the result is exactly the cap, proving raw (54000) exceeded it.
        assert buyouts[0]["amount_due_cents"] == 50000, buyouts[0]


class TestRecurringTuition:
    """Recurring tuition rounds the discount on the single base amount."""

    def test_solo_member_no_discount(self, api):
        """PRD §3.6: "the discount in cents is the base amount times the pinned
        percentage, rounded half up to whole cents, and the invoice's
        `amount_due_cents` is the base minus that rounded discount, floored at 0."

        Design: Corner/calculations/recurring_tuition_no_discount_solo
        """
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program(base_monthly_tuition_cents=12000)
        member = create_member()
        contract = sign_contract(member["id"], prog["id"], member["version"], term_months=12)
        run_billing(contract["id"])
        invoices = get_invoices(member["id"], kind="TUITION")
        assert len(invoices) == 1, invoices
        assert invoices[0]["amount_due_cents"] == 12000, invoices[0]
