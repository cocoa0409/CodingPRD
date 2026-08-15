"""Employee roster administration (PRD §3.1): creation defaults, uniqueness,
the manager filter, lifecycle terminal lockdown, and role boundaries."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    validate_success,
    validate_error,
    validate_paginated,
    make_employee_headers,
    assert_employee,
    assert_instant_equals,
    make_employee,
    set_employee_status,
    create_employee_payload,
    create_team_payload,
)

ADMIN = TEST_USERS["admin_headers"]


def test_employee_creation_defaults_and_immediate_read(api):
    """PRD §3.1: "An `HRServicesAdmin` enrolls an employee with an `employee_number`
    (the unique HRIS number; a duplicate is rejected with
    `ERR_DUPLICATE_EMPLOYEE_NUMBER`), a `full_name`, a work `email`, and optionally a
    `manager_id` pointing at another employee — null at the top of the management
    tree, and load-bearing later because the manager of record is one of the two
    fraud-verification channels for data changes. An initial `status` may be supplied
    but defaults to `ACTIVE`."
    PRD §3.1: "`has_pending_dcr`, initially false, is true exactly while any data
    change request of the employee sits in `PENDING_VERIFICATION` or
    `PENDING_APPROVAL`, and is maintained on request creation, approval, rejection,
    and cancellation — every flip bumps the employee's `version`; `open_ticket_count`
    is the computed count of the employee's tickets in `NEW`, `TRIAGED`,
    `IN_PROGRESS`, `PENDING_EMPLOYEE`, `ESCALATED`, or `REOPENED`."
    PRD §2.5: "Nothing in this API consults the wall clock. All deadlines, expiries,
    and scheduled transitions evaluate against a server-side logical clock whose
    startup default — before any explicit set — is exactly 2026-08-01T00:00:00Z."

    Design: Corner/entities/employee_creation_defaults_and_immediate_read
    """
    created = validate_success(
        api.create_employee(
            create_employee_payload(employee_number="E001", full_name="Nia New",
                                    email="nia@x.com"),
            ADMIN,
        ),
        expected_status=201,
    )
    assert_employee(created)

    # Read-after-write is immediately consistent.
    data = validate_success(api.get_employee(created["id"], ADMIN))
    assert_employee(data)
    assert data["id"] == created["id"]
    assert data["status"] == "ACTIVE"
    assert data["has_pending_dcr"] is False
    assert data["open_ticket_count"] == 0
    assert_instant_equals(data["created_at"], "2026-08-01T00:00:00Z")


def test_employee_duplicate_number_rejected(api):
    """PRD §3.1: "An `HRServicesAdmin` enrolls an employee with an `employee_number`
    (the unique HRIS number; a duplicate is rejected with
    `ERR_DUPLICATE_EMPLOYEE_NUMBER`), a `full_name`, a work `email`, and optionally a
    `manager_id` pointing at another employee — null at the top of the management
    tree, and load-bearing later because the manager of record is one of the two
    fraud-verification channels for data changes."

    Design: Corner/entities/employee_duplicate_number_rejected
    """
    first = create_employee_payload(employee_number="E002", full_name="First", email="f@x.com")
    validate_success(api.create_employee(first, ADMIN), expected_status=201)

    second = create_employee_payload(employee_number="E002", full_name="Second", email="s@x.com")
    resp = api.create_employee(second, ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMPLOYEE_NUMBER.value)


def test_employee_manager_filter_returns_direct_reports(api):
    """PRD §3.1: "The employee list can be narrowed with the `status` and
    `manager_id` filters, and reading a single employee is available to staff and —
    for their own record only — to the employee."

    Design: Corner/entities/employee_manager_fk_reverse_list
    """
    manager = make_employee(employee_number="E003", full_name="Maya Mgr", email="maya@x.com")
    report = make_employee(manager_id=manager["id"], employee_number="E004",
                           full_name="Ray Report", email="ray@x.com")

    data, meta = validate_paginated(
        api.list_employees(ADMIN, params={"manager_id": manager["id"]})
    )
    assert meta["total_count"] == 1, f"expected exactly one direct report, got {meta['total_count']}"
    assert len(data) == 1
    assert data[0]["id"] == report["id"]
    assert data[0]["manager_id"] == manager["id"]


def test_terminated_employee_cannot_leave_terminal_state(api):
    """PRD §3.1: "The employee lifecycle is a small machine on `status`: `ACTIVE`
    and `ON_LEAVE` transition back and forth under an `HRServicesAdmin`, and either
    may move to `TERMINATED`, which is terminal — any attempt to leave `TERMINATED`
    fails with `ERR_EMPLOYEE_INVALID_STATE`."

    Design: Corner/state_machines/employee_terminated_is_terminal
    """
    employee = make_employee(employee_number="E108", full_name="Term Tina", email="tina@x.com")
    terminated = set_employee_status(employee["id"], "TERMINATED")
    assert terminated["status"] == "TERMINATED"

    resp = api.set_employee_status(employee["id"], {"status": "ACTIVE"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_EMPLOYEE_INVALID_STATE.value)

    data = validate_success(api.get_employee(employee["id"], ADMIN))
    assert data["status"] == "TERMINATED", "status must remain TERMINATED after a rejected transition"


def test_employee_role_cannot_create_team(api):
    """PRD §2.1: "A caller whose role is not listed for the endpoint, or who
    violates a record-level ownership scope, is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."
    PRD §2.1: "An `HRServicesAdmin` administers the platform: creating employees,
    teams, agents, categories, and SLA policies, driving employee lifecycle
    transitions, assigning tickets, and setting the logical clock."

    Design: Corner/rbac/employee_cannot_create_team
    """
    employee = make_employee(employee_number="E501", full_name="Role Rob", email="rob@x.com")

    resp = api.create_team(
        create_team_payload(name="Nope Team"), make_employee_headers(employee["id"])
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    data, meta = validate_paginated(api.list_teams(ADMIN))
    assert meta["total_count"] == 0, "the team must not have been created"
