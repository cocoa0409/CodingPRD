"""The evaluation's two independent dimensions, and the bounded notice/reschedule cycle."""
import pytest

from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    AssessmentStatus,
    BreachStatus,
    CaseloadStatus,
    ComplianceStatus,
    MeetingStatus,
    ReportReviewDecision,
    api_client,
    assert_eligibility_meeting,
    assert_evaluation,
    fixtures,
    reschedule_payload,
)
from test_helpers.test_users import TEST_USERS

INDEX = dict(abs=1e-9)


def _drafted_case_driven_into_breach():
    """A REPORT_DRAFTED evaluation whose clock has already blown, plus a peer reviewer."""
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Lakeside Elementary",
        building_code="LS04",
        grade_band="ELEMENTARY",
        concurrent_meeting_capacity=1,
        enrollment_count=390,
    )
    author = fixtures.create_psychologist(
        [school["id"]],
        full_name="Elle Marsh",
        employee_number="E-1005",
        credential_type="SSP",
        languages_certified=["en"],
        weekly_capacity_points=20,
    )
    reviewer = fixtures.create_psychologist(
        [school["id"]],
        full_name="Raj Patel",
        employee_number="E-1006",
        credential_type="PHD",
        languages_certified=["en"],
        weekly_capacity_points=20,
    )
    instrument = fixtures.create_instrument(
        name="KTEA-3",
        instrument_code="KTEA3",
        protocol_stock_count=10,
        protocol_units_per_administration=1,
        protocol_unit_cost_cents=1000,
        license_seat_total=2,
        license_expires_on="2027-06-30",
        supported_language_editions=["en"],
    )
    fixtures.assign_license_seat(instrument["id"], author["id"])

    _, evaluation = fixtures.consented_referral(
        school["id"],
        student_local_id="STU-F",
        requested_domains=["ACADEMIC"],
        intervention_team_summary="tier 3 fluency",
    )
    fixtures.assign_evaluator(evaluation["id"], author["id"])
    fixtures.start_testing(evaluation["id"], instrument["id"], author["id"])
    fixtures.record_scores(
        evaluation["id"], author["id"], "KTEA-3 composite 78, fluency 71"
    )
    fixtures.submit_report_draft(
        evaluation["id"],
        author["id"],
        "Draft: specific learning disability in reading fluency suspected.",
    )

    fixtures.set_clock("2026-10-08T00:00:00Z")
    fixtures.run_sweep()
    return {
        "school": school,
        "author": author,
        "reviewer": reviewer,
        "instrument": instrument,
        "evaluation": fixtures.get_evaluation(evaluation["id"]),
        "breach": fixtures.first_breach(evaluation["id"]),
    }


def _meeting_taken_twice_around_the_notice_loop():
    """A meeting that has used both of its reschedules and is noticed again."""
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Riverbend Middle",
        building_code="RB05",
        grade_band="MIDDLE",
        concurrent_meeting_capacity=1,
        enrollment_count=700,
    )
    _, evaluation = fixtures.consented_referral(
        school["id"],
        student_local_id="STU-G",
        requested_domains=["ADAPTIVE"],
        intervention_team_summary="tier 3 adaptive",
    )
    meeting = fixtures.create_meeting(
        evaluation["id"],
        school["id"],
        "2026-09-20T15:00:00Z",
        "2026-09-20T16:00:00Z",
    )
    first_notice = fixtures.send_notice(meeting["id"])

    fixtures.reschedule_meeting(
        meeting["id"], "2026-09-25T15:00:00Z", "2026-09-25T16:00:00Z"
    )
    second_notice = fixtures.send_notice(meeting["id"])

    fixtures.reschedule_meeting(
        meeting["id"], "2026-09-28T15:00:00Z", "2026-09-28T16:00:00Z"
    )
    third_notice = fixtures.send_notice(meeting["id"])
    return school, evaluation, [first_notice, second_notice, third_notice]


