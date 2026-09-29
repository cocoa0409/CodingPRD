"""Restating a settled September period on the other recognition variant."""

import pytest

from test_helpers import fixtures


@pytest.fixture
def calculated_september_statement(api):
    """September 2026 cut in CALCULATED under PERIOD_STRAIGHT_LINE, clock at 2026-10-01."""
    return fixtures.build_september_statement(api)


class TestRecognitionVariantSwitchRestatesTheSettlement:
    def test_resolution_override_reapplies_the_milestone_variant_to_the_same_period(
        self, api, calculated_september_statement
    ):
        """The identical period recognises the milestone figure once the override is supplied.

        PRD: "Under the `MILESTONE_CHRONOLOGICAL` variant, revenue accrues by academic progress
        instead. The cumulative recognised amount is `tuition_charged_cents` multiplied by
        `credits_completed`, divided by `credits_enrolled`, rounded half up to whole cents, and
        the line's amount is that cumulative figure minus the enrollment's
        `recognized_to_date_cents`."
        PRD: "When a statement is recomputed, whether by dispute resolution or by
        recalculation, the statement's own previously recorded line contributions are first
        **removed** from the enrollments' `recognized_to_date_cents` and from the partnership's
        `contract_year_recognized_cents`, so that the recompute sees exactly the baseline the
        original computation saw."

        Design: Difficulty/dual_variant_calc/recognition_variant_switch_restates_september_settlement
        """
        context = calculated_september_statement
        ps_id, st_id = context["ps_id"], context["st_id"]

        assert context["statement"]["recognition_method_applied"] == "PERIOD_STRAIGHT_LINE"
        assert context["statement"]["recognized_revenue_cents"] == 159198

        fixtures.dispute_statement(
            api,
            ps_id,
            st_id,
            "Straight-line accrual overstates the partner's earned share for a term that is "
            "only three credits complete.",
        )
        restated = fixtures.resolve_statement(
            api,
            st_id,
            recognition_method_override="MILESTONE_CHRONOLOGICAL",
            adjustment_note="Restated on the milestone basis for the September period.",
        )

        assert restated["recognition_method_applied"] == "MILESTONE_CHRONOLOGICAL"
        assert restated["recognized_revenue_cents"] == 187500
        assert restated["share_gross_cents"] == 107813
        assert restated["status"] == "RESOLVED_ADJUSTED"

    def test_restated_waterfall_pins_the_adjustment_delta(self, api, calculated_september_statement):
        """The restated waterfall and the delta against the pre-resolution net payable.

        PRD: "Resolution re-runs all three settlement computations — so
        `recognized_revenue_cents`, `share_gross_cents`, `marketing_recoupment_cents`,
        `subtotal_cents`, `holdback_pct`, `holdback_cents`, `fee_for_service_cents` and
        `net_payable_cents` are all recomputed under the recompute semantics above — pins
        `adjustment_delta_cents` to the new `net_payable_cents` minus the pre-resolution
        `net_payable_cents`, and records the acting `X-User-ID` as `resolved_by_user_id`."

        Design: Difficulty/dual_variant_calc/recognition_variant_switch_restates_september_settlement
        """
        context = calculated_september_statement
        ps_id, st_id = context["ps_id"], context["st_id"]
        net_before = context["statement"]["net_payable_cents"]
        assert net_before == 73919

        fixtures.dispute_statement(api, ps_id, st_id, "Milestone basis contractually applies.")
        restated = fixtures.resolve_statement(
            api,
            st_id,
            recognition_method_override="MILESTONE_CHRONOLOGICAL",
            adjustment_note="Restated on the milestone basis for the September period.",
        )

        assert restated["marketing_recoupment_cents"] == 16171
        assert restated["subtotal_cents"] == 91642
        assert restated["holdback_cents"] == 4582
        assert restated["net_payable_cents"] == 87060
        assert restated["adjustment_delta_cents"] == 87060 - net_before == 13141
