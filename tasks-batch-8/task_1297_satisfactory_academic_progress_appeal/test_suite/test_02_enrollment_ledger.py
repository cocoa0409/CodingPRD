"""The enrollment ledger: posting, amendment, and the re-evaluation cascade."""
import pytest

from test_helpers import (
    AID_OFFICER, REGISTRAR, amend_payload, api_client, close_and_evaluate,
    close_grading, create_enrollment, create_posted_enrollment, create_program,
    create_student, create_term, enrollment_payload, get_student,
    list_audit_events, list_notifications, official_evaluation, post_grades,
    post_grades_payload, setup_suspended_student, validate_error,
    validate_paginated, validate_success,
)


def test_enrollment_post_from_posted_rejected(api):
    """PRD section 3.2: "Grade posting moves an enrollment from `IN_PROGRESS` to
    `POSTED`, recording the final `earned_credits`, `quality_points`, and `gpa_hours`;
    posting from any other state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/enrollment_post_from_posted_rejected
    """
    program = create_program(code="BS-PP", name="PostPost", required_credits=120)
    term = create_term(1)
    student = create_student(program["id"], student_number="S-1001")
    enrollment = create_posted_enrollment(student["id"], term["id"], 12, 12, 48.0, 12)

    res = api.post_enrollment(
        enrollment["id"], post_grades_payload(0, 0.0, 12), REGISTRAR)
    validate_error(res, "ERR_INVALID_STATE")

    student_after = get_student(student["id"])
    assert student_after["cumulative_earned_credits"] == 12, (
        "a rejected second posting must not move the cumulative ledger")


def test_enrollment_amend_in_progress_rejected(api):
    """PRD section 3.2: "Amending from `IN_PROGRESS` is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/enrollment_amend_in_progress_rejected
    """
    program = create_program(code="BS-AI", name="AmendInProg", required_credits=120)
    term = create_term(1)
    student = create_student(program["id"], student_number="S-1002")
    enrollment = create_enrollment(student["id"], term["id"], 12)

    res = api.amend_enrollment(
        enrollment["id"], amend_payload(12, 48.0, 12, "too early"), REGISTRAR)
    validate_error(res, "ERR_INVALID_STATE")

    reread = validate_success(api.get_enrollment(enrollment["id"], AID_OFFICER), 200)
    assert reread["status"] == "IN_PROGRESS"


def test_enrollment_amend_self_loop_allowed(api):
    """PRD section 3.2: "When a grade is later corrected, amendment moves the
    enrollment from `POSTED` to `AMENDED` — or from `AMENDED` to `AMENDED` again, since
    repeat amendments are permitted and each appends its own audit row."

    Design: Corner/state_machines/enrollment_amend_self_loop_allowed
    """
    program = create_program(code="BS-AS", name="AmendSelf", required_credits=120)
    term = create_term(1)
    student = create_student(program["id"], student_number="S-1003")
    enrollment = create_posted_enrollment(student["id"], term["id"], 6, 3, 9.0, 6)
    first = validate_success(api.amend_enrollment(
        enrollment["id"], amend_payload(6, 24.0, 6, "first correction"), REGISTRAR), 200)
    assert first["status"] == "AMENDED"

    second = validate_success(api.amend_enrollment(
        enrollment["id"], amend_payload(6, 18.0, 6, "second correction"), REGISTRAR), 200)
    assert second["status"] == "AMENDED"
    assert second["amendment_count"] == 2

    student_after = get_student(student["id"])
    assert student_after["cumulative_quality_points"] == pytest.approx(18.0), (
        "the latest amendment's values win on the cumulative ledger")


def test_enrollment_create_on_closed_term_rejected(api):
    """PRD section 3.2: "Enrollment into a term that is no longer `OPEN` is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/enrollment_create_on_closed_term_rejected
    """
    program = create_program(code="BS-EC", name="EnrollClosed", required_credits=120)
    term = create_term(1)
    student = create_student(program["id"], student_number="S-8001")
    create_posted_enrollment(student["id"], term["id"], 12, 12, 48.0, 12)
    close_grading(term["id"])

    res = api.create_enrollment(
        enrollment_payload(student["id"], term["id"], 3), REGISTRAR)
    validate_error(res, "ERR_INVALID_STATE")

    rows, meta = validate_paginated(
        api.list_enrollments(AID_OFFICER, params={"term_id": term["id"]}))
    assert meta["total_count"] == 1, "the rejected create must not persist a row"