def test_finalising_the_report_leaves_the_compliance_dimension_breached():
    """One row holds REPORT_FINAL and BREACHED at the same time.

    "Note carefully that finalizing the report does **not** touch the evaluation's `compliance_status`: an evaluation may reach `REPORT_FINAL` while still `BREACHED`, and closing the compliance dimension is the job of the meeting hold or the remedy approval."

    Design: Difficulty/non_linear_state_machine/evaluation_parallel_dimensions_report_final_while_breached
    """
    context = _drafted_case_driven_into_breach()

    before = context["evaluation"]
    assert before["assessment_status"] == AssessmentStatus.REPORT_DRAFTED.value
    assert before["compliance_status"] == ComplianceStatus.BREACHED.value

    finalised = fixtures.review_report(
        before["id"],
        ReportReviewDecision.APPROVE.value,
        reviewer_psychologist_id=context["reviewer"]["id"],
    )

    assert_evaluation(finalised)
    assert finalised["assessment_status"] == AssessmentStatus.REPORT_FINAL.value
    assert finalised["compliance_status"] == ComplianceStatus.BREACHED.value
    assert finalised["days_remaining"] == -8


def test_the_breach_record_is_untouched_by_the_assessment_transition():
    """The breach the sweep opened keeps its status and its frozen day count.

    "`breach_days` is frozen at detection and is never recomputed by later clock movement, however far the clock subsequently runs."

    Design: Difficulty/non_linear_state_machine/evaluation_parallel_dimensions_report_final_while_breached
    """
    context = _drafted_case_driven_into_breach()

    fixtures.review_report(
        context["evaluation"]["id"],
        ReportReviewDecision.APPROVE.value,
        reviewer_psychologist_id=context["reviewer"]["id"],
    )

    breach = {
        row["id"]: row
        for row in fixtures.evaluation_breaches(context["evaluation"]["id"])
    }[context["breach"]["id"]]
    assert breach["status"] == BreachStatus.DETECTED.value
    assert breach["breach_days"] == 8


def test_finalising_the_report_empties_the_author_s_caseload_figures():
    """The assessment dimension alone drives the case out of the open window.

    "That transition cascades: because `REPORT_FINAL` is outside the four open statuses, the assigned psychologist's `open_case_points` is re-derived and drops by exactly this evaluation's `caseload_points`, and from that new total the psychologist's `caseload_status`, `pressure_index_assigned_basis` and `pressure_index_clock_weighted` are all re-derived in turn."

    Design: Difficulty/non_linear_state_machine/evaluation_parallel_dimensions_report_final_while_breached
    """
    context = _drafted_case_driven_into_breach()

    before_author = fixtures.get_psychologist(context["author"]["id"])
    assert before_author["open_case_points"] == 5
    assert before_author["pressure_index_clock_weighted"] == pytest.approx(0.50, **INDEX)

    fixtures.review_report(
        context["evaluation"]["id"],
        ReportReviewDecision.APPROVE.value,
        reviewer_psychologist_id=context["reviewer"]["id"],
    )

    after_author = fixtures.get_psychologist(context["author"]["id"])
    assert after_author["open_case_points"] == 0
    assert after_author["caseload_status"] == CaseloadStatus.BALANCED.value
    assert after_author["pressure_index_assigned_basis"] == pytest.approx(0.0, **INDEX)
    assert after_author["pressure_index_clock_weighted"] == pytest.approx(0.0, **INDEX)


def test_the_consumed_protocols_stay_consumed_across_the_finalisation():
    """One booklet was burned at testing-start and none comes back.

    "On success the same product is written to the evaluation's `protocol_units_consumed` and debited from the instrument's `protocol_stock_count`."

    Design: Difficulty/non_linear_state_machine/evaluation_parallel_dimensions_report_final_while_breached
    """
    context = _drafted_case_driven_into_breach()

    finalised = fixtures.review_report(
        context["evaluation"]["id"],
        ReportReviewDecision.APPROVE.value,
        reviewer_psychologist_id=context["reviewer"]["id"],
    )

    assert finalised["protocol_units_consumed"] == 1
    instrument = fixtures.get_instrument(context["instrument"]["id"])
    assert instrument["protocol_stock_count"] == 9


