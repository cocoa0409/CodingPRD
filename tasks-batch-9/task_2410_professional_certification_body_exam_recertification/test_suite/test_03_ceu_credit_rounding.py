"""Credit accrual rounds each award before the cycle total is summed."""

import pytest

from test_helpers import assertions as ax
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_success
from test_helpers.test_users import (
    ELIGIBILITY_REVIEWER_3_ID,
    make_eligibility_reviewer_headers,
)

REVIEWER = make_eligibility_reviewer_headers(ELIGIBILITY_REVIEWER_3_ID)

STRICT_PROGRAM = {"ceu_credit_accrual_basis": "STRICT_CYCLE"}

# 3.05 hours of self study is worth 1.525 credits before rounding.
SELF_STUDY_CLAIMS = [
    {"activity_date": "2026-09-01T00:00:00Z", "category": "SELF_STUDY",
     "provider": "Reading Module 1", "contact_hours": 3.05},
    {"activity_date": "2026-09-02T00:00:00Z", "category": "SELF_STUDY",
     "provider": "Reading Module 2", "contact_hours": 3.05},
    {"activity_date": "2026-09-03T00:00:00Z", "category": "SELF_STUDY",
     "provider": "Reading Module 3", "contact_hours": 3.05},
]


def _claim_all(api, state):
    return [validate_success(api.claim_ceu_activity(
        state.cycle_id, f.claim_ceu_payload(**claim), state.owner_headers), 201)
        for claim in SELF_STUDY_CLAIMS]


class TestSelfStudyAwardRounding:
    """Three identical half-credit-per-hour claims of 3.05 hours each."""

    def test_each_award_is_rounded_half_up_to_two_decimals_on_its_own(self, api):
        """1.525 credits per activity is recorded as 1.53, per activity, at claim
        time — not carried unrounded to be totalled later.

        PRD §3.11: "an hour of `SELF_STUDY` is worth 0.5".

        PRD §3.11: "Its `credits_awarded` is recorded immediately as the
        `contact_hours` multiplied by the category's credit multiplier, rounded
        half up to two decimals".

        Design: Difficulty/combinatorial_formula/ceu_self_study_award_rounded_per_activity_before_capping_totals_4_59
        """
        state = fx.pipeline_through_certificant(api, program_overrides=STRICT_PROGRAM)

        activities = _claim_all(api, state)

        for activity in activities:
            assert float(activity["credits_awarded"]) == pytest.approx(1.53, abs=0.001)
            assert activity["counted"] is False
            assert float(activity["credits_counted"]) == pytest.approx(0.00, abs=0.001)

    def test_approved_awards_count_at_their_rounded_value_within_the_self_study_cap(self, api):
        """Approval makes each activity count, and with 20.0 credits of headroom
        the cap never truncates, so each counts at exactly its rounded award.

        PRD §3.11: "for an activity in a capped category, its `credits_counted` is
        the lesser of its award and the category's remaining cap headroom, and the
        headroom is then reduced by that amount".

        PRD §3.11: "`SELF_STUDY` contributes at most 20.0 credits per cycle and
        `VOLUNTEER` at most 5.0."

        Design: Difficulty/combinatorial_formula/ceu_self_study_award_rounded_per_activity_before_capping_totals_4_59
        """
        state = fx.pipeline_through_certificant(api, program_overrides=STRICT_PROGRAM)
        activities = _claim_all(api, state)

        for activity in activities:
            reviewed = validate_success(api.review_ceu_activity(
                activity["id"], f.review_ceu_payload("APPROVE"), REVIEWER), 200)
            assert reviewed["status"] == "APPROVED"
            assert reviewed["counted"] is True
            assert float(reviewed["credits_counted"]) == pytest.approx(1.53, abs=0.001)

    def test_cycle_total_is_the_sum_of_rounded_awards_and_not_the_rounded_sum(self, api):
        """Three awards of 1.53 total 4.59; summing the raw products first would
        have produced 4.575 and therefore 4.58.

        PRD §3.11: "the cycle's `credits_applied` becomes the sum of
        `credits_counted` across the eligible set plus the carry-in contribution,
        rounded half up to two decimals".

        PRD §3.11: "The two rounding points are distinct and both are required:
        rounding each award before capping and then rounding the sum is the
        specified behaviour, whereas summing unrounded awards and rounding once at
        the end is wrong."

        Design: Difficulty/combinatorial_formula/ceu_self_study_award_rounded_per_activity_before_capping_totals_4_59
        """
        state = fx.pipeline_through_certificant(api, program_overrides=STRICT_PROGRAM)
        activities = _claim_all(api, state)
        for activity in activities:
            validate_success(api.review_ceu_activity(
                activity["id"], f.review_ceu_payload("APPROVE"), REVIEWER), 200)

        cycle = fx.read_cycle(api, state.cycle_id)

        assert float(cycle["credits_applied"]) == pytest.approx(4.59, abs=0.001)
        assert float(cycle["credits_applied"]) != pytest.approx(4.58, abs=0.001)
        assert cycle["status"] == "OPEN"
        certificant = fx.read_certificant(api, state.certificant_id)
        assert float(certificant["ceu_credits_applied"]) == pytest.approx(4.59, abs=0.001)

    def test_credits_applied_always_agrees_with_the_counted_children(self, api):
        """The accrual invariant holds while the cycle is only partly approved as
        well as when every claim has been approved.

        PRD §3.11: "`credits_applied` always equals the rounded sum of the counted
        children's `credits_counted` plus the cycle's carry-in contribution."

        Design: Difficulty/combinatorial_formula/ceu_self_study_award_rounded_per_activity_before_capping_totals_4_59
        """
        state = fx.pipeline_through_certificant(api, program_overrides=STRICT_PROGRAM)
        activities = _claim_all(api, state)

        for activity in activities:
            validate_success(api.review_ceu_activity(
                activity["id"], f.review_ceu_payload("APPROVE"), REVIEWER), 200)
            cycle = fx.read_cycle(api, state.cycle_id)
            children = fx.read_activities_of(api, state.cycle_id)
            ax.assert_credits_applied_matches_counted_children(cycle, children)
