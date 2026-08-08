"""Case assignment and caseload conservation, the one-non-terminal-case constraint,
staff-role and caseload-cap gates, and the resolve-sweeps-referrals cascade."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    fixtures as fx, TEST_USERS,
)

ADMIN = TEST_USERS["administrator_headers"]


def _two_managers_case_assigned_to_first(api):
    school = fx.make_school(api)
    staff1 = fx.make_staff(api, school["id"], role_type="CASE_MANAGER", full_name="Mgr One")
    staff2 = fx.make_staff(api, school["id"], role_type="CASE_MANAGER", full_name="Mgr Two")
    student = fx.make_student(api, school["id"], grade_level=9)
    case = fx.make_case(api, student["id"])
    validate_success(api.assign_case(case["id"], {"staff_id": staff1["id"]}, ADMIN), 200)
    return staff1, staff2, case


def test_reassign_moves_caseload_between_staff(api):
    """PRD §3.4: "on a reassignment the prior assignee's `active_caseload` drops by one
    and the new assignee's rises by one, where each `active_caseload` is defined as the
    number of that staff member's cases in `OPEN` or `MONITORING` status."

    Design: Difficulty/compensating_invariant/caseload_conserved_on_reassign
    """
    staff1, staff2, case = _two_managers_case_assigned_to_first(api)
    validate_success(api.assign_case(case["id"], {"staff_id": staff2["id"]}, ADMIN), 200)
    s1 = validate_success(api.get_staff(staff1["id"], ADMIN), 200)
    s2 = validate_success(api.get_staff(staff2["id"], ADMIN), 200)
    assert s1["active_caseload"] == 0
    assert s2["active_caseload"] == 1


def test_reassign_conserves_total_caseload(api):
    """PRD §3.4: "Across all staff, the sum of active caseloads always equals the number
    of assigned non-terminal cases."

    Design: Difficulty/compensating_invariant/caseload_conserved_on_reassign
    """
    staff1, staff2, case = _two_managers_case_assigned_to_first(api)
    validate_success(api.assign_case(case["id"], {"staff_id": staff2["id"]}, ADMIN), 200)
    s1 = validate_success(api.get_staff(staff1["id"], ADMIN), 200)
    s2 = validate_success(api.get_staff(staff2["id"], ADMIN), 200)
    assert s1["active_caseload"] + s2["active_caseload"] == 1


def test_second_open_case_rejected(api):
    """PRD §3.3: "Because a student may hold only one non-terminal case, a manual open for
    a student who already has a case in `OPEN` or `MONITORING` is rejected with
    `ERR_CASE_ALREADY_OPEN`."

    Design: Corner/validations/second_open_case_rejected
    """
    school, student, case = fx.make_school_student_case(api)
    res = api.create_case({"student_id": student["id"]}, ADMIN)
    validate_error(res, ApiErrorId.ERR_CASE_ALREADY_OPEN.value)


def test_assign_non_casemanager_staff_rejected(api):
    """PRD §3.4: "The assignee must be a staff member whose `role_type` is `CASE_MANAGER`;
    any other role type is rejected with `ERR_INVALID_STAFF_ROLE`."

    Design: Corner/validations/assign_non_casemanager_staff_rejected
    """
    school = fx.make_school(api)
    officer = fx.make_staff(api, school["id"], role_type="OFFICER", full_name="Off Role")
    student = fx.make_student(api, school["id"], grade_level=9)
    case = fx.make_case(api, student["id"])
    res = api.assign_case(case["id"], {"staff_id": officer["id"]}, ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STAFF_ROLE.value)


def test_caseload_cap_exceeded_rejected(api):
    """PRD §3.4: "An assignment that would push the new assignee's `active_caseload` above
    their `max_caseload` is refused with `ERR_CASELOAD_EXCEEDED`."

    Design: Corner/validations/caseload_cap_exceeded_rejected
    """
    school = fx.make_school(api)
    staff = fx.make_staff(api, school["id"], role_type="CASE_MANAGER", full_name="Cap Mgr", max_caseload=1)
    s1 = fx.make_student(api, school["id"], grade_level=9, full_name="Cy Cap")
    s2 = fx.make_student(api, school["id"], grade_level=9, full_name="Di Cap")
    case1 = fx.make_case(api, s1["id"])
    case2 = fx.make_case(api, s2["id"])
    validate_success(api.assign_case(case1["id"], {"staff_id": staff["id"]}, ADMIN), 200)
    res = api.assign_case(case2["id"], {"staff_id": staff["id"]}, ADMIN)
    validate_error(res, ApiErrorId.ERR_CASELOAD_EXCEEDED.value)


def test_resolved_transition_sweeps_referrals_to_completed(api):
    """PRD §3.9: "Resolving a case is the re-engagement milestone: every service referral
    for the case still in `REFERRED`, `ACCEPTED`, or `IN_PROGRESS` is swept to
    `COMPLETED`."

    Design: Corner/state_machines/resolved_transition_sweeps_referrals_completed
    """
    school, staff, student, case, conf = fx.make_case_with_held_conference(api)
    referral = fx.get_success_data(
        api.create_service_referral(case["id"], {"service_type": "COUNSELING", "provider_name": "Hope Center"}, ADMIN)
    )
    validate_success(api.transition_case(case["id"], {"to_status": "MONITORING"}, ADMIN), 200)
    validate_success(api.transition_case(case["id"], {"to_status": "RESOLVED"}, ADMIN), 200)
    referrals, _ = validate_paginated(api.list_service_referrals(case["id"], ADMIN))
    swept = [r for r in referrals if r["id"] == referral["id"]]
    assert len(swept) == 1
    assert swept[0]["status"] == "COMPLETED"
