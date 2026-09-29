"""The statutory parent-notice lead: ten days passes, nine days fails."""
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    MeetingStatus,
    api_client,
    assert_eligibility_meeting,
    fixtures,
    is_iso8601_timestamp,
)
from test_helpers.test_users import TEST_USERS


def _two_disjoint_meetings_at_one_building():
    """Two meetings on the same day at a capacity-one building, intervals apart.

    The closed intervals 15:00-16:00 and 17:00-18:00 do not intersect, so the
    hosting building's capacity rule never enters the picture.
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Fairmont High",
        building_code="FM11",
        grade_band="HIGH",
        concurrent_meeting_capacity=1,
        enrollment_count=1100,
    )
    _, first_evaluation = fixtures.consented_referral(
        school["id"],
        student_local_id="STU-L",
        requested_domains=["COGNITIVE"],
        intervention_team_summary="tier 3 cognition",
    )
    first_meeting = fixtures.create_meeting(
        first_evaluation["id"],
        school["id"],
        "2026-09-20T15:00:00Z",
        "2026-09-20T16:00:00Z",
    )
    _, second_evaluation = fixtures.consented_referral(
        school["id"],
        student_local_id="STU-M",
        requested_domains=["ACADEMIC"],
        intervention_team_summary="tier 3 reading",
    )
    second_meeting = fixtures.create_meeting(
        second_evaluation["id"],
        school["id"],
        "2026-09-20T17:00:00Z",
        "2026-09-20T18:00:00Z",
    )
    return school, first_meeting, second_meeting


def test_a_lead_of_exactly_ten_days_is_accepted():
    """Noticing on 10 September for a 20 September meeting clears the requirement.

    "The statutory lead requirement is ten calendar days: the number of calendar days from the current clock date to the calendar date of `scheduled_start_at` must be at least ten."

    Design: Difficulty/boundary_precision_check/parent_notice_lead_days_exact_ten_boundary
    """
    _, first_meeting, _ = _two_disjoint_meetings_at_one_building()
    fixtures.set_clock("2026-09-10T00:00:00Z")

    noticed = fixtures.send_notice(first_meeting["id"])

    assert_eligibility_meeting(noticed)
    assert noticed["status"] == MeetingStatus.NOTICED.value
    assert noticed["notice_lead_days"] == 10
    assert is_iso8601_timestamp(noticed["parent_notice_sent_at"])
    assert noticed["parent_notice_sent_at"].startswith("2026-09-10")


def test_a_lead_of_nine_days_is_refused():
    """One day later the same meeting date is one day short of the requirement.

    "Exactly ten days passes; nine days fails with `ERR_NOTICE_LEAD_INSUFFICIENT`."

    Design: Difficulty/boundary_precision_check/parent_notice_lead_days_exact_ten_boundary
    """
    _, first_meeting, second_meeting = _two_disjoint_meetings_at_one_building()
    fixtures.set_clock("2026-09-10T00:00:00Z")
    fixtures.send_notice(first_meeting["id"])
    fixtures.set_clock("2026-09-11T00:00:00Z")

    response = api_client.send_meeting_notice(
        second_meeting["id"], TEST_USERS["intake_coordinator_headers"]
    )

    validate_error(response, ApiErrorId.ERR_NOTICE_LEAD_INSUFFICIENT.value, 422)


def test_the_refused_notice_leaves_the_meeting_unnoticed():
    """A rejected notice stamps neither the instant nor the lead.

    "The meeting opens in `PROPOSED` status with `reschedule_count` at zero and `parent_notice_sent_at`, `notice_lead_days` and `held_at` all null."

    Design: Difficulty/boundary_precision_check/parent_notice_lead_days_exact_ten_boundary
    """
    _, _, second_meeting = _two_disjoint_meetings_at_one_building()
    fixtures.set_clock("2026-09-11T00:00:00Z")

    api_client.send_meeting_notice(
        second_meeting["id"], TEST_USERS["intake_coordinator_headers"]
    )

    unchanged = fixtures.get_meeting(second_meeting["id"])
    assert unchanged["status"] == MeetingStatus.PROPOSED.value
    assert unchanged["parent_notice_sent_at"] is None
    assert unchanged["notice_lead_days"] is None
    assert unchanged["held_at"] is None
