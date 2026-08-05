"""Difficulty queue A — dual-variant and combinatorial money formulas.

Covers move-out proration (provisional block vs daily settlement), payout
accrual-projection vs cash-final settlement, per-invoice platform-fee rounding,
and the late-fee tier keyed on subtotal.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    active_tenancy, active_tenancy_with_open_invoice,
    file_notice, new_invoice, assess_fee, pay_invoice, do_move_out,
    new_payout, project, read_membership, read_invoice, read_payout,
    manager_headers, finance_headers,
)


# ==========================================================================
# dual_variant_calc / move_out_proration_whole_period_block_vs_daily_settlement
# ==========================================================================
class TestMoveOutProrationDualVariant:
    def _setup_notice_and_invoice(self, api):
        ctx = active_tenancy(api, weekly=25000, monthly=100000, budget=60000)
        mem = ctx["membership"]["id"]
        notice = file_notice(api, mem, "MEMBER_INITIATED", "2026-06-18",
                             member_id=ctx["member"]["id"])
        from test_helpers import set_clock
        set_clock(api, "2026-06-18T00:00:00Z")
        inv = new_invoice(api, mem, "2026-06-15", "2026-06-21")
        return ctx, mem, notice, inv

    def test_provisional_notice_block_charges_full_period_subtotal(self, api):
        """PRD §3.8: "It charges the entire period containing the move-out date
        with no daily refund whatsoever: the provisional final charge equals the
        full period subtotal."

        Design: Difficulty/dual_variant_calc/move_out_proration_whole_period_block_vs_daily_settlement
        """
        ctx = active_tenancy(api, weekly=25000, monthly=100000, budget=60000)
        mem = ctx["membership"]["id"]
        notice = file_notice(api, mem, "MEMBER_INITIATED", "2026-06-18",
                             member_id=ctx["member"]["id"])
        assert notice["provisional_final_charge_cents"] == 39000
        assert read_membership(api, mem)["provisional_final_charge_cents"] == 39000

    def test_final_settlement_daily_prorates_and_writes_negative_adjustment(self, api):
        """PRD §3.8: "the number of days from the target period's start through the
        actual_move_out_date inclusive of the move-out day; and the final charge
        is the daily rate multiplied by that occupied-day count as an exact
        integer product". PRD §3.8: "The proration adjustment written onto the
        invoice is the final charge minus the period subtotal, which is negative
        (a credit) whenever the resident occupied fewer than a full period's days."

        Design: Difficulty/dual_variant_calc/move_out_proration_whole_period_block_vs_daily_settlement
        """
        ctx, mem, notice, inv = self._setup_notice_and_invoice(api)
        assert inv["subtotal_cents"] == 39000
        result = validate_success(api.move_out(
            mem, {"actual_move_out_date": "2026-06-18"}, manager_headers()))
        assert result["final_charge_cents"] == 22284
        assert result["provisional_final_charge_cents"] == 39000
        assert result["final_charge_cents"] != result["provisional_final_charge_cents"]
        assert result["tenancy_status"] == "MOVED_OUT"
        assert result["billing_status"] == "CURRENT"
        assert result["balance_due_cents"] == 22284
        updated_inv = read_invoice(api, inv["id"])
        assert updated_inv["proration_adjustment_cents"] == -16716
        assert updated_inv["total_amount_cents"] == 22284


# ==========================================================================
# dual_variant_calc / payout_accrual_projection_vs_cash_final_settlement
# ==========================================================================
class TestPayoutAccrualVsCashVariant:
    def _setup(self, api):
        from test_helpers import set_clock
        ctx = active_tenancy(api, weekly=25000, monthly=100000, budget=60000)
        mem = ctx["membership"]["id"]
        invA = new_invoice(api, mem, "2026-06-01", "2026-06-07")
        set_clock(api, "2026-06-06T00:00:00Z")
        assess_fee(api, invA["id"])
        pay_invoice(api, invA["id"], 41500, "ACH", member_id=ctx["member"]["id"])
        set_clock(api, "2026-06-15T00:00:00Z")
        invB = new_invoice(api, mem, "2026-06-15", "2026-06-21")
        payout = new_payout(api, ctx["house"]["id"], "2026-06-01", "2026-06-30")
        return ctx, invA, invB, payout

    def test_accrual_projection_reads_billed_totals_and_withholds_reserve(self, api):
        """PRD §3.10: "The gross_cents is the sum of total_amount_cents over the
        cycle invoices (billed, not collected)." PRD §3.10: "The reserve_cents is
        the gross times a reserve rate of 0.05, rounded half up. The
        net_payout_cents is the gross minus the platform fee minus the maintenance
        credit minus the reserve, floored at zero."

        Design: Difficulty/dual_variant_calc/payout_accrual_projection_vs_cash_final_settlement
        """
        ctx, invA, invB, payout = self._setup(api)
        projected = project(api, payout["id"])
        assert projected["gross_cents"] == 80500
        assert projected["platform_fee_cents"] == 10063
        assert projected["reserve_cents"] == 4025
        assert projected["net_payout_cents"] == 66412
        assert projected["variant_applied"] == "ACCRUAL_PROJECTION"

    def test_cash_final_release_reads_collected_and_releases_reserve(self, api):
        """PRD §3.10: "the gross_cents is the sum of amount_paid_cents over the
        cycle invoices (collected only)"; "the reserve_cents drops to zero; and
        the net_payout_cents is gross minus platform fee minus maintenance credit,
        floored at zero — the same invoice set therefore produces a different net
        than the projection did".

        Design: Difficulty/dual_variant_calc/payout_accrual_projection_vs_cash_final_settlement
        """
        ctx, invA, invB, payout = self._setup(api)
        project(api, payout["id"])
        released = validate_success(api.release_payout(payout["id"], finance_headers("fa-2")))
        assert released["status"] == "RELEASED"
        assert released["variant_applied"] == "CASH_FINAL"
        assert released["gross_cents"] == 41500
        assert released["platform_fee_cents"] == 5188
        assert released["reserve_cents"] == 0
        assert released["net_payout_cents"] == 36312
        assert released["net_payout_cents"] != 66412


# ==========================================================================
# combinatorial_formula / platform_fee_rounded_per_invoice_then_summed
# ==========================================================================
class TestPlatformFeePerInvoiceRounding:
    def _setup(self, api):
        from test_helpers import set_clock
        ctx = active_tenancy(api, weekly=25000, monthly=100000, budget=60000)
        mem = ctx["membership"]["id"]
        member_id = ctx["member"]["id"]
        file_notice(api, mem, "MEMBER_INITIATED", "2026-06-18", member_id=member_id)
        invA = new_invoice(api, mem, "2026-06-01", "2026-06-07")
        set_clock(api, "2026-06-06T00:00:00Z")
        assess_fee(api, invA["id"])
        pay_invoice(api, invA["id"], 41500, "ACH", member_id=member_id)
        set_clock(api, "2026-06-18T00:00:00Z")
        invB = new_invoice(api, mem, "2026-06-15", "2026-06-21")
        do_move_out(api, mem, "2026-06-18")
        pay_invoice(api, invB["id"], 22284, "CARD", member_id=member_id)
        payout = new_payout(api, ctx["house"]["id"], "2026-06-01", "2026-06-30")
        return ctx, invA, invB, payout

    def test_fee_is_sum_of_per_invoice_rounded_lines_not_round_of_sum(self, api):
        """PRD §3.10: "The platform_fee_cents is the sum, over those same invoices,
        of each invoice's total_amount_cents times a platform fee rate of 0.125,
        rounded half up per invoice and then summed — the rounding is per-invoice
        and the sum of rounded lines is the answer; summing first and rounding once
        is wrong."

        Design: Difficulty/combinatorial_formula/platform_fee_rounded_per_invoice_then_summed
        """
        ctx, invA, invB, payout = self._setup(api)
        assert read_invoice(api, invA["id"])["total_amount_cents"] == 41500
        assert read_invoice(api, invB["id"])["total_amount_cents"] == 22284
        projected = project(api, payout["id"])
        assert projected["gross_cents"] == 63784
        assert projected["platform_fee_cents"] == 7974
        assert projected["platform_fee_cents"] != 7973

    def test_reserve_and_net_use_the_per_invoice_fee(self, api):
        """PRD §3.10: "The reserve_cents is the gross times a reserve rate of 0.05,
        rounded half up. The net_payout_cents is the gross minus the platform fee
        minus the maintenance credit minus the reserve, floored at zero."

        Design: Difficulty/combinatorial_formula/platform_fee_rounded_per_invoice_then_summed
        """
        ctx, invA, invB, payout = self._setup(api)
        projected = project(api, payout["id"])
        assert projected["reserve_cents"] == 3189
        assert projected["net_payout_cents"] == 52621


# ==========================================================================
# combinatorial_formula / late_fee_tier_keyed_on_subtotal_not_on_total
# ==========================================================================
class TestLateFeeTierKeyedOnSubtotal:
    def _setup_overdue_invoice(self, api):
        from test_helpers import set_clock
        ctx = active_tenancy_with_open_invoice(
            api, weekly=25000, monthly=100000, budget=60000,
            period_start="2026-06-01", period_end="2026-06-07")
        set_clock(api, "2026-06-06T00:00:00Z")
        return ctx

    def test_tier_keys_on_subtotal_yielding_2500_not_4000(self, api):
        """PRD §3.5: "if subtotal_cents is at least 20000 but below 40000 cents the
        fee is 2500 cents". PRD §3.5: "The tier keys strictly on the subtotal, so
        proration and prior fees never move an invoice into a different late-fee
        band."

        Design: Difficulty/combinatorial_formula/late_fee_tier_keyed_on_subtotal_not_on_total
        """
        ctx = self._setup_overdue_invoice(api)
        inv = ctx["invoice"]
        assert inv["base_rent_cents"] == 25000
        assert inv["utility_share_cents"] == 14000
        assert inv["occupied_rooms_at_period_start"] == 1
        assert inv["subtotal_cents"] == 39000
        result = validate_success(api.fee_adjustment(inv["id"], {"action": "ASSESS"},
                                                     finance_headers()))
        assert result["late_fee_cents"] == 2500
        assert result["late_fee_cents"] != 4000
        assert result["total_amount_cents"] == 41500

    def test_assessment_drives_invoice_and_billing_past_due(self, api):
        """PRD §3.6: "An assessment sets late_fee_cents from the subtotal tier of
        §3.5, raises total_amount_cents by that fee, drives the invoice to
        PAST_DUE, drives the tenancy's billing_status from CURRENT to PAST_DUE, and
        recomputes balance_due_cents."

        Design: Difficulty/combinatorial_formula/late_fee_tier_keyed_on_subtotal_not_on_total
        """
        ctx = self._setup_overdue_invoice(api)
        inv = ctx["invoice"]
        result = validate_success(api.fee_adjustment(inv["id"], {"action": "ASSESS"},
                                                     finance_headers()))
        assert result["status"] == "PAST_DUE"
        membership = read_membership(api, ctx["membership"]["id"])
        assert membership["billing_status"] == "PAST_DUE"
        assert membership["balance_due_cents"] == 41500
