"""The term-end evaluation pipeline: gating, standing cycles, and cascades."""
import pytest

from test_helpers import (
    AID_OFFICER, REGISTRAR, api_client, close_and_evaluate, close_grading,
    create_enrollment, create_posted_enrollment, create_program, create_student,
    create_standard_terms, create_term, evaluate_term, get_student,
    list_audit_events, list_evaluations, list_notifications,
    official_evaluation, post_grades, setup_approved_appeal,
    setup_suspended_student, validate_error, validate_paginated,
    validate_success,
)


class TestTermCloseAndEvaluateGates:
    """Evaluation needs a grading-closed term; closing needs zero in-progress rows."""

    def _world(self, api):
        program = create_program(code="BS-GEOL", name="Geology", required_credits=120)
        term = create_term(1)
        student = create_student(program["id"], student_number="S-9302",
                                 full_name="Hal Pending")
        enrollment = create_enrollment(student["id"], term["id"], 12)
        return term, student, enrollment

    def test_evaluate_on_open_term_rejected(self, api):
        """PRD section 3.5: "An `AidOfficer` runs the evaluation pipeline over a
        `GRADING_CLOSED` term; a run against a term that has not been closed fails with
        `ERR_TERM_NOT_READY`, and a repeat run against an already `EVALUATED` term
        fails with `ERR_INVALID_STATE`, since each term is evaluated exactly once
        before `EVALUATED` becomes terminal."

        Design: Difficulty/cross_entity_state_dependency/term_close_requires_all_enrollments_posted
        """
        term, _student, _enrollment = self._world(api)
        res = api.evaluate_term(term["id"], AID_OFFICER)
        validate_error(res, "ERR_TERM_NOT_READY")

    def test_close_grading_blocked_until_all_enrollments_posted(self, api):
        """PRD section 3.5: "The transition from `OPEN` to `GRADING_CLOSED` requires
        that no enrollment in the term remain `IN_PROGRESS`; any lingering in-progress
        row fails the close with `ERR_ENROLLMENTS_PENDING`."

        Design: Difficulty/cross_entity_state_dependency/term_close_requires_all_enrollments_posted
        """
        term, _student, enrollment = self._world(api)
        res = api.close_grading(term["id"], REGISTRAR)
        validate_error(res, "ERR_ENROLLMENTS_PENDING")

        post_grades(enrollment["id"], 12, 48.0, 12)
        closed = validate_success(api.close_grading(term["id"], REGISTRAR), 200)
        assert closed["status"] == "GRADING_CLOSED"


class TestEvaluationCascadeToAudit:
    """One evaluate call mutates term, evaluation, student, notification, and audit."""

    def _world(self, api):
        program = create_program(code="BS-PHYS", name="Physics", required_credits=120)
        term = create_term(1)
        student = create_student(program["id"], student_number="S-7001",
                                 full_name="Cal Cascade")
        create_posted_enrollment(student["id"], term["id"], 12, 6, 24.0, 12)
        close_grading(term["id"])
        return term, student

    def test_evaluate_cascade_evaluation_standing_notification(self, api):
        """PRD section 3.5: "Each swept student receives an official `SapEvaluation`
        row bound to their `student_id` and the term's `term_id`" and "The row records
        `prior_standing` — the student's standing immediately before the evaluation —
        and `result_standing`, the standing it assigns".
        PRD section 3.8: "Any other standing change — a fall to `WARNING`, a recovery
        from `WARNING` — queues a plain `STANDING_CHANGE` at `evaluated_at`."

        Design: Difficulty/transitive_cascade/term_evaluation_cascade_to_audit
        """
        term, student = self._world(api)
        summary = evaluate_term(term["id"])
        assert summary["evaluated_count"] == 1
        assert summary["warning_count"] == 1

        evaluation = official_evaluation(student["id"], term["id"])
        assert evaluation["status"] == "OFFICIAL"
        assert evaluation["result_standing"] == "WARNING"

        student_after = get_student(student["id"])
        assert student_after["sap_status"] == "WARNING"

        notifications = list_notifications({"student_id": student["id"]})
        assert len(notifications) == 1
        assert notifications[0]["kind"] == "STANDING_CHANGE"
        assert notifications[0]["status"] == "QUEUED"
        assert notifications[0]["scheduled_at"].startswith("2026-08-01T00:00:00"), (
            "queued at evaluated_at; the logical clock starts at 2026-08-01T00:00:00Z")

    def test_evaluate_cascade_audit_trail_complete(self, api):
        """PRD section 3.5: "Per student the cascade appends `EVALUATION_POSTED`, then
        — when standing moved — `STANDING_CHANGED`, then one `NOTIFICATION_QUEUED` per
        queued notification; the term itself closes the run with a single
        `TERM_EVALUATED`."
        PRD section 2.10: "Every mutation in the system appends one or more
        `AuditEvent` rows to an append-only trail; no endpoint exists to modify or
        delete audit rows."
        PRD section 2.10: "the affected `student_id` for federal-review scoping (null
        on `Program` and `Term` rows)"

        Design: Difficulty/transitive_cascade/term_evaluation_cascade_to_audit
        """
        term, student = self._world(api)
        evaluate_term(term["id"])

        events = list_audit_events({"student_id": student["id"]})
        actions = sorted(e["action"] for e in events)
        assert actions == sorted([
            "STUDENT_CREATED", "ENROLLMENT_CREATED", "ENROLLMENT_POSTED",
            "EVALUATION_POSTED", "STANDING_CHANGED", "NOTIFICATION_QUEUED",
        ]), "one audit event per mutation along the evaluate cascade"

        term_events = list_audit_events({"entity_type": "Term"})
        assert {e["action"] for e in term_events} == {
            "TERM_CREATED", "TERM_GRADING_CLOSED", "TERM_EVALUATED"}
        assert all(e["student_id"] is None for e in term_events)