class TestAmendmentConservesEarnedCredits:
    """The earned-credit ledger is conserved across forward/compensating amends."""

    def _world(self, api):
        program = create_program(code="BS-STAT", name="Statistics", required_credits=120)
        term = create_term(1)
        student = create_student(program["id"], student_number="S-9501")
        create_posted_enrollment(student["id"], term["id"], 6, 6, 24.0, 6)
        e2 = create_posted_enrollment(student["id"], term["id"], 6, 3, 9.0, 6)
        return student, e2

    def test_amendment_reverses_and_reapplies_earned_credits(self, api):
        """PRD section 3.2: "The amendment fully reverses the enrollment's prior
        contribution to the student's cumulative counters and applies the new values,
        increments `amendment_count`, bumps the student's `version`, and appends
        `ENROLLMENT_AMENDED`."

        Design: Difficulty/compensating_invariant/enrollment_amendment_conserves_cumulative_earned
        """
        student, e2 = self._world(api)
        assert get_student(student["id"])["cumulative_earned_credits"] == 9

        amended = validate_success(api.amend_enrollment(
            e2["id"], amend_payload(0, 0.0, 6, "Grade changed B -> F"), REGISTRAR), 200)
        assert amended["status"] == "AMENDED"
        assert get_student(student["id"])["cumulative_earned_credits"] == 6, (
            "forward amend 3 -> 0 must reverse the prior contribution")

        validate_success(api.amend_enrollment(
            e2["id"], amend_payload(3, 9.0, 6, "Grade appeal upheld: F -> B restored"),
            REGISTRAR), 200)
        assert get_student(student["id"])["cumulative_earned_credits"] == 9, (
            "the compensating amend must restore the ledger exactly, with no drift")

    def test_amendment_never_touches_attempted_credits(self, api):
        """PRD section 3.2: "The attempted-credit figure is fixed at creation — later
        amendments adjust only outcome fields — and creation appends
        `ENROLLMENT_CREATED`."
        PRD section 3.3: "The pace metric `pace_pct` is one hundred times the summed
        earned credits divided by the summed attempted credits, rounded half up to two
        decimal places; it is null when no attempted credits exist at all."

        Design: Difficulty/compensating_invariant/enrollment_amendment_conserves_cumulative_earned
        """
        student, e2 = self._world(api)
        for earned, qp in ((0, 0.0), (3, 9.0)):
            amended = validate_success(api.amend_enrollment(
                e2["id"], amend_payload(earned, qp, 6, "correction"), REGISTRAR), 200)
            current = get_student(student["id"])
            assert current["cumulative_attempted_credits"] == 12, (
                "amendment must never move attempted credits")

        assert amended["amendment_count"] == 2
        assert amended["status"] == "AMENDED"
        assert current["pace_pct"] == pytest.approx(75.0)


def test_amend_cascade_supersedes_evaluation_and_reinstates(api):
    """PRD section 3.2: "If an `OFFICIAL` evaluation exists for that student and term,
    it is superseded — its status becomes `SUPERSEDED` — and the single-student
    evaluation pipeline of §3.5 re-runs: a replacement `OFFICIAL` evaluation is
    created from the recomputed metrics, standing is reassigned, notifications are
    queued, and the corresponding audit rows (`EVALUATION_SUPERSEDED`, then
    `EVALUATION_POSTED`, then whatever the standing and notification cascade adds) are
    appended."

    Design: Corner/complexity_layers/amend_cascade_supersedes_evaluation_and_reinstates
    """
    world = setup_suspended_student(
        t2_stats={"attempted_credits": 12, "earned_credits": 3,
                  "quality_points": 6.0, "gpa_hours": 6})
    student_id = world["student"]["id"]
    term2 = world["terms"][2]
    old_evaluation = world["evaluation"]

    enrollment_rows, _ = validate_paginated(api.list_enrollments(
        AID_OFFICER, params={"student_id": student_id, "term_id": term2["id"]}))
    enrollment_id = enrollment_rows[0]["id"]
    amended = validate_success(api.amend_enrollment(
        enrollment_id, amend_payload(12, 48.0, 12, "Grade appeal upheld: F -> A"),
        REGISTRAR), 200)
    assert amended["status"] == "AMENDED"

    superseded = validate_success(
        api.get_evaluation(old_evaluation["id"], AID_OFFICER), 200)
    assert superseded["status"] == "SUPERSEDED"

    replacement = official_evaluation(student_id, term2["id"])
    assert replacement["id"] != old_evaluation["id"]
    assert replacement["result_standing"] == "GOOD_STANDING"
    assert replacement["pace_pct"] == pytest.approx(83.33)
    assert replacement["cumulative_gpa"] == pytest.approx(3.0)

    student = get_student(student_id)
    assert student["sap_status"] == "GOOD_STANDING"
    assert student["pace_pct"] == pytest.approx(83.33)

    reinstatements = list_notifications(
        {"student_id": student_id, "kind": "REINSTATEMENT"})
    assert len(reinstatements) == 1
    assert reinstatements[0]["status"] == "QUEUED"

    superseded_events = list_audit_events(
        {"student_id": student_id, "action": "EVALUATION_SUPERSEDED"})
    assert len(superseded_events) == 1
    assert superseded_events[0]["entity_id"] == old_evaluation["id"]
    amended_events = list_audit_events(
        {"student_id": student_id, "action": "ENROLLMENT_AMENDED"})
    assert len(amended_events) == 1


def test_amend_response_immediately_reflects_new_values(api):
    """PRD section 3.2: "The amendment fully reverses the enrollment's prior
    contribution to the student's cumulative counters and applies the new values,
    increments `amendment_count`, bumps the student's `version`, and appends
    `ENROLLMENT_AMENDED`."
    PRD section 2.5: "`version` (integer): a system-managed counter that increments
    with every modification, including modifications performed by the server itself as
    cascade side effects."

    Design: Corner/consistency_model/amend_response_immediately_reflects_new_values
    """
    program = create_program(code="BS-IC", name="Immediate", required_credits=120)
    term = create_term(1)
    student = create_student(program["id"], student_number="S-7001")
    posted = create_posted_enrollment(student["id"], term["id"], 6, 3, 9.0, 6)

    amended = validate_success(api.amend_enrollment(
        posted["id"], amend_payload(6, 24.0, 6, "correction"), REGISTRAR), 200)
    assert amended["earned_credits"] == 6
    assert amended["status"] == "AMENDED"
    assert amended["version"] == posted["version"] + 1, (
        "the amend response itself must carry the bumped version")

    student_after = get_student(student["id"])
    assert student_after["cumulative_earned_credits"] == 6
    assert student_after["cumulative_quality_points"] == pytest.approx(24.0)
    assert student_after["cumulative_gpa"] == pytest.approx(4.0)
