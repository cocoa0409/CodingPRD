"""The two deepest cascades: staffing leave removes work, exclusion credit restores compliance."""
import pytest

from test_helpers import (
    AssessmentStatus,
    BreachSeverity,
    BreachStatus,
    CancellationReason,
    CaseloadStatus,
    ComplianceStatus,
    ExclusionStatus,
    PsychologistStatus,
    RemedyBasis,
    SessionStatus,
    assert_evaluation,
    assert_psychologist,
    assert_timeline_breach,
    assert_timeline_exclusion,
    fixtures,
)

INDEX = dict(abs=1e-9)


def _staffed_case_with_a_booked_interpreter():
    """One nine-point interpreter case assigned to the only evaluator on file."""
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Cedar Park Elementary",
        building_code="CP06",
        grade_band="ELEMENTARY",
        concurrent_meeting_capacity=2,
        enrollment_count=520,
    )
    psychologist = fixtures.create_psychologist(
        [school["id"]],
        full_name="Fay Nolan",
        employee_number="E-1007",
        credential_type="SSP",
        languages_certified=["en"],
        weekly_capacity_points=20,
    )
    _, evaluation = fixtures.consented_referral(
        school["id"],
        student_local_id="STU-H",
        primary_language="es",
        interpreter_required=True,
        bilingual_evaluation_required=False,
        requested_domains=["COGNITIVE", "ACADEMIC", "ADAPTIVE"],
        intervention_team_summary="tier 3, newcomer",
    )
    evaluation = fixtures.assign_evaluator(evaluation["id"], psychologist["id"])
    session = fixtures.book_session(
        evaluation["id"],
        "2026-09-10T09:00:00Z",
        "2026-09-10T10:00:00Z",
        language_code="es",
        interpreter_name="M. Cruz",
    )
    return school, psychologist, evaluation, session


