"""State machine legality, terminal lockdown, idempotency, ordering gates.

Covers queue-B corner instances under `state_machines`.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_error_is_one_of,
    get_success_data,
    ApiErrorId,
    create_case,
    create_and_approve_case,
    create_revocation_task,
    create_asset_item,
    create_case_with_statement,
    make_task_ready,
    execute_task,
    verify_task,
    drive_case_to_payroll_pending,
    drive_case_to_clearance,
    drive_case_to_ready_to_close,
    set_clock,
    close_case,
    HR_INTAKE,
    HR_APPROVER,
    IT_OP,
    IT_VER,
    IT_MGR,
    CLERK,
    PAYROLL_CALC,
    PAYROLL_APPROVER,
    MGR,
    BEN_ADMIN,
    HR_REVIEWER,
    HR_DIRECTOR,
)


class TestCaseStateLegality:
    def test_case_close_from_intake_rejected(self):
        """PRD §3.7: "An `HRPartner` closes a `READY_TO_CLOSE` case" — closing
        from `INTAKE` is not a from-state the close transition allows.
        PRD §2.6: "State legality — the target resource is in a from-state the
        requested transition allows, including terminal-state lockdown and
        repeated-trigger attempts; otherwise `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/case_close_from_intake_rejected
        """
        case = create_case(employee_ref="E-SM1")
        resp = api_client.close_case(
            case["id"],
            {"expected_offboarding_case_version": case["version"]},
            HR_APPROVER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_case_terminal_lockdown_closed(self):
        """PRD §3.7: "`CLOSED` and `VOIDED` are the case's terminal states, and
        operations attempted against either are rejected with `ERR_CASE_TERMINAL`."
        PRD §3.1: "A voided case is terminal."

        Design: Corner/state_machines/case_terminal_lockdown_closed
        """
        artifacts = drive_case_to_ready_to_close(employee_ref="E-SM2")
        case = artifacts["case"]
        close_resp = close_case(case["id"], case["version"])
        closed = validate_success(close_resp)
        assert closed["status"] == "CLOSED"

        # Any further transition attempt is rejected.
        void_resp = api_client.void_case(
            case["id"], {"void_reason": "late change"}, HR_APPROVER
        )
        validate_error_is_one_of(
            void_resp, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_CASE_TERMINAL]
        )


class TestRevocationTaskIdempotency:
    def test_double_execute_second_call_rejected(self):
        """PRD §2.6: "State legality — ... including terminal-state lockdown and
        repeated-trigger attempts; otherwise `ERR_INVALID_STATE` (HTTP 409)."
        PRD §3.2: "An `ITOperator` then executes a ready task."

        Design: Corner/state_machines/double_execute_second_call_rejected
        """
        case = create_and_approve_case(employee_ref="E-SM3")
        task = make_task_ready(case["id"], system_name="EMAIL", sequence_rank=1)
        execute_task(task["id"], outcome="SUCCESS")
        # second execute on EXECUTED task
        resp = api_client.execute_revocation_task(task["id"], {"outcome": "SUCCESS"}, IT_OP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestRevocationOrderingGate:
    def test_revoke_ordering_gate_blocks_higher_rank(self):
        """PRD §3.2: "A pending task becomes executable when the logical clock
        reaches its `scheduled_at` and every sibling with a lower `sequence_rank`
        is already terminal — `VERIFIED` or `WAIVED`." PRD §2.6: "Revocation
        ordering gate — lower-ranked revocation siblings are terminal, and waiver
        is only attempted after the retry cap; otherwise `ERR_SEQUENCE_GATE`
        (HTTP 422)."

        Design: Corner/state_machines/revoke_ordering_gate_blocks_higher_rank
        """
        case = create_and_approve_case(employee_ref="E-SM4")
        create_revocation_task(case["id"], system_name="EMAIL", sequence_rank=1)
        task_b = create_revocation_task(case["id"], system_name="VPN", sequence_rank=2)
        # Advance clock past both schedules. Rank 1 releases; rank 2 stays gated.
        set_clock("2026-08-10T17:00:00Z")
        refreshed_b = get_success_data(api_client.get_revocation_task(task_b["id"], IT_OP))
        # The rank-2 task must NOT be READY while rank-1 is non-terminal.
        assert refreshed_b["status"] == "PENDING", (
            "rank-2 task must not become READY while rank-1 sibling is non-terminal"
        )
        # Direct execute attempt on the non-READY rank-2 task is rejected.
        resp = api_client.execute_revocation_task(task_b["id"], {"outcome": "SUCCESS"}, IT_OP)
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_SEQUENCE_GATE, ApiErrorId.ERR_INVALID_STATE]
        )


class TestRevocationWaiverGate:
    def test_waive_before_retry_cap_rejected(self):
        """PRD §3.2: "waiver attempted before the retry cap is reached is
        rejected with `ERR_SEQUENCE_GATE`, as is any execution attempt while a
        lower-ranked sibling is not yet terminal."

        Design: Corner/state_machines/waive_before_retry_cap_rejected
        """
        case = create_and_approve_case(employee_ref="E-SM5")
        task = make_task_ready(case["id"], system_name="EMAIL", sequence_rank=1)
        execute_task(task["id"], outcome="FAILED", failure_reason="first failure")
        # retry_count is 0 — waiver must be rejected
        resp = api_client.waive_revocation_task(
            task["id"], {"waive_reason": "premature"}, IT_MGR
        )
        validate_error(resp, ApiErrorId.ERR_SEQUENCE_GATE, expected_status=422)


class TestRevocationRetryCap:
    def test_revoke_retry_cap_exceeded(self):
        """PRD §3.2: "Retrying is refused once `retry_count` has reached the cap
        of three, rejected with `ERR_RETRY_CAP_EXCEEDED`."

        Design: Corner/state_machines/revoke_retry_cap_exceeded
        """
        case = create_and_approve_case(employee_ref="E-SM6")
        task = make_task_ready(case["id"], system_name="EMAIL", sequence_rank=1)
        # Cycle 1: fail + retry (retry_count becomes 1)
        execute_task(task["id"], outcome="FAILED", failure_reason="f1")
        get_success_data(api_client.retry_revocation_task(task["id"], IT_OP))
        set_clock("2026-08-10T18:01:00Z")
        # Cycle 2
        execute_task(task["id"], outcome="FAILED", failure_reason="f2")
        get_success_data(api_client.retry_revocation_task(task["id"], IT_OP))
        set_clock("2026-08-10T20:01:00Z")
        # Cycle 3
        execute_task(task["id"], outcome="FAILED", failure_reason="f3")
        get_success_data(api_client.retry_revocation_task(task["id"], IT_OP))
        set_clock("2026-08-11T00:01:00Z")
        # Final fail at retry_count == 3
        execute_task(task["id"], outcome="FAILED", failure_reason="f4")
        # Fourth retry attempt is rejected at the cap.
        resp = api_client.retry_revocation_task(task["id"], IT_OP)
        validate_error(resp, ApiErrorId.ERR_RETRY_CAP_EXCEEDED, expected_status=422)


class TestBenefitsRequeueCap:
    def test_benefits_requeue_cap_then_escalate(self):
        """PRD §3.6: "a requeue at the cap is rejected with
        `ERR_RETRY_CAP_EXCEEDED`; at the cap the administrator instead escalates
        the notice, landing it in `ESCALATED`."

        Design: Corner/state_machines/benefits_requeue_cap_then_escalate
        """
        case, _task = drive_case_to_payroll_pending(employee_ref="E-SM7")
        notice = get_success_data(
            api_client.create_benefits_notice(
                {"offboarding_case_id": case["id"], "notice_kind": "COBRA_ELECTION"},
                BEN_ADMIN,
            )
        )
        # Notice was created BEFORE payroll stage? drive_case_to_payroll_pending
        # already reached PAYROLL_PENDING, so creating a notice now leaves it DRAFT
        # without an automatic queue. Re-drive the cascade by going through the
        # documented path: notices created pre-PAYROLL_PENDING auto-queue. Here the
        # notice was created post-PAYROLL_PENDING, so we exercise a case variant
        # that goes through the queue path in a fresh scenario.
        # Use a fresh case where the notice is created BEFORE the cascade.
        case2 = create_and_approve_case(employee_ref="E-SM7B")
        notice2 = get_success_data(
            api_client.create_benefits_notice(
                {"offboarding_case_id": case2["id"], "notice_kind": "COBRA_ELECTION"},
                BEN_ADMIN,
            )
        )
        # Drive to PAYROLL_PENDING which cascades notice DRAFT -> QUEUED.
        task2 = create_revocation_task(case2["id"], system_name="EMAIL", sequence_rank=1)
        set_clock("2026-08-10T17:00:00Z")
        execute_task(task2["id"], outcome="SUCCESS")
        verify_task(task2["id"], outcome="VERIFIED")
        notice2_queued = get_success_data(api_client.get_benefits_notice(notice2["id"], BEN_ADMIN))
        assert notice2_queued["status"] == "QUEUED"

        # SENT -> FAILED -> requeue -> SENT -> FAILED
        get_success_data(api_client.send_benefits_notice(notice2["id"], BEN_ADMIN))
        get_success_data(api_client.report_failure_benefits_notice(notice2["id"], BEN_ADMIN))
        get_success_data(api_client.requeue_benefits_notice(notice2["id"], BEN_ADMIN))
        get_success_data(api_client.send_benefits_notice(notice2["id"], BEN_ADMIN))
        get_success_data(api_client.report_failure_benefits_notice(notice2["id"], BEN_ADMIN))
        # Now failure_count == 2 — requeue at cap is rejected
        resp = api_client.requeue_benefits_notice(notice2["id"], BEN_ADMIN)
        validate_error(resp, ApiErrorId.ERR_RETRY_CAP_EXCEEDED, expected_status=422)
        # Escalate at cap is allowed
        esc = validate_success(api_client.escalate_benefits_notice(notice2["id"], BEN_ADMIN))
        assert esc["status"] == "ESCALATED"


class TestCaseVoidCascade:
    def test_case_void_from_approved_cascades_children(self):
        """PRD §3.1: "Voiding from `INTAKE` or `APPROVED` requires a
        `void_reason` and cascades: every revocation task still `PENDING`,
        `READY`, or `RETRY_SCHEDULED` becomes `WAIVED`; every asset item still
        `TRACKED` becomes `WAIVED`; a statement still `DRAFT` or `CALCULATED`
        becomes `VOIDED`."

        Design: Corner/state_machines/case_void_from_approved_cascades_children
        """
        case = create_and_approve_case(employee_ref="E-SM8")
        task = create_revocation_task(case["id"], system_name="EMAIL", sequence_rank=1)
        item = create_asset_item(
            case["id"], asset_tag="K1", asset_kind="KEYCARD", replacement_cost_cents=500,
            issued_date="2026-01-01T00:00:00Z",
        )
        stmts = get_success_data(api_client.list_case_statements(case["id"], PAYROLL_CALC))
        stmt = stmts[0]

        resp = api_client.void_case(
            case["id"], {"void_reason": "duplicate intake"}, HR_APPROVER
        )
        voided = validate_success(resp)
        assert voided["status"] == "VOIDED"

        task_after = get_success_data(api_client.get_revocation_task(task["id"], IT_OP))
        item_after = get_success_data(api_client.get_asset_item(item["id"], CLERK))
        stmt_after = get_success_data(api_client.get_statement(stmt["id"], PAYROLL_CALC))
        assert task_after["status"] == "WAIVED"
        assert item_after["status"] == "WAIVED"
        assert stmt_after["status"] == "VOIDED"

    def test_case_void_blocked_once_revocation_executed(self):
        """PRD §3.1: "Once revocation has actually begun — any task `EXECUTED`
        or `VERIFIED` — an approved case can no longer be voided; the attempt is
        rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/case_void_blocked_once_revocation_executed
        """
        case = create_and_approve_case(employee_ref="E-SM9")
        task = make_task_ready(case["id"], system_name="EMAIL", sequence_rank=1)
        execute_task(task["id"], outcome="SUCCESS")
        resp = api_client.void_case(case["id"], {"void_reason": "too late"}, HR_APPROVER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestKTPlanAutoComplete:
    def test_kt_plan_zero_required_sessions_does_not_auto_complete_on_session(self):
        """PRD §3.5: "A plan requiring zero sessions never auto-completes; the
        `Manager` completes it explicitly." The auto-created plan has
        `required_session_count == 0`, so completing a session under it must not
        flip the plan to `COMPLETE`.

        Design: Corner/state_machines/kt_plan_auto_completes_on_session_threshold
        """
        from test_helpers import create_case_with_plan, create_kt_session
        case, plan = create_case_with_plan(employee_ref="E-SM10")
        # Plan was auto-created with required_session_count == 0 by approval.
        assert plan["required_session_count"] == 0
        get_success_data(api_client.activate_kt_plan(plan["id"], MGR))
        session = create_kt_session(plan["id"], topic="t1")
        # Drive clock past session start so completion is legal.
        set_clock("2026-08-05T10:30:00Z")
        completed = validate_success(api_client.complete_kt_session(session["id"], MGR))
        assert completed["status"] == "COMPLETED"
        refreshed = get_success_data(api_client.get_kt_plan(plan["id"], MGR))
        assert refreshed["completed_session_count"] == 1
        # Plan must NOT auto-complete when required_session_count == 0.
        assert refreshed["status"] == "ACTIVE"
