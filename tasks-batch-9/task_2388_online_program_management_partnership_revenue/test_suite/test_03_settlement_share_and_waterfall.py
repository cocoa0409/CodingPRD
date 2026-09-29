"""Per-line share rounding and the pinned order of the settlement waterfall."""

import pytest

from test_helpers import assertions, fixtures


class TestPerLineShareRoundingBeforeSumming:
    @pytest.fixture
    def two_line_milestone_period(self, api):
        """A MILESTONE_CHRONOLOGICAL contract with two paid enrollments at 3 and 1 credits."""
        context = fixtures.build_launched_program(
            api,
            partnership_overrides={"revenue_recognition_method": "MILESTONE_CHRONOLOGICAL"},
        )
        ps_id, pg_id, co_id = context["ps_id"], context["pg_id"], context["co_id"]

        first_lead = fixtures.create_applied_lead(api, ps_id, pg_id, co_id)
        first_enrollment = fixtures.enroll_lead(api, first_lead["id"])
        second_lead = fixtures.create_applied_lead(
            api,
            ps_id,
            pg_id,
            co_id,
            hours_to_first_contact=9,
            prospect_external_id="P-1002",
            source_channel="PAID_SOCIAL",
        )
        second_enrollment = fixtures.enroll_lead(api, second_lead["id"], student_external_id="S-2002")

        fixtures.set_clock(api, fixtures.CLOCK_SEP_5)
        fixtures.post_tuition_entry(api, first_enrollment["id"])
        fixtures.record_progress(api, first_enrollment["id"], 3)
        fixtures.post_tuition_entry(api, second_enrollment["id"])
        fixtures.record_progress(api, second_enrollment["id"], 1)
        fixtures.post_marketing_entry(api, ps_id, pg_id, amount_cents=300000)
        fixtures.set_clock(api, fixtures.CLOCK_OCT_1)

        context["en_id"] = first_enrollment["id"]
        context["en2_id"] = second_enrollment["id"]
        return context

    def test_each_line_share_is_rounded_before_the_lines_are_summed(
        self, api, two_line_milestone_period
    ):
        """Two milestone lines at the 0.575 marginal rate must land on 143,751 cents.

        PRD: "The rounding order here is pinned and consequential: **each line's accumulated
        share is rounded half up to whole cents, and the rounded integers are then summed**
        into `share_gross_cents`. Summing exact line shares and rounding once at the end is
        forbidden."
        PRD: "The two orders differ by whole cents — two lines of 187,500 and 62,500 cents at a
        rate of 0.575 give 107,813 plus 35,938, so 143,751 cents per-line, against 143,750 cents
        if summed first and rounded once."

        Design: Difficulty/combinatorial_formula/partner_share_rounds_each_recognition_line_before_summing
        """
        statement = fixtures.cut_statement(api, two_line_milestone_period["ps_id"])

        assert statement["line_count"] == 2
        assert statement["recognized_revenue_cents"] == 250000
        assert statement["share_gross_cents"] == 143751
        assert statement["share_gross_cents"] != 143750

    def test_two_line_statement_carries_the_waterfall_through_to_net_payable(
        self, api, two_line_milestone_period
    ):
        """The waterfall runs on the per-line gross, not on a re-rounded total.

        PRD: "Step 5 sets `subtotal_cents` to `share_gross_cents` minus
        `marketing_recoupment_cents`."
        PRD: "Step 7 sets `fee_for_service_cents` to the partnership's
        `fee_schedule_monthly_cents` when `contract_structure` is `FEE_FOR_SERVICE` and to 0
        otherwise, and sets `net_payable_cents` to `subtotal_cents` minus `holdback_cents` plus
        `fee_for_service_cents`."

        Design: Difficulty/combinatorial_formula/partner_share_rounds_each_recognition_line_before_summing
        """
        statement = fixtures.cut_statement(api, two_line_milestone_period["ps_id"])

        assert statement["marketing_recoupment_cents"] == 21562
        assert statement["subtotal_cents"] == 122189
        assert statement["holdback_cents"] == 6109
        assert statement["net_payable_cents"] == 116080
        assertions.assert_waterfall_internally_consistent(statement)


class TestNetPayableEvaluationOrder:
    @pytest.fixture
    def september_ready_to_cut(self, api):
        """One paid enrollment and 300,000 cents of unrecouped spend, clock at 2026-10-01."""
        return fixtures.build_paid_enrollment(
            api, marketing_spend_cents=300000, final_clock=fixtures.CLOCK_OCT_1
        )

    def test_recoupment_ceiling_is_floored_on_the_gross_share(self, api, september_ready_to_cut):
        """The ceiling is 15 percent of gross taken with a floor, never a share of the subtotal.

        PRD: "Step 3 derives a recoupment ceiling as `share_gross_cents` multiplied by 0.15 and
        taken with a **floor**, not rounded half up: the cap never rounds up in the partner's
        favour."
        PRD: "the recoupment ceiling is a function of `share_gross_cents` and never of
        `subtotal_cents`, while the holdback tier is a function of `subtotal_cents` and
        therefore of the position *after* recoupment."

        Design: Difficulty/combinatorial_formula/net_payable_order_caps_recoupment_on_gross_then_tiers_holdback_on_subtotal
        """
        statement = fixtures.cut_statement(api, september_ready_to_cut["ps_id"])

        assert statement["recognition_method_applied"] == "PERIOD_STRAIGHT_LINE"
        assert statement["recognized_revenue_cents"] == 159198
        assert statement["share_gross_cents"] == 91539
        assert statement["marketing_recoupment_cents"] == 13730
        assert statement["marketing_recoupment_cents"] != 11671

    def test_holdback_tier_is_selected_from_the_subtotal_after_recoupment(
        self, api, september_ready_to_cut
    ):
        """The holdback tier reads the position after the sweep, and the exit is CALCULATED.

        PRD: "Step 6 selects `holdback_pct` from `subtotal_cents`: 0.10 when the subtotal is at
        least $100,000, and 0.05 otherwise — the comparison is inclusive at the trigger."
        PRD: "A new statement is created in `CALCULATED`, records the acting `X-User-ID` as
        `authored_by_user_id`, sets `partnership_id`, initialises `adjustment_delta_cents` to 0
        and `requires_recalculation` to false, leaves `approved_by_user_id`,
        `resolved_by_user_id`, `dispute_reason`, `remittance_reference` and `remitted_at` null,
        and increments the partnership's `version` by one."

        Design: Difficulty/combinatorial_formula/net_payable_order_caps_recoupment_on_gross_then_tiers_holdback_on_subtotal
        """
        statement = fixtures.cut_statement(api, september_ready_to_cut["ps_id"])

        assert statement["subtotal_cents"] == 77809
        assert statement["holdback_pct"] == pytest.approx(0.05, abs=0.0001)
        assert statement["holdback_cents"] == 3890
        assert statement["net_payable_cents"] == 73919
        assert statement["status"] == "CALCULATED"
        assert statement["requires_recalculation"] is False
