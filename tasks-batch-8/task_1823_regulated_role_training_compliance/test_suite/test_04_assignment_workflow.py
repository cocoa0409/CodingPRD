"""Training-assignment workflow: start, submit, review, fail, void, expire."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_completion,
    add_requirement,
    assert_instant_equal,
    create_active_curriculum,
    create_employee,
    create_leave,
    create_regulator,
    create_role,
    find_assignment,
    get_assignment,
    get_employee,
    list_completions,
    make_employee_headers,
    reject_completion,
    run_sweep,
    set_clock,
    setup_employee_with_assignment,
    submit_completion,
    validate_error,
    validate_success,
    verify_assignment,
    void_completion,
)
from test_helpers import factories

ADMIN = TEST_USERS["compliance_admin_headers"]


def test_start_twice_returns_invalid_state(api):
    """PRD §3.4: "Starting an assignment moves `progress_status` from `ASSIGNED`
    to `IN_PROGRESS`; the caller must be the assignment's own employee
    (`ERR_OWNERSHIP_MISMATCH`), the assignment must still be `ASSIGNED`
    (`ERR_INVALID_STATE`), and a `TERMINATED` employee may not start training
    (`ERR_EMPLOYEE_TERMINATED`)."

    Design: Corner/state_machines/assignment_start_twice_returns_invalid_state
    """
    ctx = setup_employee_with_assignment("ST2")
    asg, emp = ctx["assignment"], ctx["employee"]

    first = api.start_assignment(asg["id"], make_employee_headers(emp["id"]))
    assert validate_success(first, 200)["progress_status"] == "IN_PROGRESS"

    second = api.start_assignment(asg["id"], make_employee_headers(emp["id"]))
    validate_error(second, ApiErrorId.ERR_INVALID_STATE.value)


def test_frozen_assignment_rejects_submission(api):
    """PRD §3.4: "the deadline dimension must not be `FROZEN` — an employee on
    leave cannot submit (`ERR_ASSIGNMENT_FROZEN`)"

    Design: Corner/validations/frozen_assignment_rejects_submission
    """
    set_clock("2026-08-03T09:00:00Z")
    reg = create_regulator(code="REG-FZ2", name="FZ2 Regulator")
    cur = create_active_curriculum(reg["id"], code="CUR-FZ2", title="FZ2 Course")
    role = create_role(code="R-FZ2", name="FZ2 Role")
    emp = create_employee("E-FZ2-1", role["id"], full_name="FZ2 Emp")
    create_leave(emp["id"])  # window covers the clock -> ON_LEAVE
    add_requirement(role["id"], cur["id"])

    asg = find_assignment(emp["id"], curriculum_id=cur["id"])
    assert asg["deadline_status"] == "FROZEN"

    resp = api.submit_completion(
        asg["id"], factories.submit_completion_payload(),
        make_employee_headers(emp["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_FROZEN.value)


def test_evidence_tier_and_uri_enforced(api):
    """PRD §3.4: "the supplied evidence tier must be at least the curriculum's
    `evidence_requirement` in the tier ordering (`ERR_EVIDENCE_TYPE_INSUFFICIENT`);
    and `evidence_uri` is required exactly when `evidence_type` is not `NONE`,
    its absence on a tiered submission failing with `ERR_EVIDENCE_URI_MISSING`."

    Design: Corner/validations/evidence_tier_and_uri_enforced_in_order
    """
    ctx = setup_employee_with_assignment("EV", evidence_requirement="PROCTORED_CERTIFICATE")
    asg, emp = ctx["assignment"], ctx["employee"]

    low_tier = api.submit_completion(
        asg["id"],
        {"score_pct": 90, "evidence_type": "CERTIFICATE", "evidence_uri": "uri://cert"},
        make_employee_headers(emp["id"]),
    )
    validate_error(low_tier, ApiErrorId.ERR_EVIDENCE_TYPE_INSUFFICIENT.value)

    no_uri = api.submit_completion(
        asg["id"],
        {"score_pct": 90, "evidence_type": "PROCTORED_CERTIFICATE"},
        make_employee_headers(emp["id"]),
    )
    validate_error(no_uri, ApiErrorId.ERR_EVIDENCE_URI_MISSING.value)

    ok = api.submit_completion(
        asg["id"],
        {"score_pct": 90, "evidence_type": "PROCTORED_CERTIFICATE",
         "evidence_uri": "uri://proc/123"},
        make_employee_headers(emp["id"]),
    )
    record = validate_success(ok, 201)
    assert record["review_status"] == "PENDING_REVIEW"
    assert record["passed"] is True


class TestScoreBoundary:
    def test_score_below_passing_rejected(self, api):
        """PRD §3.4: "the score must be at least the curriculum's *current*
        `passing_score_pct`, with an exactly-equal score passing
        (`ERR_SCORE_BELOW_PASSING`)"

        Design: Difficulty/boundary_precision_check/score_exactly_at_passing_boundary
        """
        ctx = setup_employee_with_assignment("B6A")
        asg, emp = ctx["assignment"], ctx["employee"]

        resp = api.submit_completion(
            asg["id"], factories.submit_completion_payload(score_pct=79.99),
            make_employee_headers(emp["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SCORE_BELOW_PASSING.value)

        _, meta = list_completions(asg["id"])
        assert meta["total_count"] == 0, "rejected submission persists no record"

    def test_score_exactly_at_passing_succeeds(self, api):
        """PRD §3.4: "the score must be at least the curriculum's *current*
        `passing_score_pct`, with an exactly-equal score passing
        (`ERR_SCORE_BELOW_PASSING`)"
        PRD §3.4: "`is_late`, true exactly when the submission instant is
        strictly later than the assignment's `due_at` — a submission exactly at
        the due instant is on time"

        Design: Difficulty/boundary_precision_check/score_exactly_at_passing_boundary
        """
        ctx = setup_employee_with_assignment("B6A")
        asg, emp = ctx["assignment"], ctx["employee"]

        resp = api.submit_completion(
            asg["id"], factories.submit_completion_payload(score_pct=80.00),
            make_employee_headers(emp["id"]),
        )
        record = validate_success(resp, 201)
        assert record["passed"] is True, "80.00 >= 80.00: equality passes"
        assert record["is_late"] is False, "submission is far before due_at"

        updated = get_assignment(asg["id"])
        assert updated["progress_status"] == "SUBMITTED"


class TestTerminalAssignmentGate:
    def test_submission_on_verified_completed_rejected(self, api):
        """PRD §3.4: "Submitting completion evidence creates a
        **CompletionRecord** beneath the assignment and advances
        `progress_status` from `ASSIGNED` or `IN_PROGRESS` to `SUBMITTED`."
        PRD §3.4: "progress must be `ASSIGNED` or `IN_PROGRESS`
        (`ERR_ASSIGNMENT_NOT_SUBMITTABLE`)"

        Design: Difficulty/cross_entity_state_dependency/completion_blocked_by_assignment_terminal_state
        """
        ctx = setup_employee_with_assignment("X7A")
        asg, emp = ctx["assignment"], ctx["employee"]
        verify_assignment(asg["id"], emp["id"], score_pct=90)
        assert get_assignment(asg["id"])["progress_status"] == "VERIFIED_COMPLETED"

        resp = api.submit_completion(
            asg["id"], factories.submit_completion_payload(score_pct=95),
            make_employee_headers(emp["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_SUBMITTABLE.value)

    def test_rejected_submission_on_terminal_persists_no_record(self, api):
        """PRD §3.4: "progress must be `ASSIGNED` or `IN_PROGRESS`
        (`ERR_ASSIGNMENT_NOT_SUBMITTABLE`)"

        Design: Difficulty/cross_entity_state_dependency/completion_blocked_by_assignment_terminal_state
        """
        ctx = setup_employee_with_assignment("X7A")
        asg, emp = ctx["assignment"], ctx["employee"]
        verify_assignment(asg["id"], emp["id"], score_pct=90)

        api.submit_completion(
            asg["id"], factories.submit_completion_payload(score_pct=95),
            make_employee_headers(emp["id"]),
        )
        _, meta = list_completions(asg["id"])
        assert meta["total_count"] == 1, "only the original record exists"


class TestStatePriorityBeatsScoreSafety:
    def _setup_submitted(self):
        ctx = setup_employee_with_assignment("P5A")
        asg, emp = ctx["assignment"], ctx["employee"]
        submit_completion(asg["id"], emp["id"], score_pct=90)
        return ctx, asg, emp

    def test_submitted_assignment_with_failing_score_returns_state_error(self, api):
        """PRD §2.9: "State-machine preconditions (priority 7) beat regulatory
        safety gates (priority 11): a completion submitted against an assignment
        whose `progress_status` is already `SUBMITTED`, even with a failing
        score, returns `ERR_ASSIGNMENT_NOT_SUBMITTABLE`, not a score error."

        Design: Difficulty/priority_pair_validation_conflict/state_priority_beats_score_safety_on_submit
        """
        _, asg, emp = self._setup_submitted()
        resp = api.submit_completion(
            asg["id"], factories.submit_completion_payload(score_pct=10),
            make_employee_headers(emp["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_SUBMITTABLE.value)

    def test_rejected_resubmission_leaves_no_trace(self, api):
        """PRD §2.9: "State-machine preconditions (priority 7) beat regulatory
        safety gates (priority 11): a completion submitted against an assignment
        whose `progress_status` is already `SUBMITTED`, even with a failing
        score, returns `ERR_ASSIGNMENT_NOT_SUBMITTABLE`, not a score error."

        Design: Difficulty/priority_pair_validation_conflict/state_priority_beats_score_safety_on_submit
        """
        _, asg, emp = self._setup_submitted()
        api.submit_completion(
            asg["id"], factories.submit_completion_payload(score_pct=10),
            make_employee_headers(emp["id"]),
        )
        assert get_assignment(asg["id"])["progress_status"] == "SUBMITTED"
        _, meta = list_completions(asg["id"])
        assert meta["total_count"] == 1, "no record created by the rejected request"


def test_completion_review_state_gates(api):
    """PRD §3.4: "**Voiding** is the compensating action for an acceptance,
    permitted only on an `ACCEPTED` record (`ERR_COMPLETION_NOT_VOIDABLE`) and
    requiring a `reason`"
    PRD §3.4: "**Acceptance** — permitted only while the record is
    `PENDING_REVIEW`, else `ERR_COMPLETION_NOT_REVIEWABLE`"

    Design: Corner/errors/completion_review_state_gates
    """
    ctx = setup_employee_with_assignment("RSG")
    asg, emp = ctx["assignment"], ctx["employee"]
    c1 = submit_completion(asg["id"], emp["id"], score_pct=90)

    early_void = api.void_completion(c1["id"], {"reason": "premature"}, ADMIN)
    validate_error(early_void, ApiErrorId.ERR_COMPLETION_NOT_VOIDABLE.value)

    accepted = accept_completion(c1["id"])
    assert accepted["review_status"] == "ACCEPTED"

    second_accept = api.accept_completion(c1["id"], {}, ADMIN)
    validate_error(second_accept, ApiErrorId.ERR_COMPLETION_NOT_REVIEWABLE.value)


def test_terminal_failed_assignment_rejects_new_submission(api):
    """PRD §3.4: "It moves the record to `REJECTED`, increments the assignment's
    `attempts_used` by 1, and then branches on the attempt ceiling: once
    `attempts_used` reaches the curriculum's `max_attempts`, the assignment
    fails outright into `FAILED` — recomputing the employee's
    `compliance_blocked`, which a HARD-requirement failure sets, and cascading
    the employee's `PENDING` attestations under `OPEN` campaigns into `BLOCKED`;
    below the ceiling, the assignment loops back to `IN_PROGRESS` for another
    attempt."
    PRD §3.4: "progress must be `ASSIGNED` or `IN_PROGRESS`
    (`ERR_ASSIGNMENT_NOT_SUBMITTABLE`)"

    Design: Corner/state_machines/terminal_failed_assignment_rejects_new_submission
    """
    ctx = setup_employee_with_assignment("FAIL", max_attempts=2, criticality="HARD")
    asg, emp = ctx["assignment"], ctx["employee"]

    c1 = submit_completion(asg["id"], emp["id"], score_pct=90)
    reject_completion(c1["id"], review_note="first reject")
    c2 = submit_completion(asg["id"], emp["id"], score_pct=92)
    reject_completion(c2["id"], review_note="second reject")

    updated = get_assignment(asg["id"])
    assert updated["progress_status"] == "FAILED", "second reject reached max_attempts"
    assert updated["attempts_used"] == 2

    resp = api.submit_completion(
        asg["id"], factories.submit_completion_payload(score_pct=99),
        make_employee_headers(emp["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_SUBMITTABLE.value)

    employee = get_employee(emp["id"])
    assert employee["compliance_blocked"] is True, (
        "HARD requirement FAILED with no later verified assignment"
    )


class TestRevisionLoop:
    def _setup_loop(self):
        return setup_employee_with_assignment(
            "LOOP", recurrence="VALIDITY_CYCLE", due_in_days=2, max_attempts=3,
        )

    def test_reject_loops_back_and_accept_sets_validity_horizon(self, api):
        """PRD §3.4: "It moves the record to `REJECTED`, increments the
        assignment's `attempts_used` by 1, and then branches on the attempt
        ceiling: once `attempts_used` reaches the curriculum's `max_attempts`,
        the assignment fails outright into `FAILED` — recomputing the employee's
        `compliance_blocked`, which a HARD-requirement failure sets, and
        cascading the employee's `PENDING` attestations under `OPEN` campaigns
        into `BLOCKED`; below the ceiling, the assignment loops back to
        `IN_PROGRESS` for another attempt."
        PRD §3.4: "for a `VALIDITY_CYCLE` requirement, `expires_at` is
        `completed_at` plus the curriculum's `validity_months` calendar months,
        day clamped to month end on overflow"
        PRD §3.4: "an `attempt_no` equal to one more than the assignment's prior
        completion-record count (so the first attempt is numbered 1)"

        Design: Difficulty/non_linear_state_machine/assignment_parallel_dimensions_revision_loop
        """
        ctx = self._setup_loop()
        asg, emp = ctx["assignment"], ctx["employee"]

        api.start_assignment(asg["id"], make_employee_headers(emp["id"]))
        set_clock("2026-08-06T09:00:01Z")
        run_sweep()

        c1 = submit_completion(asg["id"], emp["id"], score_pct=90)
        assert c1["is_late"] is True, "submitted strictly after due_at"
        reject_completion(c1["id"], review_note="blurry evidence")

        mid = get_assignment(asg["id"])
        assert mid["progress_status"] == "IN_PROGRESS", "reject loops SUBMITTED -> IN_PROGRESS"
        assert mid["attempts_used"] == 1

        c2 = submit_completion(asg["id"], emp["id"], score_pct=92)
        assert c2["attempt_no"] == 2, "attempt ordinals continue across the loop"
        accept_completion(c2["id"])

        done = get_assignment(asg["id"])
        assert done["progress_status"] == "VERIFIED_COMPLETED"
        assert done["attempts_used"] == 1, "accept does not consume attempts"
        assert_instant_equal(done["completed_at"], "2026-08-06T09:00:01Z", "completed_at")
        assert_instant_equal(done["expires_at"], "2027-08-06T09:00:01Z", "expires_at")

    def test_deadline_dimension_runs_parallel_then_freezes_at_terminal(self, api):
        """PRD §3.4: "Two independent status dimensions ride on every assignment
        and evolve in parallel."
        PRD §3.4: "it is computed at creation — an assignment born close to its
        due date is born `DUE_SOON`, and one born to an employee on leave is
        born `FROZEN`"
        PRD §3.4: "Once the progress dimension reaches a terminal state, the
        deadline dimension freezes permanently at its last value."

        Design: Difficulty/non_linear_state_machine/assignment_parallel_dimensions_revision_loop
        """
        ctx = self._setup_loop()
        asg, emp = ctx["assignment"], ctx["employee"]

        born = get_assignment(asg["id"])
        assert born["progress_status"] == "ASSIGNED"
        assert born["deadline_status"] == "DUE_SOON", (
            "born inside the 7-day reminder window: due - assigned = 2d"
        )

        api.start_assignment(asg["id"], make_employee_headers(emp["id"]))
        set_clock("2026-08-06T09:00:01Z")
        sweep = run_sweep()
        assert sweep["notices_created"] == 1, (
            "level-2 OVERDUE_MANAGER only; no sweep ever observed DUE_SOON"
        )

        after_sweep = get_assignment(asg["id"])
        assert after_sweep["progress_status"] == "IN_PROGRESS", "sweep moved deadline only"
        assert after_sweep["deadline_status"] == "OVERDUE"

        c1 = submit_completion(asg["id"], emp["id"], score_pct=90)
        after_submit = get_assignment(asg["id"])
        assert after_submit["progress_status"] == "SUBMITTED", "submission moves progress only"
        assert after_submit["deadline_status"] == "OVERDUE"

        accept_completion(c1["id"])
        done = get_assignment(asg["id"])
        assert done["progress_status"] == "VERIFIED_COMPLETED"
        assert done["deadline_status"] == "OVERDUE", (
            "deadline dimension frozen at last value once progress is terminal"
        )


class TestAcceptVoidCompensation:
    def _setup_verified(self):
        ctx = setup_employee_with_assignment(
            "X9B", recurrence="VALIDITY_CYCLE", validity_months=6,
        )
        asg, emp = ctx["assignment"], ctx["employee"]
        c1 = submit_completion(asg["id"], emp["id"], score_pct=90)
        accepted = accept_completion(c1["id"])
        return ctx, asg, emp, c1, accepted

    def test_accept_sets_verified_state_counts_and_expiry(self, api):
        """PRD §3.4: "moves the record to `ACCEPTED` with `reviewed_by` set to
        the reviewer's opaque operator id (an optional `review_note` may
        accompany it), moves the assignment to `VERIFIED_COMPLETED` with
        `completed_at` stamped, and sets the validity horizon: for a
        `VALIDITY_CYCLE` requirement, `expires_at` is `completed_at` plus the
        curriculum's `validity_months` calendar months, day clamped to month
        end on overflow"
        PRD §3.6: "`verified_completed_count` tracks how many of the employee's
        assignments currently stand `VERIFIED_COMPLETED`, incremented on
        acceptance, decremented on void and on expiry, and untouched by
        cancellation or termination."

        Design: Difficulty/compensating_invariant/accept_void_conserves_verified_completion_counts
        """
        ctx, asg, emp, c1, _ = self._setup_verified()
        employee = get_employee(emp["id"])
        assert employee["verified_completed_count"] == 1

        done = get_assignment(asg["id"])
        assert done["progress_status"] == "VERIFIED_COMPLETED"
        assert_instant_equal(done["completed_at"], "2026-08-03T09:00:00Z", "completed_at")
        assert_instant_equal(done["expires_at"], "2027-02-03T09:00:00Z", "expires_at (+6 months)")

    def test_void_restores_pre_accept_values_exactly(self, api):
        """PRD §3.4: "the record becomes `VOIDED`, the assignment falls from
        `VERIFIED_COMPLETED` back to `IN_PROGRESS` with `completed_at` and
        `expires_at` nulled, and the employee's verified count and block posture
        are recomputed."
        PRD §3.6: "`verified_completed_count` tracks how many of the employee's
        assignments currently stand `VERIFIED_COMPLETED`, incremented on
        acceptance, decremented on void and on expiry, and untouched by
        cancellation or termination."

        Design: Difficulty/compensating_invariant/accept_void_conserves_verified_completion_counts
        """
        _, asg, emp, c1, _ = self._setup_verified()
        voided = void_completion(c1["id"], reason="Evidence audit failure")
        assert voided["review_status"] == "VOIDED"

        employee = get_employee(emp["id"])
        assert employee["verified_completed_count"] == 0, "void decrements the count"

        restored = get_assignment(asg["id"])
        assert restored["progress_status"] == "IN_PROGRESS"
        assert restored["completed_at"] is None
        assert restored["expires_at"] is None