class TestStandingWarningReinstatementCycle:
    """GOOD_STANDING -> WARNING -> GOOD_STANDING without any appeal."""

    def _world(self, api):
        """T1: pace 50.00 fails (GPA 2.000 passes) -> WARNING. T2: perfect term lifts
        the cumulative figures to pace 75.00 / GPA 3.000 -> GOOD_STANDING."""
        program = create_program(code="BA-ENGL", name="English", required_credits=120)
        terms = create_standard_terms(2)
        student = create_student(program["id"], student_number="S-6001",
                                 full_name="Wendy Warning")
        create_posted_enrollment(student["id"], terms[1]["id"], 12, 6, 24.0, 12)
        close_and_evaluate(terms[1]["id"])
        create_posted_enrollment(student["id"], terms[2]["id"], 12, 12, 48.0, 12)
        close_and_evaluate(terms[2]["id"])
        return terms, student

    def test_standing_cycle_evaluation_rows(self, api):
        """PRD section 3.5: "4. Otherwise the failure is progressive by prior standing:
        `GOOD_STANDING` moves to `WARNING`; `WARNING` moves to `SUSPENSION`;
        `SUSPENSION` remains `SUSPENSION`; `PROBATION` falls back to `SUSPENSION`;
        `PLAN_PENDING` remains `PLAN_PENDING` while the student awaits plan creation."
        PRD section 3.5: "3. Otherwise, when pace meets the program standard and the
        qualitative standard is satisfied — GPA null or at least `min_gpa` — the
        student is assigned `GOOD_STANDING` from any prior standing."

        Design: Difficulty/non_linear_state_machine/student_standing_warning_reinstatement_cycle
        """
        terms, student = self._world(api)
        evaluation_t1 = official_evaluation(student["id"], terms[1]["id"])
        assert evaluation_t1["prior_standing"] == "GOOD_STANDING"
        assert evaluation_t1["result_standing"] == "WARNING"

        evaluation_t2 = official_evaluation(student["id"], terms[2]["id"])
        assert evaluation_t2["prior_standing"] == "WARNING"
        assert evaluation_t2["result_standing"] == "GOOD_STANDING", "cycle closes"

    def test_recovery_from_warning_queues_only_standing_change(self, api):
        """PRD section 3.8: "When an evaluation returns a student to `GOOD_STANDING`
        from `SUSPENSION`, `PROBATION`, or `PLAN_ACTIVE`, a `REINSTATEMENT` notice is
        queued at `evaluated_at`. Any other standing change — a fall to `WARNING`, a
        recovery from `WARNING` — queues a plain `STANDING_CHANGE` at `evaluated_at`."

        Design: Difficulty/non_linear_state_machine/student_standing_warning_reinstatement_cycle
        """
        _terms, student = self._world(api)
        student_after = get_student(student["id"])
        assert student_after["sap_status"] == "GOOD_STANDING"
        assert student_after["pace_pct"] == pytest.approx(75.0)
        assert student_after["cumulative_gpa"] == pytest.approx(3.0)

        notifications = list_notifications({"student_id": student["id"]})
        assert len(notifications) == 2
        assert all(n["kind"] == "STANDING_CHANGE" for n in notifications), (
            "recovery from WARNING is a plain standing change, not a reinstatement")


def test_term_evaluate_twice_rejected(api):
    """PRD section 3.5: "An `AidOfficer` runs the evaluation pipeline over a
    `GRADING_CLOSED` term; a run against a term that has not been closed fails with
    `ERR_TERM_NOT_READY`, and a repeat run against an already `EVALUATED` term fails
    with `ERR_INVALID_STATE`, since each term is evaluated exactly once before
    `EVALUATED` becomes terminal."

    Design: Corner/state_machines/term_evaluate_twice_rejected
    """
    program = create_program(code="BS-TE", name="TwiceEval", required_credits=120)
    term = create_term(1)
    student = create_student(program["id"], student_number="S-1007",
                             full_name="Eval Twice")
    create_posted_enrollment(student["id"], term["id"], 12, 12, 48.0, 12)
    close_and_evaluate(term["id"])

    res = api.evaluate_term(term["id"], AID_OFFICER)
    validate_error(res, "ERR_INVALID_STATE")

    rows = list_evaluations({"student_id": student["id"], "term_id": term["id"]})
    assert len(rows) == 1, "a rejected re-run must not duplicate the OFFICIAL row"


