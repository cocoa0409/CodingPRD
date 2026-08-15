"""Order lifecycle: bounded suspend/resume cycle, termination gating, terminal
lockdown, and illegal early-pipeline transitions."""

from test_helpers import (
    ApiErrorId,
    answer_payload,
    api_client,
    create_order_payload,
    employee_version,
    get_order,
    get_success_data,
    make_open_run,
    notify_order,
    receive_order,
    reject_order_payload,
    resume_order,
    setup_active_order_scenario,
    setup_employer_with_employee,
    suspend_order,
    terminate_employee_payload,
    terminate_order_payload,
    validate_error,
    validate_order,
)
from test_helpers.fixtures import MANAGER, SPECIALIST


class TestSuspendResumeCycle:
    def test_three_suspend_resume_cycles_succeed(self, api):
        """PRD §3.4: "Suspension moves the order to `SUSPENDED`, flips its
        `remit_posture` to `HELD` with the supplied reason recorded, and
        appends an audit entry (action `order.suspend`)."
        PRD §3.4: "a manager resumes a `SUSPENDED` order — provided the
        employee is not terminated — returning it to `ACTIVE`, restoring its
        `remit_posture` to `REMITTING`, clearing its `hold_reason`, and leaving
        the suspension count untouched, since only suspension increments it."

        Design: Difficulty/non_linear_state_machine/order_suspend_resume_cycle_bounded
        """
        base = setup_active_order_scenario(
            order_overrides={"case_number": "CS-11", "amount_value": 10000}
        )
        oid = base["order"]["id"]
        for reason in ("DISPUTED", "DISPUTED", "REFUND_PENDING"):
            suspended = suspend_order(oid, reason)
            assert suspended["processing_status"] == "SUSPENDED"
            assert suspended["remit_posture"] == "HELD"
            assert suspended["hold_reason"] == reason
            resumed = resume_order(oid)
            assert resumed["processing_status"] == "ACTIVE"
            assert resumed["remit_posture"] == "REMITTING"
            assert resumed["hold_reason"] is None

    def test_fourth_suspend_rejected_at_limit(self, api):
        """PRD §3.4: "An order tolerates at most three suspensions over its
        life; a fourth attempt is rejected with `ERR_SUSPEND_LIMIT_EXCEEDED`
        (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/order_suspend_resume_cycle_bounded
        """
        base = setup_active_order_scenario(
            order_overrides={"case_number": "CS-11", "amount_value": 10000}
        )
        oid = base["order"]["id"]
        for reason in ("DISPUTED", "DISPUTED", "REFUND_PENDING"):
            suspend_order(oid, reason)
            resume_order(oid)
        resp = api_client.suspend_order(oid, {"hold_reason": "DISPUTED"}, MANAGER)
        validate_error(resp, ApiErrorId.ERR_SUSPEND_LIMIT_EXCEEDED)
        order = get_order(oid)
        assert order["processing_status"] == "ACTIVE"
        assert order["remit_posture"] == "REMITTING"


