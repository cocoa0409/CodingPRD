"""Writes that are legal on their own row and refused because a related record moved."""
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    AssessmentStatus,
    ComplianceStatus,
    ConsentEventType,
    MeetingStatus,
    ReferralStatus,
    api_client,
    fixtures,
    make_school_psychologist_headers,
    timeline_exclusion_payload,
)
from test_helpers.test_users import TEST_USERS


def _assigned_case_whose_consent_was_withdrawn():
    """An owned evaluation cancelled by withdrawal, with its evaluator retained."""
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Ashfield Elementary",
        building_code="AF13",
        grade_band="ELEMENTARY",
        concurrent_meeting_capacity=2,
        enrollment_count=340,
    )
    psychologist = fixtures.create_psychologist(
        [school["id"]],
        full_name="Lena Ford",
        employee_number="E-1013",
        credential_type="SSP",
        languages_certified=["en"],
        weekly_capacity_points=20,
    )
    referral, evaluation = fixtures.consented_referral(
        school["id"],
        student_local_id="STU-O",
        requested_domains=["COGNITIVE"],
        intervention_team_summary="tier 3 cognition",
    )
    fixtures.assign_evaluator(evaluation["id"], psychologist["id"])
    referral = fixtures.withdraw_consent(referral["id"])
    return school, psychologist, referral, fixtures.get_evaluation(evaluation["id"])


def _due_noticed_meeting_on_a_case_with_no_final_report():
    """A meeting that is noticed and due, on an evaluation still merely ASSIGNED."""
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Glenwood Middle",
        building_code="GW14",
        grade_band="MIDDLE",
        concurrent_meeting_capacity=2,
        enrollment_count=560,
    )
    psychologist = fixtures.create_psychologist(
        [school["id"]],
        full_name="Milo Grant",
        employee_number="E-1014",
        credential_type="SSP",
        languages_certified=["en"],
        weekly_capacity_points=20,
    )
    referral, evaluation = fixtures.consented_referral(
        school["id"],
        student_local_id="STU-P",
        requested_domains=["ACADEMIC"],
        intervention_team_summary="tier 3 writing",
    )
    fixtures.assign_evaluator(evaluation["id"], psychologist["id"])
    meeting = fixtures.create_meeting(
        evaluation["id"],
        school["id"],
        "2026-09-20T15:00:00Z",
        "2026-09-20T16:00:00Z",
    )
    fixtures.set_clock("2026-09-10T00:00:00Z")
    meeting = fixtures.send_notice(meeting["id"])
    fixtures.set_clock("2026-09-20T15:00:00Z")
    return school, psychologist, referral, evaluation, meeting


def test_the_owner_s_own_claim_is_refused_once_consent_is_withdrawn():
    """Ownership passes and the grandparent referral's consent state rejects the write.

    "The claiming psychologist must be the evaluation's `psychologist_id`, or the claim is rejected with `ERR_PSYCH_NOT_OWNER`, and the parent referral must hold consent, or it is rejected with `ERR_CONSENT_NOT_ON_FILE`."

    Design: Difficulty/cross_entity_state_dependency/exclusion_claim_blocked_by_referral_consent_state
    """
    _, psychologist, referral, evaluation = _assigned_case_whose_consent_was_withdrawn()

    assert referral["status"] == ReferralStatus.CONSENT_WITHDRAWN.value
    assert referral["last_consent_event_type"] == ConsentEventType.CONSENT_WITHDRAWN.value
    # The caller IS the evaluation's psychologist, so the ownership rung passes.
    assert evaluation["psychologist_id"] == psychologist["id"]

    response = api_client.claim_timeline_exclusion(
        timeline_exclusion_payload(
            evaluation["id"],
            "BREAK_CLOSURE",
            "2026-08-10",
            "2026-08-24",
            "District summer closure",
        ),
        make_school_psychologist_headers(psychologist["id"]),
    )

    validate_error(response, ApiErrorId.ERR_CONSENT_NOT_ON_FILE.value, 409)