def test_evaluate_returns_standing_counts(api):
    """PRD section 3.5: "The response summarizes the sweep with four counters:
    `evaluated_count`, `good_standing_count`, `warning_count`, and
    `suspension_count`."
    PRD section 3.5: "The sweep set has two parts: every student with at least one
    enrollment in this term in `POSTED` or `AMENDED` status, union every student
    holding an `ACTIVE` academic plan with a `PENDING` checkpoint tied to this term."

    Design: Corner/endpoints/evaluate_returns_standing_counts
    """
    program = create_program(code="BS-CT2", name="Counts", required_credits=120)
    terms = create_standard_terms(2)
    student_a = create_student(program["id"], student_number="S-4001",
                               full_name="Good One")
    student_b = create_student(program["id"], student_number="S-4002",
                               full_name="Warn One")
    student_c = create_student(program["id"], student_number="S-4003",
                               full_name="Susp One")
    # T1 sweeps only C (the only enrolled student): first failure -> WARNING.
    create_posted_enrollment(student_c["id"], terms[1]["id"], 12, 3, 12.0, 12)
    close_and_evaluate(terms[1]["id"])
    # T2 sweeps A (first term, passes), B (first term, fails pace), C (second failure).
    create_posted_enrollment(student_a["id"], terms[2]["id"], 12, 12, 36.0, 12)
    create_posted_enrollment(student_b["id"], terms[2]["id"], 12, 6, 24.0, 12)
    create_posted_enrollment(student_c["id"], terms[2]["id"], 12, 3, 12.0, 12)
    close_grading(terms[2]["id"])

    summary = evaluate_term(terms[2]["id"])
    assert summary["evaluated_count"] == 3
    assert summary["good_standing_count"] == 1
    assert summary["warning_count"] == 1
    assert summary["suspension_count"] == 1

    evaluation_c = official_evaluation(student_c["id"], terms[2]["id"])
    assert evaluation_c["prior_standing"] == "WARNING"
    assert evaluation_c["result_standing"] == "SUSPENSION"
    # A and B were not swept at T1: they hold no T1 evaluation row.
    for stu in (student_a, student_b):
        assert list_evaluations(
            {"student_id": stu["id"], "term_id": terms[1]["id"]}) == []


def test_probation_failure_returns_suspension(api):
    """PRD section 3.5: "4. Otherwise the failure is progressive by prior standing:
    `GOOD_STANDING` moves to `WARNING`; `WARNING` moves to `SUSPENSION`; `SUSPENSION`
    remains `SUSPENSION`; `PROBATION` falls back to `SUSPENSION`; `PLAN_PENDING`
    remains `PLAN_PENDING` while the student awaits plan creation."

    Design: Corner/state_machines/probation_failure_returns_suspension
    """
    world = setup_approved_appeal(resolution="PROBATION_ONLY")
    student_id = world["student"]["id"]
    assert world["student"]["sap_status"] == "PROBATION"

    create_posted_enrollment(student_id, world["terms"][3]["id"], 6, 0, 0.0, 6)
    close_and_evaluate(world["terms"][3]["id"])

    evaluation = official_evaluation(student_id, world["terms"][3]["id"])
    assert evaluation["prior_standing"] == "PROBATION"
    assert evaluation["result_standing"] == "SUSPENSION"
    assert get_student(student_id)["sap_status"] == "SUSPENSION"
    assert evaluation["appeal_deadline_at"].startswith("2026-08-15T00:00:00"), (
        "a fresh appeal window: evaluated_at + the program's 14 appeal_window_days")


def test_standing_reinstatement_without_appeal(api):
    """PRD section 3.5: "3. Otherwise, when pace meets the program standard and the
    qualitative standard is satisfied — GPA null or at least `min_gpa` — the student is
    assigned `GOOD_STANDING` from any prior standing. This is the reinstatement path:
    `WARNING` returns to good standing, and `SUSPENSION`, `PROBATION`, and plan
    completions all return through it."
    PRD section 3.8: "When an evaluation returns a student to `GOOD_STANDING` from
    `SUSPENSION`, `PROBATION`, or `PLAN_ACTIVE`, a `REINSTATEMENT` notice is queued at
    `evaluated_at`."

    Design: Corner/state_machines/standing_reinstatement_without_appeal
    """
    world = setup_suspended_student()
    student_id = world["student"]["id"]
    create_posted_enrollment(student_id, world["terms"][3]["id"], 12, 12, 48.0, 12)
    close_and_evaluate(world["terms"][3]["id"])

    evaluation = official_evaluation(student_id, world["terms"][3]["id"])
    assert evaluation["prior_standing"] == "SUSPENSION"
    assert evaluation["result_standing"] == "GOOD_STANDING", (
        "pace 75.00 >= 67.00 and GPA 2.500 >= 2.0 reinstate without any appeal")

    reinstatements = list_notifications(
        {"student_id": student_id, "kind": "REINSTATEMENT"})
    assert len(reinstatements) == 1
    assert reinstatements[0]["status"] == "QUEUED"