class TestEmployeeTerminationGates:
    def _setup_notified_order_then_terminate_employee(self):
        base = setup_employer_with_employee()
        ee_id = base["employee"]["id"]
        order = receive_order(ee_id, base["authority"]["id"], case_number="CS-H")
        validate_order(order["id"])
        notify_order(order["id"])
        get_success_data(
            api_client.terminate_employee(
                ee_id, terminate_employee_payload("2026-08-10"), MANAGER
            )
        )
        return base, order

    def test_activation_blocked_by_employee_termination(self, api):
        """PRD §3.4: "The specialist activates an order only from
        `EMPLOYEE_NOTIFIED`, only while `notification_sent_at` is set, and only
        while the employee remains unterminated
        (`ERR_EMPLOYEE_TERMINATED_INELIGIBLE` otherwise); the order arrives at
        `ACTIVE` and an audit entry (action `order.activate`) is appended."
        PRD §3.2: "a set `termination_date` immediately bars three operations
        against that employee: receiving a new order, activating an order, and
        adding a pay statement for the employee to a run. All three are
        rejected with `ERR_EMPLOYEE_TERMINATED_INELIGIBLE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/order_activation_gated_by_employee_termination
        """
        base, order = self._setup_notified_order_then_terminate_employee()
        resp = api_client.activate_order(order["id"], SPECIALIST)
        validate_error(resp, ApiErrorId.ERR_EMPLOYEE_TERMINATED_INELIGIBLE)
        assert get_order(order["id"])["processing_status"] == "EMPLOYEE_NOTIFIED"
        # The same gate bars statement creation for the terminated employee.
        run = make_open_run(base["employer"]["id"])
        resp2 = api_client.create_statement(
            run["id"],
            {"employee_id": base["employee"]["id"],
             "gross_earnings_cents": 100000,
             "mandatory_deductions_cents": 20000},
            SPECIALIST,
        )
        validate_error(resp2, ApiErrorId.ERR_EMPLOYEE_TERMINATED_INELIGIBLE)

    def test_intake_blocked_by_employee_termination(self, api):
        """PRD §3.2: "Termination does not, by itself, terminate the employee's
        garnishment orders — each order requires its own explicit termination —
        but a set `termination_date` immediately bars three operations against
        that employee: receiving a new order, activating an order, and adding a
        pay statement for the employee to a run. All three are rejected with
        `ERR_EMPLOYEE_TERMINATED_INELIGIBLE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/order_activation_gated_by_employee_termination
        """
        base, order = self._setup_notified_order_then_terminate_employee()
        ee_id = base["employee"]["id"]
        payload = create_order_payload(
            base["authority"]["id"], employee_version(ee_id), case_number="CS-H2"
        )
        resp = api_client.create_order(ee_id, payload, SPECIALIST)
        validate_error(resp, ApiErrorId.ERR_EMPLOYEE_TERMINATED_INELIGIBLE)


class TestTerminalLockdown:
    def test_rejected_order_locks_all_actions(self, api):
        """PRD §2.9: "then state legality — a transition attempted from an
        illegal state, including any mutation aimed at a terminal-state
        resource, is rejected with `ERR_INVALID_STATE` (HTTP 409)."
        PRD §3.4: "The order's `processing_status` now walks the legal pipeline
        — `RECEIVED`, `VALIDATED`, `EMPLOYEE_NOTIFIED`, `ACTIVE`,
        `ANSWER_FILED`, `SUSPENDED`, and the terminal `SATISFIED`,
        `TERMINATED`, and `REJECTED`"
        From terminal REJECTED, validate/notify/activate/suspend/answer/
        terminate are all rejected.

        Design: Corner/state_machines/order_terminal_lockdown_rejected
        """
        base = setup_employer_with_employee()
        order = receive_order(
            base["employee"]["id"], base["authority"]["id"], case_number="CS-R"
        )
        rejected = get_success_data(
            api_client.reject_order(order["id"], reject_order_payload(), SPECIALIST)
        )
        assert rejected["processing_status"] == "REJECTED"
        assert rejected["remit_posture"] == "CLOSED"

        oid = order["id"]
        for resp in (
            api_client.validate_order(oid, SPECIALIST),
            api_client.notify_order(oid, SPECIALIST),
            api_client.activate_order(oid, SPECIALIST),
            api_client.suspend_order(oid, {"hold_reason": "DISPUTED"}, MANAGER),
            api_client.answer_order(oid, answer_payload(), MANAGER),
            api_client.terminate_order(oid, terminate_order_payload(), MANAGER),
        ):
            validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_order(oid)["processing_status"] == "REJECTED"


class TestInvalidEarlyTransition:
    def test_notify_before_validate_rejected(self, api):
        """PRD §3.4: "When the `payroll_specialist` records that notification,
        the order moves from `VALIDATED` to `EMPLOYEE_NOTIFIED`, its
        `notification_sent_at` is stamped from the logical clock, and an audit
        entry (action `order.notify`) is appended."
        Notification on a RECEIVED (never validated) order is an invalid
        transition and must be rejected with ERR_INVALID_STATE.

        Design: Corner/state_machines/notify_before_validate_rejected
        """
        base = setup_employer_with_employee()
        order = receive_order(
            base["employee"]["id"], base["authority"]["id"], case_number="CS-NV"
        )
        resp = api_client.notify_order(order["id"], SPECIALIST)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_order(order["id"])["processing_status"] == "RECEIVED"