def _breached_case_with_a_proposed_remedy_and_a_pending_claim():
    """A five-point case one day past its due date, with a remedy on the table.

    A fifteen-day closure claim sits undecided, and approving it is the trigger
    the tests below exercise.
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Harbor View Middle",
        building_code="HV07",
        grade_band="MIDDLE",
        concurrent_meeting_capacity=2,
        enrollment_count=640,
    )
    psychologist = fixtures.create_psychologist(
        [school["id"]],
        full_name="Gil Amato",
        employee_number="E-1008",
        credential_type="SSP",
        languages_certified=["en"],
        weekly_capacity_points=20,
    )
    _, evaluation = fixtures.consented_referral(
        school["id"],
        student_local_id="STU-I",
        requested_domains=["SOCIAL_EMOTIONAL"],
        intervention_team_summary="tier 3 behaviour",
    )
    evaluation = fixtures.assign_evaluator(evaluation["id"], psychologist["id"])

    fixtures.set_clock("2026-10-01T00:00:00Z")
    fixtures.run_sweep()
    breach = fixtures.first_breach(evaluation["id"])
    breach = fixtures.propose_remedy(
        breach["id"],
        RemedyBasis.BREACH_DAY_BASIS.value,
        additional_minutes=0,
        corrective_action_note="One 30-minute make-up session",
    )
    claim = fixtures.claim_exclusion(
        evaluation["id"],
        psychologist["id"],
        "BREAK_CLOSURE",
        "2026-08-10",
        "2026-08-24",
        claim_note="District summer closure",
    )
    return school, psychologist, evaluation, breach, claim


def test_leave_unassigns_the_case_and_cancels_its_interpreter_support():
    """One HR event walks from the psychologist through the case to the session.

    "Second, every evaluation assigned to them whose `assessment_status` is `ASSIGNED`, `IN_TESTING`, `SCORED` or `REPORT_DRAFTED` is driven back to `PENDING_ASSIGNMENT`, with `psychologist_id` cleared and `reassignment_count` incremented by one; the evaluation's `version` increments as part of that write."

    Design: Difficulty/transitive_cascade/psychologist_leave_cascade_depth_four
    """
    _, psychologist, evaluation, session = _staffed_case_with_a_booked_interpreter()

    before_person = fixtures.get_psychologist(psychologist["id"])
    assert before_person["open_case_points"] == 9
    assert fixtures.get_evaluation(evaluation["id"])["caseload_points"] == 9

    on_leave = fixtures.place_on_leave(psychologist["id"])

    assert_psychologist(on_leave)
    assert on_leave["status"] == PsychologistStatus.ON_LEAVE.value

    unassigned = fixtures.get_evaluation(evaluation["id"])
    assert_evaluation(unassigned)
    assert unassigned["assessment_status"] == AssessmentStatus.PENDING_ASSIGNMENT.value
    assert unassigned["psychologist_id"] is None
    assert unassigned["reassignment_count"] == 1

    sessions = {row["id"]: row for row in fixtures.evaluation_sessions(evaluation["id"])}
    cancelled = sessions[session["id"]]
    assert cancelled["status"] == SessionStatus.CANCELLED.value
    assert (
        cancelled["cancellation_reason"]
        == CancellationReason.PSYCHOLOGIST_UNAVAILABLE.value
    )


def test_leave_empties_the_caseload_figures_of_the_departing_evaluator():
    """The fourth level drives all four caseload figures back to their floor.

    "Fourth, the caseload figures are re-derived for this psychologist, driving `open_case_points` to 0, `caseload_status` to `BALANCED` and both pressure indices to `0.00`."

    Design: Difficulty/transitive_cascade/psychologist_leave_cascade_depth_four
    """
    _, psychologist, _, _ = _staffed_case_with_a_booked_interpreter()

    before_person = fixtures.get_psychologist(psychologist["id"])
    assert before_person["pressure_index_assigned_basis"] == pytest.approx(
        0.45, **INDEX
    )
    assert before_person["pressure_index_clock_weighted"] == pytest.approx(0.45, **INDEX)

    fixtures.place_on_leave(psychologist["id"])

    after_person = fixtures.get_psychologist(psychologist["id"])
    assert after_person["open_case_points"] == 0
    assert after_person["caseload_status"] == CaseloadStatus.BALANCED.value
    assert after_person["pressure_index_assigned_basis"] == pytest.approx(0.0, **INDEX)
    assert after_person["pressure_index_clock_weighted"] == pytest.approx(0.0, **INDEX)


def test_leave_leaves_the_statutory_clock_exactly_where_it_was():
    """Removing the evaluator does not buy the district any calendar time.

    "`base_due_date` is `clock_start_date` advanced by 60 calendar days."

    Design: Difficulty/transitive_cascade/psychologist_leave_cascade_depth_four
    """
    _, psychologist, evaluation, _ = _staffed_case_with_a_booked_interpreter()

    fixtures.place_on_leave(psychologist["id"])

    after = fixtures.get_evaluation(evaluation["id"])
    assert after["clock_start_date"] == "2026-08-01"
    assert after["base_due_date"] == "2026-09-30"
    assert after["credited_exclusion_days"] == 0
    assert after["statutory_due_date"] == "2026-09-30"


def test_approving_the_closure_credits_days_and_moves_the_due_date():
    """The first two levels: the claim earns its ceiling and the clock is re-resolved.

    "Second, and caused by the first, the evaluation's `credited_exclusion_days`, `statutory_due_date`, `elapsed_statutory_days` and `days_remaining` are recomputed by the pinned seven-step resolution."

    Design: Difficulty/transitive_cascade/exclusion_approval_cascade_depth_five_vacates_remedy
    """
    (
        _,
        _,
        evaluation,
        _,
        claim,
    ) = _breached_case_with_a_proposed_remedy_and_a_pending_claim()

    before = fixtures.get_evaluation(evaluation["id"])
    assert before["compliance_status"] == ComplianceStatus.BREACHED.value
    assert before["days_remaining"] == -1

    approved = fixtures.decide_exclusion(claim["id"], "APPROVE")

    assert_timeline_exclusion(approved)
    assert approved["status"] == ExclusionStatus.APPROVED.value
    assert approved["days_claimed"] == 15
    assert approved["days_credited"] == 14

    after = fixtures.get_evaluation(evaluation["id"])
    assert_evaluation(after)
    assert after["credited_exclusion_days"] == 14
    assert after["statutory_due_date"] == "2026-10-14"
    assert after["elapsed_statutory_days"] == 47
    assert after["days_remaining"] == 13


def test_approving_the_closure_pulls_the_evaluation_back_out_of_breach():
    """Thirteen days remaining is past the ten-day at-risk window, so it is on track.

    "Third, and caused by the second, the evaluation's `compliance_status` is re-derived from the new `days_remaining`: an evaluation may move `BREACHED → AT_RISK` when the credit pulls it back to between zero and ten days remaining inclusive, or `BREACHED → ON_TRACK` when the credit pulls it back past ten days remaining, and equally `AT_RISK → ON_TRACK` when more than ten days remain after the credit."

    Design: Difficulty/transitive_cascade/exclusion_approval_cascade_depth_five_vacates_remedy
    """
    (
        _,
        _,
        evaluation,
        _,
        claim,
    ) = _breached_case_with_a_proposed_remedy_and_a_pending_claim()

    fixtures.decide_exclusion(claim["id"], "APPROVE")

    after = fixtures.get_evaluation(evaluation["id"])
    assert after["days_remaining"] == 13
    assert after["compliance_status"] == ComplianceStatus.ON_TRACK.value


def test_approving_the_closure_vacates_the_breach_and_discards_its_award():
    """The proposed thirty minutes are unwound while the frozen counts stay frozen.

    "Fourth, and caused by the evaluation leaving `BREACHED`, any timeline breach of that evaluation whose status is `DETECTED` or `REMEDY_PROPOSED` is vacated and its `remedy_minutes_awarded` is driven to zero — a breach that has been cured by a legitimate exclusion no longer counts against the district."

    Design: Difficulty/transitive_cascade/exclusion_approval_cascade_depth_five_vacates_remedy
    """
    (
        _,
        _,
        evaluation,
        breach,
        claim,
    ) = _breached_case_with_a_proposed_remedy_and_a_pending_claim()

    assert breach["status"] == BreachStatus.REMEDY_PROPOSED.value
    assert breach["breach_days"] == 1
    assert breach["severity"] == BreachSeverity.MINOR.value
    assert breach["remedy_minutes_awarded"] == 30

    fixtures.decide_exclusion(claim["id"], "APPROVE")

    vacated = {
        row["id"]: row for row in fixtures.evaluation_breaches(evaluation["id"])
    }[breach["id"]]
    assert_timeline_breach(vacated)
    assert vacated["status"] == BreachStatus.VACATED.value
    assert vacated["remedy_minutes_awarded"] == 0
    assert vacated["remedy_basis"] == RemedyBasis.BREACH_DAY_BASIS.value
    assert vacated["breach_days"] == 1


def test_approving_the_closure_lightens_the_clock_weighted_pressure_index():
    """The fifth level: the case stops weighing double once it is no longer breached.

    "On each of these levels the assigned psychologist's `pressure_index_assigned_basis` and `pressure_index_clock_weighted` are re-derived, because the urgency weight attached to this evaluation has changed."

    Design: Difficulty/transitive_cascade/exclusion_approval_cascade_depth_five_vacates_remedy
    """
    (
        _,
        psychologist,
        _,
        _,
        claim,
    ) = _breached_case_with_a_proposed_remedy_and_a_pending_claim()

    before_person = fixtures.get_psychologist(psychologist["id"])
    assert before_person["open_case_points"] == 5
    assert before_person["pressure_index_assigned_basis"] == pytest.approx(0.25, **INDEX)
    assert before_person["pressure_index_clock_weighted"] == pytest.approx(0.50, **INDEX)

    fixtures.decide_exclusion(claim["id"], "APPROVE")

    after_person = fixtures.get_psychologist(psychologist["id"])
    assert_psychologist(after_person)
    assert after_person["open_case_points"] == 5
    assert after_person["pressure_index_assigned_basis"] == pytest.approx(0.25, **INDEX)
    assert after_person["pressure_index_clock_weighted"] == pytest.approx(0.25, **INDEX)
