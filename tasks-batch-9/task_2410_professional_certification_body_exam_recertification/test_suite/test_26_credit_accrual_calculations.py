"""Awards are stamped once, but only counted children accrue, and caps fill in order."""

import pytest

from test_helpers import assertions as ax
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_success
from test_helpers.test_users import ELIGIBILITY_REVIEWER_3_ID, make_eligibility_reviewer_headers

REVIEWER = make_eligibility_reviewer_headers(ELIGIBILITY_REVIEWER_3_ID)


def _review(api, activity_id, outcome, review_note):
    return validate_success(api.review_ceu_activity(
        activity_id, f.review_ceu_payload(outcome, review_note=review_note), REVIEWER), 200)


def _three_unreviewed_claims(api):
    """A holder with three submitted claims worth 6, 12 and 12 credits."""
    state = fx.pipeline_through_certificant(api)
    hours = [(6.0, "2026-09-15T00:00:00Z"), (12.0, "2026-10-15T00:00:00Z"),
             (12.0, "2026-11-15T00:00:00Z")]
    activities = [fx.claim_ceu(api, state, contact_hours=contact_hours,
                              activity_date=activity_date)
                  for contact_hours, activity_date in hours]
    return state, activities


def _four_claims_across_categories(api):
    """Eleven contact hours spread over four differently weighted categories."""
    state = fx.pipeline_through_certificant(api)
    claims = [
        ("PUBLICATION", "Journal of Practice", 3.5, "2026-09-01T00:00:00Z"),
        ("VOLUNTEER", "Chapter Outreach", 4.0, "2026-09-02T00:00:00Z"),
        ("LIVE_INSTRUCTION", "State Chapter Seminar", 2.0, "2026-09-03T00:00:00Z"),
        ("PRESENTING", "Annual Conference", 1.5, "2026-09-04T00:00:00Z"),
    ]
    activities = [fx.claim_ceu(api, state, category=category, provider=provider,
                               contact_hours=contact_hours, activity_date=activity_date)
                  for category, provider, contact_hours, activity_date in claims]
    return state, activities


def _three_self_study_claims(api):
    """Thirty, thirty and ten self-study hours, claimed strictly in that order."""
    state = fx.pipeline_through_certificant(api)
    hours = [(30.0, "2026-09-01T00:00:00Z"), (30.0, "2026-09-02T00:00:00Z"),
             (10.0, "2026-09-03T00:00:00Z")]
    activities = [fx.claim_ceu(api, state, category="SELF_STUDY",
                               provider="Online Modules Ltd", contact_hours=contact_hours,
                               activity_date=activity_date)
                  for contact_hours, activity_date in hours]
    return state, activities


