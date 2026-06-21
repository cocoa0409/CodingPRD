"""Monthly-charge computation: full-month vs prorated move-in, the pinned per-line rounding
order, and the open-balance conservation invariant across issue then void.

Citations are verbatim from PRD.md §3.8.
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    setup_admitted_resident, create_statement,
    TEST_USERS,
)

BILLING = TEST_USERS["billing_clerk_headers"]
STAFF = TEST_USERS["staff_headers"]

# Canonical LEVEL_2 resident assessment: adl all 2 (sum 10) -> 30, cognition 0, behavior 0.
_LEVEL_2_ASMT = {
    "adl_bathing": 2, "adl_dressing": 2, "adl_toileting": 2,
    "adl_transferring": 2, "adl_eating": 2, "cognition_score": 0, "behavior_flags": 0,
}


class TestMonthlyChargeFullVsProrated:
    """The first/move-in statement prorates and applies the community fee; an ordinary
    statement charges the full month with no fee — two algorithms, different cents."""

    def test_first_statement_is_prorated_with_community_fee(self, api):
        """PRD §3.8: "the `rent_charge_cents` is the base-rent monthly figure multiplied by
        billable days, divided by days in the month, rounded half up to whole cents; the
        `care_points_charge_cents` is the care-points monthly figure multiplied by billable days,
        divided by days in the month, rounded half up to whole cents; and the
        `community_fee_charge_cents` is the agreement's `community_fee_cents`."

        Design: Difficulty/dual_variant_calc/monthly_charge_full_vs_prorated_on_billing
        """
        # LEVEL_2 resident (cp 30), rate 1500 -> care month 45000; base rent 401500.
        # Jan 2026 (31 days), move-in day 10 -> 22 billable days; community fee 250000.
        ctx = setup_admitted_resident(
            care_point_rate_cents=1500, base_rent_cents=401500,
            move_in_date="2026-01-10", community_fee_cents=250000,
            assessment_overrides=_LEVEL_2_ASMT,
        )
        stmt = create_statement(ctx["resident"]["id"], 2026, 1, is_first_statement=True)
        issued = validate_success(api.issue_billing_statement(stmt["id"], BILLING), 200)
        assert issued["rent_charge_cents"] == 284935
        assert issued["care_points_charge_cents"] == 31935
        assert issued["community_fee_charge_cents"] == 250000
        assert issued["total_charge_cents"] == 566870

    def test_full_month_statement_no_proration_no_fee(self, api):
        """PRD §3.8: "For an ordinary (non-first) statement there is no proration: the
        `rent_charge_cents` is the full base-rent monthly figure, the `care_points_charge_cents`
        is the full care-points monthly figure, and the `community_fee_charge_cents` is zero."

        Design: Difficulty/dual_variant_calc/monthly_charge_full_vs_prorated_on_billing
        """
        ctx = setup_admitted_resident(
            care_point_rate_cents=1500, base_rent_cents=401500,
            move_in_date="2026-01-10", community_fee_cents=250000,
            assessment_overrides=_LEVEL_2_ASMT,
        )
        stmt = create_statement(ctx["resident"]["id"], 2026, 2, is_first_statement=False)
        issued = validate_success(api.issue_billing_statement(stmt["id"], BILLING), 200)
        assert issued["rent_charge_cents"] == 401500
        assert issued["care_points_charge_cents"] == 45000
        assert issued["community_fee_charge_cents"] == 0
        assert issued["total_charge_cents"] == 446500


class TestMonthlyChargeRoundingOrder:
    """The pinned rounding order is round-each-line-then-sum, which differs from
    sum-then-round on fractional days."""

    def test_prorated_lines_rounded_independently_then_summed(self, api):
        """PRD §3.8: "The rounding order is pinned: each line is prorated and rounded to whole
        cents on its own, and only then are the lines summed — the two monthly figures must not
        be summed first and the combined total prorated, because on fractional days that order
        yields a different cent."

        Design: Difficulty/combinatorial_formula/monthly_charge_round_per_line_then_sum_mode_b
        """
        # Same prorated inputs but community fee 0, so total exposes the per-line sum: 316870.
        # Sum-then-round would give 316871; the PRD pins 316870.
        ctx = setup_admitted_resident(
            care_point_rate_cents=1500, base_rent_cents=401500,
            move_in_date="2026-01-10", community_fee_cents=0,
            assessment_overrides=_LEVEL_2_ASMT,
        )
        stmt = create_statement(ctx["resident"]["id"], 2026, 1, is_first_statement=True)
        issued = validate_success(api.issue_billing_statement(stmt["id"], BILLING), 200)
        assert issued["rent_charge_cents"] == 284935
        assert issued["care_points_charge_cents"] == 31935
        assert issued["total_charge_cents"] == 316870

    def test_total_equals_per_line_sum(self, api):
        """PRD §3.8: "The `total_charge_cents` is the sum of `rent_charge_cents`,
        `care_points_charge_cents`, and `community_fee_charge_cents`."

        Design: Difficulty/combinatorial_formula/monthly_charge_round_per_line_then_sum_mode_b
        """
        ctx = setup_admitted_resident(
            care_point_rate_cents=1500, base_rent_cents=401500,
            move_in_date="2026-01-10", community_fee_cents=0,
            assessment_overrides=_LEVEL_2_ASMT,
        )
        stmt = create_statement(ctx["resident"]["id"], 2026, 1, is_first_statement=True)
        issued = validate_success(api.issue_billing_statement(stmt["id"], BILLING), 200)
        expected = (issued["rent_charge_cents"]
                    + issued["care_points_charge_cents"]
                    + issued["community_fee_charge_cents"])
        assert issued["total_charge_cents"] == expected


class TestOpenBalanceConservation:
    """Issuing raises open_balance_cents by the statement total; voiding restores it."""

    def test_issue_raises_open_balance_by_total(self, api):
        """PRD §3.8: "At issuance the charge lines are computed and frozen, and the resident's
        `open_balance_cents` is recomputed because the statement now joins the open set."
        PRD §3.8: "The resident's `open_balance_cents` is the sum, over the resident's billing
        statements whose status is `ISSUED` or `PARTIALLY_PAID`, of each statement's
        `total_charge_cents` minus its `paid_cents`"

        Design: Difficulty/compensating_invariant/open_balance_conserved_issue_then_void
        """
        ctx = setup_admitted_resident(
            care_point_rate_cents=1500, base_rent_cents=401500,
            move_in_date="2026-09-15", community_fee_cents=0,
            assessment_overrides=_LEVEL_2_ASMT,
        )
        stmt = create_statement(ctx["resident"]["id"], 2026, 10, is_first_statement=False)
        issued = validate_success(api.issue_billing_statement(stmt["id"], BILLING), 200)
        assert issued["total_charge_cents"] == 446500
        res = validate_success(api.get_resident(ctx["resident"]["id"], STAFF), 200)
        assert res["open_balance_cents"] == 446500

    def test_void_restores_open_balance_to_zero(self, api):
        """PRD §3.8: "A `BillingClerk` may void a statement that is `ISSUED` or
        `PARTIALLY_PAID`, advancing it to `VOID`; voiding removes the statement from the
        resident's open set and recomputes the resident's `open_balance_cents`."

        Design: Difficulty/compensating_invariant/open_balance_conserved_issue_then_void
        """
        ctx = setup_admitted_resident(
            care_point_rate_cents=1500, base_rent_cents=401500,
            move_in_date="2026-09-15", community_fee_cents=0,
            assessment_overrides=_LEVEL_2_ASMT,
        )
        stmt = create_statement(ctx["resident"]["id"], 2026, 10, is_first_statement=False)
        validate_success(api.issue_billing_statement(stmt["id"], BILLING), 200)
        voided = validate_success(api.void_billing_statement(stmt["id"], BILLING), 200)
        assert voided["status"] == "VOID"
        res = validate_success(api.get_resident(ctx["resident"]["id"], STAFF), 200)
        assert res["open_balance_cents"] == 0
