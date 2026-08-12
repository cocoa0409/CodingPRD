"""Employee deactivation cascade, manager reassignment, and per-employee lists."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    ApiErrorId,
    setup_basic_case,
    create_employee,
    create_employee_payload,
    get_case_checkins,
)

HR = TEST_USERS["hr_admin_headers"]


def test_manager_deactivation_two_link_cascade(api):
    """PRD §3.2: "deactivating an `ACTIVE` employee (a repeated deactivation is
    rejected with `ERR_EMPLOYEE_NOT_ACTIVE`) marks every non-terminal case that
    employee manages — any case whose phase is not `COMPLETED`, `WITHDRAWN`,
    `REVOKED`, or `SEPARATED` — with `manager_reassignment_required` true,
    incrementing each such case's `version`; cancels every check-in owned by
    that employee (`owner_employee_id`) in `SCHEDULED` or `MISSED` status on
    those cases, recomputing the affected cases' health; and additionally
    cancels every `SCHEDULED` or `MISSED` check-in where the deactivated
    employee serves as the case's buddy."

    Design: Difficulty/transitive_cascade/manager_deactivation_two_link_cascade
    """
    ctx = setup_basic_case()
    case_id = ctx["case"]["id"]
    mgr_id = ctx["manager"]["id"]

    resp = api.deactivate_employee(mgr_id, HR)
    assert validate_success(resp)["employment_status"] == "INACTIVE"

    case = get_success_data(api.get_onboarding_case(case_id, HR))
    assert case["manager_reassignment_required"] is True
    assert case["phase"] == "PRE_BOARDING"  # phase dimension unaffected

    checkins = get_case_checkins(case_id)
    # Two MANAGER check-ins owned by mgr are cancelled; buddy's check-ins survive.
    mgr_checkins = [c for c in checkins if c["kind"] == "MANAGER"]
    bud_checkins = [c for c in checkins if c["kind"] == "BUDDY"]
    assert all(c["status"] == "CANCELLED" for c in mgr_checkins)
    assert all(c["status"] == "SCHEDULED" for c in bud_checkins)


def test_deactivation_cancels_buddy_owned_checkins(api):
    """PRD §3.2: "additionally cancels every `SCHEDULED` or `MISSED` check-in
    where the deactivated employee serves as the case's buddy."

    Deactivating the buddy cancels the BUDDY-owned check-ins on the case.

    Design: Difficulty/transitive_cascade/manager_deactivation_two_link_cascade
    """
    ctx = setup_basic_case()
    case_id = ctx["case"]["id"]
    bud_id = ctx["buddy"]["id"]

    get_success_data(api.deactivate_employee(bud_id, HR))
    checkins = get_case_checkins(case_id)
    bud_checkins = [c for c in checkins if c["kind"] == "BUDDY"]
    mgr_checkins = [c for c in checkins if c["kind"] == "MANAGER"]
    assert all(c["status"] == "CANCELLED" for c in bud_checkins)
    assert all(c["status"] == "SCHEDULED" for c in mgr_checkins)


def test_deactivate_twice_rejected(api):
    """PRD §3.2: "deactivating an `ACTIVE` employee (a repeated deactivation is
    rejected with `ERR_EMPLOYEE_NOT_ACTIVE`)"

    Design: Corner/validations/deactivate_twice_rejected
    """
    emp = create_employee()
    resp = api.deactivate_employee(emp["id"], HR)
    assert validate_success(resp)["employment_status"] == "INACTIVE"

    resp2 = api.deactivate_employee(emp["id"], HR)
    validate_error(resp2, ApiErrorId.ERR_EMPLOYEE_NOT_ACTIVE)


def test_employee_checkins_subresource_lists_owned(api):
    """PRD §3.2: "Anyone can inspect a given employee's owned check-ins through
    the per-employee check-in list."

    Design: Corner/endpoints/employee_checkins_subresource_lists_owned
    """
    ctx = setup_basic_case()
    mgr_id = ctx["manager"]["id"]
    bud_id = ctx["buddy"]["id"]

    mgr_list = get_success_data(api.list_employee_checkins(mgr_id, HR))
    assert len(mgr_list) == 2
    assert all(c["kind"] == "MANAGER" for c in mgr_list)
    assert all(c["owner_employee_id"] == mgr_id for c in mgr_list)

    bud_list = get_success_data(api.list_employee_checkins(bud_id, HR))
    assert len(bud_list) == 2
    assert all(c["kind"] == "BUDDY" for c in bud_list)


def test_reassign_manager_restores_cadence(api):
    """PRD §3.2: "**Manager reassignment** — performed by an `HRAdmin` supplying
    a `new_manager_id` — swaps in a new hiring manager: the target employee must
    exist and be `ACTIVE` (`ERR_EMPLOYEE_NOT_ACTIVE`), and must differ from the
    case's `buddy_id` (`ERR_DUAL_ROLE_ASSIGNMENT`). The reassignment updates the
    case's `manager_id`, clears `manager_reassignment_required` to false,
    regenerates the future manager check-ins for the new owner according to the
    cadence rule of §3.7 (respecting the same thirty-minute buffer against that
    owner's existing non-cancelled check-ins), and increments the case
    `version`."

    Design: Corner/endpoints/reassign_manager_restores_cadence
    """
    ctx = setup_basic_case()
    case_id = ctx["case"]["id"]
    mgr_id = ctx["manager"]["id"]
    mgr2 = get_success_data(api.create_employee(create_employee_payload(full_name="Mgr2"), HR))

    get_success_data(api.deactivate_employee(mgr_id, HR))
    case_pre = get_success_data(api.get_onboarding_case(case_id, HR))
    assert case_pre["manager_reassignment_required"] is True

    resp = api.reassign_manager(case_id, {"new_manager_id": mgr2["id"]}, HR)
    data = validate_success(resp)
    assert data["manager_reassignment_required"] is False
    assert data["manager_id"] == mgr2["id"]

    # New manager owns 2 regenerated SCHEDULED MANAGER check-ins on canonical dates.
    mgr2_checkins = get_success_data(api.list_employee_checkins(mgr2["id"], HR))
    sched = sorted(c["scheduled_at"] for c in mgr2_checkins if c["status"] == "SCHEDULED")
    assert sched == ["2026-05-05T09:00:00Z", "2026-06-03T09:00:00Z"]