class TestAccrualInputSet:
    """Only rows whose ``counted`` is true reach the cycle's total."""

    def test_an_approval_counts_its_award_and_a_rejection_leaves_the_total_alone(self, api):
        """Approving the six-credit claim moves the cycle to exactly 6.00, and rejecting
        the twelve-credit claim keeps its award on the row while contributing nothing.

        PRD §3.11: "First, gather the eligible set: every activity under the cycle whose
        `counted` is true and whose `activity_date` falls inside the window."

        PRD §3.11: "A `REJECT` also requires `SUBMITTED`, moves the activity `SUBMITTED →
        REJECTED`, which is terminal, and leaves `counted` false with `credits_counted` at
        0."

        Design: Corner/calculations/ceu_accrual_counts_only_approved_activities_and_ignores_rejected_and_unreviewed_ones
        """
        state, activities = _three_unreviewed_claims(api)

        approved = _review(api, activities[0]["id"], "APPROVE", "certificate on file")
        assert approved["status"] == "APPROVED"
        assert approved["counted"] is True
        assert float(approved["credits_counted"]) == pytest.approx(6.00, abs=0.01)
        after_approval = fx.read_cycle(api, state.cycle_id)
        assert float(after_approval["credits_applied"]) == pytest.approx(6.00, abs=0.01)
        assert after_approval["status"] == "OPEN"

        rejected = _review(api, activities[1]["id"], "REJECT", "provider not accredited")
        assert rejected["status"] == "REJECTED"
        assert rejected["counted"] is False
        assert float(rejected["credits_counted"]) == pytest.approx(0.00, abs=0.01)
        assert float(rejected["credits_awarded"]) == pytest.approx(12.00, abs=0.01)
        assert float(fx.read_cycle(api, state.cycle_id)["credits_applied"]) == pytest.approx(
            6.00, abs=0.01)

    def test_an_unreviewed_claim_never_enters_the_input_set(self, api):
        """The third claim keeps its award and is ignored, so the twelve-credit
        requirement stays unmet: summing awards would have read 30.00 and satisfied it.

        PRD §3.11: "In summary, `counted` is true exactly when an activity's `status` is
        `APPROVED` or `VERIFIED` **and** its `activity_date` falls inside the cycle's
        accrual window; `SUBMITTED`, `REJECTED`, `AUDIT_SELECTED`, and `REVOKED` activities
        never count."

        PRD §3.11: "A `CEU`-path cycle is `SATISFIED` exactly when its `credits_applied` is
        greater than or equal to its `required_credits`, with exact equality satisfying; a
        `RE_EXAM`-path cycle is `SATISFIED` exactly when its `reexam_registration_id` is
        set."

        Design: Corner/calculations/ceu_accrual_counts_only_approved_activities_and_ignores_rejected_and_unreviewed_ones
        """
        state, activities = _three_unreviewed_claims(api)
        _review(api, activities[0]["id"], "APPROVE", "certificate on file")
        _review(api, activities[1]["id"], "REJECT", "provider not accredited")

        untouched = fx.read_activity(api, activities[2]["id"])
        assert untouched["status"] == "SUBMITTED"
        assert untouched["counted"] is False
        assert float(untouched["credits_counted"]) == pytest.approx(0.00, abs=0.01)
        assert float(untouched["credits_awarded"]) == pytest.approx(12.00, abs=0.01)

        cycle = fx.read_cycle(api, state.cycle_id)
        assert cycle["status"] == "OPEN"
        assert float(cycle["credits_applied"]) == pytest.approx(6.00, abs=0.01)
        ax.assert_credits_applied_matches_counted_children(
            cycle, fx.read_activities_of(api, state.cycle_id))
        certificant = fx.read_certificant(api, state.certificant_id)
        assert float(certificant["ceu_credits_applied"]) == pytest.approx(6.00, abs=0.01)
        assert certificant["status"] == "ACTIVE"


class TestCategoryMultipliers:
    """Each category carries its own weight, and hours are never credits."""

    def test_each_award_is_the_hours_times_its_own_category_multiplier(self, api):
        """The four claims are weighted five, a quarter, one and two, so their awards are
        stamped at 17.50, 1.00, 2.00 and 3.00 before any reviewer looks at them.

        PRD §3.11: "Its `credits_awarded` is recorded immediately as the `contact_hours`
        multiplied by the category's credit multiplier, rounded half up to two decimals — a
        figure recorded but not yet counted toward anything."

        PRD §3.11: "The multipliers reflect the effort each activity type represents: an
        hour of `LIVE_INSTRUCTION` is worth 1.0 credits, an hour of `SELF_STUDY` is worth
        0.5, an hour spent `PRESENTING` is worth 2.0, an hour spent on `PUBLICATION` is
        worth 5.0, and an hour of `VOLUNTEER` service is worth 0.25."

        Design: Corner/calculations/ceu_category_multipliers_come_from_the_constants_block_not_from_raw_contact_hours
        """
        _state, activities = _four_claims_across_categories(api)

        awards = [float(activity["credits_awarded"]) for activity in activities]
        assert awards[0] == pytest.approx(17.50, abs=0.01)
        assert awards[1] == pytest.approx(1.00, abs=0.01)
        assert awards[2] == pytest.approx(2.00, abs=0.01)
        assert awards[3] == pytest.approx(3.00, abs=0.01)
        for activity in activities:
            assert activity["counted"] is False
            ax.assert_ceu_activity(activity)

    def test_the_approvals_accumulate_to_twenty_three_and_a_half_credits(self, api):
        """Approving them one at a time walks the cycle 17.50, 18.50, 20.50, 23.50 — never
        the 11.00 that summing contact hours would give.

        PRD §3.11: "Second, compute each eligible activity's award as its `contact_hours`
        multiplied by its category multiplier, **rounded half up to two decimals at this
        point** — rounding precedes capping, and this is the same figure held in
        `credits_awarded`."

        PRD §3.11: "Fourth, the cycle's `credits_applied` becomes the sum of
        `credits_counted` across the eligible set plus the carry-in contribution, rounded
        half up to two decimals."

        Design: Corner/calculations/ceu_category_multipliers_come_from_the_constants_block_not_from_raw_contact_hours
        """
        state, activities = _four_claims_across_categories(api)
        expected_counted = [17.50, 1.00, 2.00, 3.00]
        expected_running = [17.50, 18.50, 20.50, 23.50]

        for activity, counted, running in zip(activities, expected_counted, expected_running):
            reviewed = _review(api, activity["id"], "APPROVE", "documentation sighted")
            assert float(reviewed["credits_counted"]) == pytest.approx(counted, abs=0.01)
            assert float(fx.read_cycle(api, state.cycle_id)["credits_applied"]) == (
                pytest.approx(running, abs=0.01))

        cycle = fx.read_cycle(api, state.cycle_id)
        assert float(cycle["credits_applied"]) == pytest.approx(23.50, abs=0.01)
        assert cycle["status"] == "SATISFIED"
        assert float(cycle["carryover_credits_out"]) == pytest.approx(0.00, abs=0.01)
        ax.assert_credit_precision(cycle["credits_applied"])


