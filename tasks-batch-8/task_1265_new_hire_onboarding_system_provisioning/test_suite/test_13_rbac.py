"""Role-based access control: peer-role isolation and ownership+kind binding."""
from test_helpers import (
    api_client,
    validate_error,
    get_success_data,
    TEST_USERS,
    ApiErrorId,
    setup_basic_case,
    setup_case_in_provisioning,
    setup_in_progress,
    create_employee,
    create_employee_payload,
    get_case_tasks,
    get_case_checkins,
    get_case_cycles,
    create_handoff_for_case,
    make_buddy_headers,
    make_new_hire_headers,
    make_hiring_manager_headers,
)

HR = TEST_USERS["hr_admin_headers"]
IT = TEST_USERS["it_provisioner_headers"]
PAYROLL = TEST_USERS["payroll_ops_headers"]


def test_it_provisioner_cannot_submit_order(api):
    """PRD §4: "POST `/api/provisioning-orders/{id}/submit` ... Authorized
    Role(s): HRAdmin"

    Design: Corner/rbac/it_provisioner_cannot_submit_order
    """
    ctx = setup_case_in_provisioning()
    order = ctx["order"]
    resp = api.submit_provisioning_order(order["id"], IT)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_payroll_ops_cannot_transmit_handoff(api):
    """PRD §4: "POST `/api/payroll-handoffs/{id}/transmit` ... Authorized
    Role(s): HRAdmin"

    Design: Corner/rbac/payroll_ops_cannot_transmit_handoff
    """
    ctx = setup_in_progress()
    case_id = ctx["case"]["id"]
    case = get_success_data(api.get_onboarding_case(case_id, HR))
    handoff = create_handoff_for_case(case_id, case["version"])
    resp = api.transmit_payroll_handoff(handoff["id"], PAYROLL)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_newhire_cannot_waive_task(api):
    """PRD §4: "POST `/api/onboarding-tasks/{id}/waive` ... Authorized Role(s):
    HRAdmin"

    Design: Corner/rbac/newhire_cannot_waive_task
    """
    ctx = setup_basic_case()
    case_id = ctx["case"]["id"]
    tasks = get_case_tasks(case_id)
    t3 = next(t for t in tasks if not t["is_required"])
    nh = make_new_hire_headers(ctx["new_hire"]["id"])
    resp = api.waive_task(t3["id"], nh)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_buddy_cannot_complete_manager_kind_checkin(api):
    """PRD §3.7: "Completion belongs to the check-in's owner, acting in the role
    matching its kind — a `Buddy` for `BUDDY` check-ins, a `HiringManager` for
    `MANAGER` ones — and a caller whose `X-User-ID` differs from the check-in's
    `owner_employee_id` is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/buddy_cannot_complete_manager_kind_checkin
    """
    ctx = setup_basic_case()
    case_id = ctx["case"]["id"]
    checkins = get_case_checkins(case_id)
    c_m1 = next(c for c in checkins if c["kind"] == "MANAGER")
    # Buddy (wrong kind + wrong owner) attempts completion.
    buddy = make_buddy_headers(ctx["buddy"]["id"])
    resp = api.complete_check_in(c_m1["id"], {"notes": "poach"}, buddy)
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


def test_manager_cannot_evaluate_unowned_case(api):
    """PRD §3.8: "Evaluation belongs to the hiring manager: the caller's
    `X-User-ID` must equal the owning case's `manager_id`
    (`ERR_NOT_RESOURCE_OWNER`)"

    Design: Corner/rbac/manager_cannot_evaluate_unowned_case
    """
    ctx = setup_in_progress()
    case_id = ctx["case"]["id"]
    # Advance clock so cycle 1 is EVALUATION_DUE.
    get_success_data(api.set_current_utc({"to_iso8601": "2026-08-03T00:00:00Z"}, HR))
    cy1 = get_case_cycles(case_id)[0]

    mgr2 = get_success_data(api.create_employee(create_employee_payload(full_name="Mgr2"), HR))
    other_mgr = make_hiring_manager_headers(mgr2["id"])
    resp = api.evaluate_probation_cycle(cy1["id"], {"outcome": "PASS", "rating": 4}, other_mgr)
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