def test_the_withdrawal_cascade_cancels_the_case_but_keeps_its_evaluator():
    """The cancelled evaluation still names the psychologist the claim came from.

    "The evaluation's `psychologist_id` is retained for audit, but because the case has left the open-caseload window the assigned psychologist's `open_case_points`, `caseload_status` and both pressure indices are re-derived."

    Design: Difficulty/cross_entity_state_dependency/exclusion_claim_blocked_by_referral_consent_state
    """
    _, psychologist, _, evaluation = _assigned_case_whose_consent_was_withdrawn()

    assert evaluation["assessment_status"] == AssessmentStatus.CANCELLED.value
    assert evaluation["compliance_status"] == ComplianceStatus.WAIVED.value
    assert evaluation["psychologist_id"] == psychologist["id"]
    assert fixtures.get_psychologist(psychologist["id"])["open_case_points"] == 0


def test_the_refused_claim_creates_no_exclusion_row():
    """No claim is persisted, so the evaluation's credit stays at zero.

    "A fresh claim opens in `CLAIMED` status, records `days_claimed` as the inclusive calendar-day count of its window — a window whose start and end dates are the same day counts as one day — and leaves `days_credited` at zero, `decided_by_user_id` null and `decided_at` null."

    Design: Difficulty/cross_entity_state_dependency/exclusion_claim_blocked_by_referral_consent_state
    """
    _, psychologist, _, evaluation = _assigned_case_whose_consent_was_withdrawn()

    api_client.claim_timeline_exclusion(
        timeline_exclusion_payload(
            evaluation["id"],
            "BREAK_CLOSURE",
            "2026-08-10",
            "2026-08-24",
            "District summer closure",
        ),
        make_school_psychologist_headers(psychologist["id"]),
    )

    assert fixtures.evaluation_exclusions(evaluation["id"]) == []
    assert fixtures.get_evaluation(evaluation["id"])["credited_exclusion_days"] == 0


def test_holding_a_due_noticed_meeting_needs_the_sibling_report_finalised():
    """The meeting's own state and due date are fine; the evaluation's is not.

    "The evaluation's `assessment_status` must be `REPORT_FINAL`, since a determination cannot be made without a finalized report; otherwise the attempt is rejected with `ERR_REPORT_NOT_FINAL`."

    Design: Difficulty/cross_entity_state_dependency/meeting_hold_blocked_by_evaluation_report_state
    """
    _, _, _, evaluation, meeting = _due_noticed_meeting_on_a_case_with_no_final_report()

    assert meeting["status"] == MeetingStatus.NOTICED.value
    assert meeting["notice_lead_days"] == 10
    assert (
        fixtures.get_evaluation(evaluation["id"])["assessment_status"]
        == AssessmentStatus.ASSIGNED.value
    )

    response = api_client.hold_meeting(
        meeting["id"], TEST_USERS["psych_services_supervisor_headers"]
    )

    validate_error(response, ApiErrorId.ERR_REPORT_NOT_FINAL.value, 409)


def test_the_refused_hold_fires_no_part_of_the_closure_cascade():
    """Neither the meeting, nor the evaluation's posture, nor the referral moves.

    "Either way the parent referral moves to the terminal `COMPLETED` status, since the determination has been made and no further consent event is meaningful."

    Design: Difficulty/cross_entity_state_dependency/meeting_hold_blocked_by_evaluation_report_state
    """
    (
        _,
        _,
        referral,
        evaluation,
        meeting,
    ) = _due_noticed_meeting_on_a_case_with_no_final_report()

    api_client.hold_meeting(
        meeting["id"], TEST_USERS["psych_services_supervisor_headers"]
    )

    unchanged_meeting = fixtures.get_meeting(meeting["id"])
    assert unchanged_meeting["status"] == MeetingStatus.NOTICED.value
    assert unchanged_meeting["held_at"] is None

    unchanged_evaluation = fixtures.get_evaluation(evaluation["id"])
    assert unchanged_evaluation["days_remaining"] == 10
    assert unchanged_evaluation["compliance_status"] == ComplianceStatus.ON_TRACK.value

    assert (
        fixtures.get_referral(referral["id"])["status"]
        == ReferralStatus.CONSENTED.value
    )