def test_the_notice_loop_can_be_re_entered_and_re_stamps_the_lead():
    """Three notices on one row, each measured against its own new date.

    "Re-issuing a notice after a reschedule overwrites both fields for the new date."

    Design: Difficulty/non_linear_state_machine/eligibility_meeting_notice_reschedule_cycle_bounded
    """
    _, _, notices = _meeting_taken_twice_around_the_notice_loop()

    first, second, third = notices
    assert [notice["status"] for notice in notices] == [
        MeetingStatus.NOTICED.value
    ] * 3
    assert first["notice_lead_days"] == 50
    assert second["notice_lead_days"] == 55
    assert third["notice_lead_days"] == 58

    assert_eligibility_meeting(third)
    assert third["scheduled_start_at"].startswith("2026-09-28")
    assert third["reschedule_count"] == 2


def test_a_reschedule_request_clears_the_previous_notice_each_time_round():
    """Every trip through the loop voids the notice it started from.

    "A successful reschedule overwrites the interval, increments `reschedule_count` by one, and clears both `parent_notice_sent_at` and `notice_lead_days`, because a fresh notice for the new date is mandatory — the cycle `NOTICED → RESCHEDULE_REQUESTED → NOTICED` is legitimate and bounded only by that ceiling of two."

    Design: Difficulty/non_linear_state_machine/eligibility_meeting_notice_reschedule_cycle_bounded
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Riverbend Annex",
        building_code="RB06",
        grade_band="MIDDLE",
        concurrent_meeting_capacity=1,
        enrollment_count=700,
    )
    _, evaluation = fixtures.consented_referral(
        school["id"], student_local_id="STU-G2", requested_domains=["ADAPTIVE"]
    )
    meeting = fixtures.create_meeting(
        evaluation["id"], school["id"], "2026-09-20T15:00:00Z", "2026-09-20T16:00:00Z"
    )
    noticed = fixtures.send_notice(meeting["id"])
    assert noticed["notice_lead_days"] == 50
    assert noticed["parent_notice_sent_at"] is not None

    requested = fixtures.reschedule_meeting(
        meeting["id"], "2026-09-25T15:00:00Z", "2026-09-25T16:00:00Z"
    )

    assert requested["status"] == MeetingStatus.RESCHEDULE_REQUESTED.value
    assert requested["reschedule_count"] == 1
    assert requested["parent_notice_sent_at"] is None
    assert requested["notice_lead_days"] is None
    assert requested["scheduled_start_at"].startswith("2026-09-25")


def test_the_third_reschedule_is_refused_by_the_ceiling():
    """Two reschedules are the whole allowance, and the third is rejected.

    "Rescheduling is bounded: a meeting may accept at most two reschedules, so the request is accepted only while `reschedule_count` is strictly below two and is rejected with `ERR_RESCHEDULE_LIMIT_REACHED` once it has reached two."

    Design: Difficulty/non_linear_state_machine/eligibility_meeting_notice_reschedule_cycle_bounded
    """
    _, _, notices = _meeting_taken_twice_around_the_notice_loop()
    meeting_id = notices[-1]["id"]

    response = api_client.request_meeting_reschedule(
        meeting_id,
        reschedule_payload("2026-10-02T15:00:00Z", "2026-10-02T16:00:00Z"),
        TEST_USERS["intake_coordinator_headers"],
    )

    validate_error(response, ApiErrorId.ERR_RESCHEDULE_LIMIT_REACHED.value, 409)

    unchanged = fixtures.get_meeting(meeting_id)
    assert unchanged["status"] == MeetingStatus.NOTICED.value
    assert unchanged["reschedule_count"] == 2
    assert unchanged["scheduled_start_at"].startswith("2026-09-28")
    assert unchanged["notice_lead_days"] == 58
