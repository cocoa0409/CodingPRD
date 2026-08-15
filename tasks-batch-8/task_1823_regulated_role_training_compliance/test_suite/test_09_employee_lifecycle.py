"""Employee lifecycle: termination cascade, manual assignment gates, leave windows."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_requirement,
    create_active_curriculum,
    create_employee,
    create_leave,
    create_regulator,
    create_role,
    create_role_change,
    find_attestation,
    get_role_change_data,
    get_success_data,
    list_completions,
    open_campaign,
    create_campaign,
    set_clock,
    setup_employee_with_assignment,
    submit_completion,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories

ADMIN = TEST_USERS["compliance_admin_headers"]
HR = TEST_USERS["hr_admin_headers"]


def test_terminate_cascades_to_assignments_attestations_and_role_changes(api):
    """PRD §3.3: "moves every non-terminal assignment to `CANCELLED` and voids
    its `PENDING_REVIEW` completion records; moves every `SCHEDULED` role change
    to `CANCELLED`; expires every `PENDING`, `BLOCKED`, or `EXCEPTION_PENDING`
    attestation into `EXPIRED`, auto-denying their `REQUESTED` exceptions with
    the `decision_note` string `AUTO_DENIED_AT_CLOSE`; and forces
    `compliance_blocked` to false while leaving `verified_completed_count`
    unchanged."

    Design: Corner/state_machines/terminate_cascades_to_assignments_attestations_and_role_changes
    """
    ctx = setup_employee_with_assignment("TRM")
    reg, emp, asg = ctx["regulator"], ctx["employee"], ctx["assignment"]
    submit_completion(asg["id"], emp["id"], score_pct=90)

    camp = create_campaign(reg["id"], statement_version="STMT-TRM")
    open_campaign(camp["id"])
    att = find_attestation(emp["id"])
    assert att["status"] == "PENDING"

    r2 = create_role(code="R-TRM2", name="TRM Role Two")
    rc = create_role_change(emp["id"], r2["id"], effective_at="2026-08-10T00:00:00Z")
    assert rc["status"] == "SCHEDULED"

    terminated = get_success_data(api.terminate_employee(emp["id"], HR), 200)
    assert terminated["status"] == "TERMINATED"
    assert terminated["compliance_blocked"] is False

    after = get_success_data(api.get_assignment(asg["id"], ADMIN), 200)
    assert after["progress_status"] == "CANCELLED"
    records, _ = list_completions(asg["id"])
    assert records[0]["review_status"] == "VOIDED"

    attestations, _ = validate_paginated(api.list_employee_attestations(emp["id"], ADMIN))
    assert attestations[0]["status"] == "EXPIRED"

    assert get_role_change_data(rc["id"])["status"] == "CANCELLED"


def test_manual_assignment_on_terminated_employee_rejected(api):
    """PRD §3.4: "Manual creation against a `TERMINATED` employee fails with
    `ERR_EMPLOYEE_TERMINATED`."

    Design: Corner/validations/manual_assignment_on_terminated_employee_rejected
    """
    ctx = setup_employee_with_assignment("TA")
    emp, asg, req = ctx["employee"], ctx["assignment"], ctx["requirement"]
    get_success_data(api.cancel_assignment(asg["id"], ADMIN), 200)
    get_success_data(api.terminate_employee(emp["id"], HR), 200)

    resp = api.create_manual_assignment(
        emp["id"], factories.create_manual_assignment_payload(req["id"]), ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_EMPLOYEE_TERMINATED.value)


def test_manual_assignment_duplicate_rejected(api):
    """PRD §3.4: "no non-terminal assignment may already exist for that employee
    and requirement (`ERR_DUPLICATE_ACTIVE_ASSIGNMENT`)"

    Design: Corner/validations/manual_assignment_duplicate_rejected
    """
    ctx = setup_employee_with_assignment("MD")
    emp, req = ctx["employee"], ctx["requirement"]
    resp = api.create_manual_assignment(
        emp["id"], factories.create_manual_assignment_payload(req["id"]), ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_ASSIGNMENT.value)


def test_manual_assignment_to_retired_requirement_rejected(api):
    """PRD §3.4: "the requirement must be `ACTIVE` (`ERR_REQUIREMENT_NOT_ACTIVE`)"
    PRD §3.2: "Retiring a requirement — again only while `ACTIVE`, else
    `ERR_INVALID_STATE` — leaves existing assignments running untouched but
    excludes the requirement from all future sweeps, recurrence creations, and
    role-change assignment."

    Design: Corner/validations/manual_assignment_to_retired_requirement_rejected
    """
    set_clock("2026-08-03T09:00:00Z")
    reg = create_regulator(code="REG-RTR", name="RTR Regulator")
    cur = create_active_curriculum(reg["id"], code="CUR-RTR", title="RTR Course")
    role = create_role(code="R-RTR", name="RTR Role")
    req = add_requirement(role["id"], cur["id"])
    get_success_data(api.retire_requirement(req["id"], ADMIN), 200)
    emp = create_employee("E-RTR-1", role["id"], full_name="RTR Emp")

    resp = api.create_manual_assignment(
        emp["id"], factories.create_manual_assignment_payload(req["id"]), ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_REQUIREMENT_NOT_ACTIVE.value)


def test_manual_assignment_cross_role_rejected(api):
    """PRD §3.4: "the requirement's role must equal the employee's
    `current_role_id` (`ERR_REQUIREMENT_ROLE_MISMATCH`)"

    Design: Corner/validations/manual_assignment_cross_role_rejected
    """
    set_clock("2026-08-03T09:00:00Z")
    reg = create_regulator(code="REG-XR", name="XR Regulator")
    cur = create_active_curriculum(reg["id"], code="CUR-XR", title="XR Course")
    r1 = create_role(code="R-XR1", name="XR One")
    r2 = create_role(code="R-XR2", name="XR Two")
    req2 = add_requirement(r2["id"], cur["id"])
    emp = create_employee("E-XR-1", r1["id"], full_name="XR Emp")

    resp = api.create_manual_assignment(
        emp["id"], factories.create_manual_assignment_payload(req2["id"]), ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_REQUIREMENT_ROLE_MISMATCH.value)


class TestLeaveWindowBuffer:
    def _setup_on_leave_employee(self, api):
        set_clock("2026-08-03T09:00:00Z")
        role = create_role(code="R-L8B", name="L8B Role")
        emp = create_employee("E-L8B-1", role["id"], full_name="L8B Emp")
        create_leave(
            emp["id"], start_date="2026-08-03T00:00:00Z",
            end_date="2026-08-07T23:59:59Z", reason="Medical",
        )
        return emp

    def test_leave_starting_next_day_violates_buffer(self, api):
        """PRD §3.3: "Leave windows for the same employee may not nearly-touch:
        a new leave conflicts with an existing one whenever the new leave's
        start falls on or before one day after the existing leave's end *and*
        the existing leave's start falls on or before one day after the new
        leave's end — closed intervals plus a mandatory one-day buffer — and
        such a conflict is rejected with `ERR_LEAVE_OVERLAP`."
        PRD §3.3: "When a leave's window covers the current instant at creation,
        the employee moves from `ACTIVE` to `ON_LEAVE` and every non-terminal
        assignment they hold has its `deadline_status` frozen to `FROZEN`."

        Design: Difficulty/resource_temporal_overlap/leave_closed_interval_buffer_gap
        """
        emp = self._setup_on_leave_employee(api)
        employee = get_success_data(api.get_employee(emp["id"], ADMIN), 200)
        assert employee["status"] == "ON_LEAVE", "L1 covers the clock at creation"

        resp = api.create_leave(
            emp["id"],
            factories.create_leave_payload(
                start_date="2026-08-08T00:00:00Z", end_date="2026-08-10T23:59:59Z",
                reason="Extension",
            ),
            HR,
        )
        validate_error(resp, ApiErrorId.ERR_LEAVE_OVERLAP.value)

    def test_leave_with_full_day_gap_accepted(self, api):
        """PRD §3.3: "Leave windows for the same employee may not nearly-touch:
        a new leave conflicts with an existing one whenever the new leave's
        start falls on or before one day after the existing leave's end *and*
        the existing leave's start falls on or before one day after the new
        leave's end — closed intervals plus a mandatory one-day buffer — and
        such a conflict is rejected with `ERR_LEAVE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/leave_closed_interval_buffer_gap
        """
        emp = self._setup_on_leave_employee(api)
        resp = api.create_leave(
            emp["id"],
            factories.create_leave_payload(
                start_date="2026-08-09T00:00:00Z", end_date="2026-08-12T23:59:59Z",
                reason="Extension 2",
            ),
            HR,
        )
        validate_success(resp, 201)

        _, meta = validate_paginated(api.list_leaves(emp["id"], ADMIN))
        assert meta["total_count"] == 2