class TestSelfStudyCapWaterfall:
    """The twenty-credit cap is consumed in creation order, not shared out."""

    def test_the_cap_is_filled_first_come_and_truncates_the_later_claims(self, api):
        """The first claim takes fifteen of the twenty, the second is cut to the five that
        remain, and the third receives nothing at all — no row reads a pro-rata share.

        PRD §3.11: "Third, fill the capped categories in chronological order: process the
        eligible activities sorted by `created_at` ascending, breaking ties by
        `activity_date` ascending and then by `contact_hours` ascending; for an activity in
        a capped category, its `credits_counted` is the lesser of its award and the
        category's remaining cap headroom, and the headroom is then reduced by that amount;
        for an activity in an uncapped category, its `credits_counted` is simply its award."

        PRD §3.11: "`SELF_STUDY` contributes at most 20.0 credits per cycle and `VOLUNTEER`
        at most 5.0."

        Design: Corner/calculations/self_study_cap_fills_in_creation_order_and_truncates_the_later_activities_to_zero
        """
        _state, activities = _three_self_study_claims(api)
        awards = [float(activity["credits_awarded"]) for activity in activities]
        assert awards == pytest.approx([15.00, 15.00, 5.00], abs=0.01)

        counted = [float(_review(api, activity["id"], "APPROVE", "modules completed")
                         ["credits_counted"])
                   for activity in activities]

        assert counted[0] == pytest.approx(15.00, abs=0.01)
        assert counted[1] == pytest.approx(5.00, abs=0.01)
        assert counted[2] == pytest.approx(0.00, abs=0.01)
        assert counted[1] != pytest.approx(8.57, abs=0.01)
        assert counted[2] != pytest.approx(2.86, abs=0.01)

    def test_a_fully_truncated_claim_stays_approved_and_the_total_stops_at_twenty(self, api):
        """Receiving zero credit is not a rejection: the third claim is still APPROVED and
        counted, and the cycle rests at exactly the cap.

        PRD §3.11: "Because the fill is chronological, the activity created first takes the
        headroom and later ones are truncated to whatever remains, which means a late
        `SELF_STUDY` claim can legitimately receive 0.00."

        PRD §3.11: "the invariant behind it holds at every observable moment:
        `credits_applied` always equals the rounded sum of the counted children's
        `credits_counted` plus the cycle's carry-in contribution."

        Design: Corner/calculations/self_study_cap_fills_in_creation_order_and_truncates_the_later_activities_to_zero
        """
        state, activities = _three_self_study_claims(api)
        for activity in activities:
            _review(api, activity["id"], "APPROVE", "modules completed")

        truncated = fx.read_activity(api, activities[2]["id"])
        assert truncated["status"] == "APPROVED"
        assert truncated["counted"] is True
        assert float(truncated["credits_counted"]) == pytest.approx(0.00, abs=0.01)

        cycle = fx.read_cycle(api, state.cycle_id)
        assert float(cycle["credits_applied"]) == pytest.approx(20.00, abs=0.01)
        ax.assert_credits_applied_matches_counted_children(
            cycle, fx.read_activities_of(api, state.cycle_id))
        assert float(fx.read_certificant(api, state.certificant_id)["ceu_credits_applied"]) == (
            pytest.approx(20.00, abs=0.01))
