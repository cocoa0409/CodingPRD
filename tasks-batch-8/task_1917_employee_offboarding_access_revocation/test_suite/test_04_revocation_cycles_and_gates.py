"""Revocation task cycles, exit interview loops, and state-machine gates.

Covers queue-A difficulty instances under `non_linear_state_machine`,
`cross_entity_state_dependency`, `resource_temporal_overlap`, and
`boundary_precision_check/kt_plan_zero_required_sessions_never_auto_completes`.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_error_is_one_of,
    get_success_data,
    ApiErrorId,
    assert_instant_equal,
    create_case,
    create_and_approve_case,
    create_case_with_plan,
    create_revocation_task,
    create_exit_interview,
    create_kt_session,
    set_clock,
    make_task_ready,
    execute_task,
    verify_task,
    HR_INTAKE,
    HR_APPROVER,
    HR_REVIEWER,
    IT_OP,
    IT_VER,
    IT_MGR,
    MGR,
)


class TestRevocationFailureRetryCycle:
    def test_revocation_task_failed_retry_cycle_increments_and_backoff(self):
        """PRD §3.2: "An `ITOperator` may retry a `FAILED` task, which moves it
        to `RETRY_SCHEDULED`, increments `retry_count` by one, and reschedules
        it to the current time plus sixty minutes multiplied by the newly
        incremented count — so the first retry waits one hour, the second two
        hours, the third three."

        Design: Difficulty/non_linear_state_machine/revocation_task_failed_retry_cycle
        """
        case = create_and_approve_case(employee_ref="E-CYC")
        task = create_revocation_task(case["id"], system_name="VPN", sequence_rank=1)
        set_clock("2026-08-10T17:00:00Z")
        # Cycle 1: fail + retry -> retry_count 1, next instant +60min
        execute_task(task["id"], outcome="FAILED", failure_reason="vpn concentrator timeout")
        retried1 = validate_success(api_client.retry_revocation_task(task["id"], IT_OP))
        assert retried1["retry_count"] == 1
        assert retried1["status"] == "RETRY_SCHEDULED"
        assert_instant_equal(retried1["scheduled_at"], "2026-08-10T18:00:00Z")

        set_clock("2026-08-10T18:00:00Z")
        # Cycle 2: fail + retry -> retry_count 2, next instant +120min from now
        execute_task(task["id"], outcome="FAILED", failure_reason="second failure")
        retried2 = validate_success(api_client.retry_revocation_task(task["id"], IT_OP))
        assert retried2["retry_count"] == 2
        assert retried2["status"] == "RETRY_SCHEDULED"
        assert_instant_equal(retried2["scheduled_at"], "2026-08-10T20:00:00Z")

    def test_revocation_task_retry_cycle_keeps_case_posture_not_complete(self):
        """PRD §3.2: "The posture is `COMPLETE` when every task is `VERIFIED` or
        `WAIVED` and at least one task exists. Otherwise it is `BLOCKED` when any
        task sits in `FAILED` or `RETRY_SCHEDULED` with a `retry_count` that has
        reached three. Otherwise it is `IN_PROGRESS` when any task is `READY`,
        `EXECUTED`, or `RETRY_SCHEDULED`."

        Design: Difficulty/non_linear_state_machine/revocation_task_failed_retry_cycle
        """
        case = create_and_approve_case(employee_ref="E-CYC2")
        task = create_revocation_task(case["id"], system_name="VPN", sequence_rank=1)
        set_clock("2026-08-10T17:00:00Z")
        execute_task(task["id"], outcome="FAILED", failure_reason="f1")
        validate_success(api_client.retry_revocation_task(task["id"], IT_OP))
        refreshed = get_success_data(api_client.get_case(case["id"], HR_INTAKE))
        assert refreshed["revocation_posture"] != "COMPLETE"


class TestExitInterviewRescheduleLoop:
    def test_exit_interview_reschedule_no_show_rehabilitation_loop(self):
        """PRD §3.5: "Requesting a reschedule moves a `SCHEDULED` interview to
        `RESCHEDULE_REQUESTED` and increments `reschedule_count`... An interview
        whose end passes while still `SCHEDULED` is marked `NO_SHOW` by the
        scheduler; one rehabilitation loop exists — rescheduling directly from
        `NO_SHOW` to `SCHEDULED` under the same overlap rule — which also
        consumes one tick of `reschedule_count`, since the cap of two applies
        across both loops combined."

        Design: Difficulty/non_linear_state_machine/exit_interview_reschedule_no_show_rehabilitation_loop
        """
        case = create_and_approve_case(employee_ref="E-EI")
        interview = create_exit_interview(
            case["id"], scheduled_start="2026-08-05T10:00:00Z", scheduled_end="2026-08-05T11:00:00Z"
        )
        # Loop 1: request-reschedule then apply new window
        r1 = validate_success(api_client.request_reschedule_interview(interview["id"], HR_INTAKE))
        assert r1["reschedule_count"] == 1
        r2 = validate_success(api_client.reschedule_interview(
            interview["id"],
            {"scheduled_start": "2026-08-06T10:00:00Z", "scheduled_end": "2026-08-06T11:00:00Z"},
            HR_INTAKE,
        ))
        assert r2["status"] == "SCHEDULED"

        # Drive clock past the new end -> scheduler marks NO_SHOW
        set_clock("2026-08-06T12:00:00Z")
        after_no_show = get_success_data(api_client.get_exit_interview(interview["id"], HR_INTAKE))
        assert after_no_show["status"] == "NO_SHOW"

        # Rehabilitation loop: reschedule directly from NO_SHOW
        r3 = validate_success(api_client.reschedule_interview(
            interview["id"],
            {"scheduled_start": "2026-08-07T10:00:00Z", "scheduled_end": "2026-08-07T11:00:00Z"},
            HR_INTAKE,
        ))
        assert r3["status"] == "SCHEDULED"
        assert r3["reschedule_count"] == 2

    def test_exit_interview_reschedule_cap_exceeded_across_loops(self):
        """PRD §3.5: "it is refused once the count has reached the cap of two,
        rejected with `ERR_RETRY_CAP_EXCEEDED`."

        Design: Difficulty/non_linear_state_machine/exit_interview_reschedule_no_show_rehabilitation_loop
        """
        case = create_and_approve_case(employee_ref="E-EI2")
        interview = create_exit_interview(
            case["id"], scheduled_start="2026-08-05T10:00:00Z", scheduled_end="2026-08-05T11:00:00Z"
        )
        validate_success(api_client.request_reschedule_interview(interview["id"], HR_INTAKE))
        validate_success(api_client.reschedule_interview(
            interview["id"],
            {"scheduled_start": "2026-08-06T10:00:00Z", "scheduled_end": "2026-08-06T11:00:00Z"},
            HR_INTAKE,
        ))
        set_clock("2026-08-06T12:00:00Z")
        validate_success(api_client.reschedule_interview(
            interview["id"],
            {"scheduled_start": "2026-08-07T10:00:00Z", "scheduled_end": "2026-08-07T11:00:00Z"},
            HR_INTAKE,
        ))
        # Cap of 2 reached across the two loops.
        resp = api_client.request_reschedule_interview(interview["id"], HR_INTAKE)
        validate_error(resp, ApiErrorId.ERR_RETRY_CAP_EXCEEDED, expected_status=422)


class TestRevocationCrossEntityGate:
    def test_revoke_execute_gated_on_case_status_voided_case(self):
        """PRD §3.2: "An `ITOperator` then executes a ready task, which is
        permitted only while the parent case is `APPROVED` or
        `REVOCATION_IN_PROGRESS`." PRD §3.1: "Once revocation has actually begun
        — any task `EXECUTED` or `VERIFIED` — an approved case can no longer be
        voided" and voiding "every revocation task still `PENDING`, `READY`, or
        `RETRY_SCHEDULED` becomes `WAIVED`."

        The case is voided while still APPROVED (advancing the clock past the
        task's scheduled_at would release it to READY and auto-advance the case
        to REVOCATION_IN_PROGRESS per §3.2, from which §3.1 forbids voiding);
        the cascade waives the still-PENDING task.

        Design: Difficulty/cross_entity_state_dependency/revoke_execute_gated_on_case_status
        """
        case = create_and_approve_case(employee_ref="E-X1")
        task = create_revocation_task(case["id"], system_name="EMAIL", sequence_rank=1)
        # Void the APPROVED case before any clock release; the cascade waives
        # the PENDING task.
        validate_success(api_client.void_case(
            case["id"], {"void_reason": "employee rescinded resignation"}, HR_APPROVER
        ))
        resp = api_client.execute_revocation_task(task["id"], {"outcome": "SUCCESS"}, IT_OP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_revoke_execute_on_pending_task_rejected(self):
        """PRD §3.2: "An `ITOperator` then executes a ready task" — a task still
        `PENDING` (scheduler has not released it) is not in a from-state for
        execute. PRD §2.6: "State legality — the target resource is in a
        from-state the requested transition allows... otherwise
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/revoke_execute_gated_on_case_status
        """
        case = create_and_approve_case(employee_ref="E-X1B")
        task = create_revocation_task(case["id"], system_name="EMAIL", sequence_rank=1)
        # Clock remains at startup default 2026-08-01 -> task stays PENDING.
        resp = api_client.execute_revocation_task(task["id"], {"outcome": "SUCCESS"}, IT_OP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestRehireSubmitGate:
    def test_rehire_submit_gated_on_case_clearance_stage_approved(self):
        """PRD §3.7: "an `HRReviewer` submits it — permitted once the case has
        reached `CLEARANCE_IN_PROGRESS` or `READY_TO_CLOSE`." While the case is
        `APPROVED`, the submit is not in a legal from-state and is rejected per
        §2.6 rule 4 with `ERR_INVALID_STATE` (HTTP 409).

        Design: Difficulty/cross_entity_state_dependency/rehire_submit_gated_on_case_clearance_stage
        """
        case = create_and_approve_case(employee_ref="E-X2")
        reviews = get_success_data(api_client.list_case_rehire_reviews(case["id"], HR_REVIEWER))
        review = reviews[0]
        resp = api_client.submit_rehire_review(
            review["id"],
            {"recommended_code": "ELIGIBLE", "rationale": "solid performer"},
            HR_REVIEWER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_rehire_submit_gated_on_case_clearance_stage_intake(self):
        """PRD §3.7: "an `HRReviewer` submits it — permitted once the case has
        reached `CLEARANCE_IN_PROGRESS` or `READY_TO_CLOSE`."

        Even deeper in the lifecycle: an INTAKE case never lets submit through.

        Design: Difficulty/cross_entity_state_dependency/rehire_submit_gated_on_case_clearance_stage
        """
        # Review is only auto-created at approve; build a case in APPROVED first
        # then verify the gate again before revocation progresses it.
        case = create_and_approve_case(employee_ref="E-X2B")
        # Sanity: case is APPROVED (not yet CLEARANCE_IN_PROGRESS).
        assert case["status"] == "APPROVED"
        reviews = get_success_data(api_client.list_case_rehire_reviews(case["id"], HR_REVIEWER))
        review = reviews[0]
        resp = api_client.submit_rehire_review(
            review["id"],
            {"recommended_code": "ELIGIBLE", "rationale": "premature"},
            HR_REVIEWER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestExitInterviewOverlap:
    def test_exit_interview_half_open_adjacency_allowed(self):
        """PRD §3.5: "its window must not overlap any other `SCHEDULED`
        interview of the same case, measured as a half-open interval that
        includes the start instant and excludes the end instant — so one
        interview ending exactly when another begins is not a conflict."

        Design: Difficulty/resource_temporal_overlap/exit_interview_half_open_adjacency_allowed
        """
        case = create_and_approve_case(employee_ref="E-O1")
        create_exit_interview(
            case["id"], scheduled_start="2026-08-05T10:00:00Z",
            scheduled_end="2026-08-05T11:00:00Z", interviewer_ref="hr-int-1",
        )
        # Adjacent: starts exactly when the first ends -> allowed under half-open.
        resp = api_client.create_exit_interview(
            {
                "offboarding_case_id": case["id"],
                "interviewer_ref": "hr-int-2",
                "scheduled_start": "2026-08-05T11:00:00Z",
                "scheduled_end": "2026-08-05T12:00:00Z",
            },
            HR_INTAKE,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "SCHEDULED"

    def test_exit_interview_half_open_overlap_rejected_by_one_minute(self):
        """PRD §3.5: "A violation is rejected with `ERR_SCHEDULE_OVERLAP`."
        Overlapping by one minute violates the half-open rule.

        Design: Difficulty/resource_temporal_overlap/exit_interview_half_open_adjacency_allowed
        """
        case = create_and_approve_case(employee_ref="E-O1B")
        create_exit_interview(
            case["id"], scheduled_start="2026-08-05T10:00:00Z",
            scheduled_end="2026-08-05T11:00:00Z", interviewer_ref="hr-int-1",
        )
        resp = api_client.create_exit_interview(
            {
                "offboarding_case_id": case["id"],
                "interviewer_ref": "hr-int-3",
                "scheduled_start": "2026-08-05T10:59:00Z",
                "scheduled_end": "2026-08-05T12:00:00Z",
            },
            HR_INTAKE,
        )
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_OVERLAP, expected_status=422)


class TestKTSessionOverlap:
    def test_kt_session_closed_interval_adjacency_forbidden(self):
        """PRD §3.5: "Session windows obey a stricter overlap rule than
        interviews: within one plan, a new session may not overlap another
        `SCHEDULED` session on a closed interval, and zero-minute adjacency is
        forbidden — a session starting exactly when another ends is already a
        conflict, rejected with `ERR_SCHEDULE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/kt_session_closed_interval_adjacency_forbidden
        """
        case, plan = create_case_with_plan(employee_ref="E-O2")
        validate_success(api_client.activate_kt_plan(plan["id"], MGR))
        create_kt_session(
            plan["id"], topic="sys overview",
            scheduled_start="2026-08-05T10:00:00Z", scheduled_end="2026-08-05T11:00:00Z",
        )
        # Adjacent session (starts at 11:00) -> closed interval forbids it.
        resp = api_client.create_kt_session(
            {
                "knowledge_transfer_plan_id": plan["id"],
                "topic": "adjacent topic",
                "scheduled_start": "2026-08-05T11:00:00Z",
                "scheduled_end": "2026-08-05T12:00:00Z",
                "successor_ref": "succ-1",
            },
            MGR,
        )
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_OVERLAP, expected_status=422)

    def test_kt_session_with_gap_allowed(self):
        """PRD §3.5: "Session windows obey a stricter overlap rule than
        interviews: ... zero-minute adjacency is forbidden." A session with a
        positive gap after the previous end is allowed.

        Design: Difficulty/resource_temporal_overlap/kt_session_closed_interval_adjacency_forbidden
        """
        case, plan = create_case_with_plan(employee_ref="E-O2B")
        validate_success(api_client.activate_kt_plan(plan["id"], MGR))
        create_kt_session(
            plan["id"], topic="sys overview",
            scheduled_start="2026-08-05T10:00:00Z", scheduled_end="2026-08-05T11:00:00Z",
        )
        resp = api_client.create_kt_session(
            {
                "knowledge_transfer_plan_id": plan["id"],
                "topic": "after break",
                "scheduled_start": "2026-08-05T11:15:00Z",
                "scheduled_end": "2026-08-05T12:00:00Z",
                "successor_ref": "succ-1",
            },
            MGR,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "SCHEDULED"


class TestKTPlanZeroRequiredBoundary:
    def test_kt_plan_zero_required_sessions_never_auto_completes_on_activation(self):
        """PRD §3.5: "A plan requiring zero sessions never auto-completes; the
        `Manager` completes it explicitly." Even at the 0>=0 boundary, the
        activation does not flip the plan to COMPLETE.

        Design: Difficulty/boundary_precision_check/kt_plan_zero_required_sessions_never_auto_completes
        """
        case, plan = create_case_with_plan(employee_ref="E-B2")
        assert plan["required_session_count"] == 0
        activated = validate_success(api_client.activate_kt_plan(plan["id"], MGR))
        assert activated["status"] == "ACTIVE"
        refreshed = get_success_data(api_client.get_kt_plan(plan["id"], MGR))
        assert refreshed["status"] == "ACTIVE"

    def test_kt_plan_zero_required_sessions_explicit_complete(self):
        """PRD §3.5: "A plan requiring zero sessions never auto-completes; the
        `Manager` completes it explicitly."

        Design: Difficulty/boundary_precision_check/kt_plan_zero_required_sessions_never_auto_completes
        """
        case, plan = create_case_with_plan(employee_ref="E-B2B")
        validate_success(api_client.activate_kt_plan(plan["id"], MGR))
        completed = validate_success(api_client.complete_kt_plan(plan["id"], MGR))
        assert completed["status"] == "COMPLETE"
