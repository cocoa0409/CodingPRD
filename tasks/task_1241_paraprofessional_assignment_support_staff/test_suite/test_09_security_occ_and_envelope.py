"""Auth context, role authorization, not-found catalogue, optimistic concurrency,
and the response envelope (PRD §2.1, §2.2, §2.3, §2.8, §2.10)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_student,
    create_absence_payload,
    create_active_assignment,
    create_active_plan,
    create_active_student,
    create_assignment_payload,
    create_coverage_plan_payload,
    create_evaluation_payload,
    create_para,
    create_plan_payload,
    create_student,
    create_student_payload,
    get_plan_version,
    log_timesheet,
    make_para_headers,
    submit_timesheet,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
BLDG_ADMIN = TEST_USERS["building_admin_headers"]
TEACHER = TEST_USERS["teacher_headers"]
ANY = TEST_USERS["any_headers"]


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request to the API must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the role the user is acting in. A request missing either header, or carrying a role value that is not one of the declared roles, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_header_returns_unauthenticated
    """
    resp = api.create_plan(
        create_plan_payload(plan_name="NoAuth", total_budget_cents=1000),
        headers={"Content-Type": "application/json"},
    )
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_role_check_beats_state_check(api):
    """PRD §2.7: "First, the authentication check: both context headers must be present and the role must be declared, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Second, authorization: the role must be permitted on the endpoint, else `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/validations/priority_auth_role_beats_state
    """
    plan = validate_success(api.create_plan(create_plan_payload(), ADMIN), 201)
    # SpecialEdCoordinator may not activate a plan; the DRAFT plan would also fail
    # role-independent checks, but the role check fires first
    resp = api.activate_plan(plan["id"], COORD)
    data = validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    assert data["error_id"] not in (
        ApiErrorId.ERR_PLAN_HAS_NO_BUILDINGS,
        ApiErrorId.ERR_PLAN_NOT_DRAFT,
    )


@pytest.mark.parametrize(
    "getter,error_id",
    [
        ("get_plan", ApiErrorId.ERR_PLAN_NOT_FOUND),
        ("get_building", ApiErrorId.ERR_BUILDING_NOT_FOUND),
        ("get_student", ApiErrorId.ERR_STUDENT_NOT_FOUND),
        ("get_para", ApiErrorId.ERR_PARAPROFESSIONAL_NOT_FOUND),
        ("get_assignment", ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND),
        ("get_coverage_plan", ApiErrorId.ERR_COVERAGE_PLAN_NOT_FOUND),
        ("get_absence", ApiErrorId.ERR_ABSENCE_NOT_FOUND),
        ("get_backfill", ApiErrorId.ERR_BACKFILL_NOT_FOUND),
        ("get_timesheet", ApiErrorId.ERR_TIMESHEET_NOT_FOUND),
        ("get_evaluation", ApiErrorId.ERR_EVALUATION_NOT_FOUND),
        ("get_formula", ApiErrorId.ERR_FORMULA_NOT_FOUND),
        ("get_allocation", ApiErrorId.ERR_ALLOCATION_NOT_FOUND),
        ("get_change_order", ApiErrorId.ERR_CHANGE_ORDER_NOT_FOUND),
    ],
)
def test_get_missing_resource_returns_resource_specific_not_found(api, getter, error_id):
    """PRD §2.10: "Each missing resource surfaces its own error: `ERR_PLAN_NOT_FOUND`, `ERR_BUILDING_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`, `ERR_PARAPROFESSIONAL_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_COVERAGE_PLAN_NOT_FOUND`, `ERR_ABSENCE_NOT_FOUND`, `ERR_BACKFILL_NOT_FOUND`, `ERR_TIMESHEET_NOT_FOUND`, `ERR_EVALUATION_NOT_FOUND`, `ERR_FORMULA_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, or `ERR_CHANGE_ORDER_NOT_FOUND` (all HTTP 404)."

    Design: Corner/entities/get_missing_resources_returns_not_found
    """
    resp = getattr(api, getter)(NON_EXISTENT_UUID, ANY)
    validate_error(resp, error_id)


def test_students_list_pagination_envelope(api):
    """PRD §2.3: "All list endpoints accept the query parameters `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and may not exceed 100. The `offset` parameter defaults to 0. List responses are always sorted by `created_at` ascending, and the `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/students_list_pagination_shape
    """
    plan = validate_success(api.create_plan(create_plan_payload(), ADMIN), 201)
    building = validate_success(
        api.create_building(
            {"plan_id": plan["id"], "name": "Lincoln", "building_code": "LIN",
             "hardship_factor": 1.0},
            ADMIN,
        ),
        201,
    )
    for ref in ("STU-001", "STU-002", "STU-003"):
        create_student(plan["id"], building["id"], student_ref=ref,
                       iep_minutes_per_week=300)

    resp = api.list_students(ANY, params={"plan_id": plan["id"], "limit": 2, "offset": 0})
    page1, meta1 = validate_paginated(resp)
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2
    assert meta1["offset"] == 0
    assert len(page1) == 2
    for row in page1:
        assert_student(row)

    resp2 = api.list_students(ANY, params={"plan_id": plan["id"], "limit": 2, "offset": 2})
    page2, meta2 = validate_paginated(resp2)
    assert len(page2) == 1
    assert meta2["has_more"] is False


def test_student_creation_invalid_enum_returns_invalid_request(api):
    """PRD §2.10: "Malformed payloads — a missing required field, a type mismatch, an invalid enum value — are rejected with `ERR_INVALID_REQUEST` (HTTP 400), which also covers violations of the per-plan uniqueness of `building_code`, `student_ref`, and paraprofessional `email`."
    PRD §3.2: "the `iep_service_level` (`ONE_TO_ONE`, `SHARED_SUPPORT`, or `TRANSITIONAL`), the mandated `iep_minutes_per_week` which must exceed zero, and optionally a `required_qualification` defaulting to `NONE` (the alternatives being `BEHAVIOR_SUPPORT`, `MEDICAL_DELEGATION`, and `SIGN_LANGUAGE`)."

    Design: Corner/entities/student_creation_invalid_enum_returns_invalid_request
    """
    plan = validate_success(api.create_plan(create_plan_payload(), ADMIN), 201)
    building = validate_success(
        api.create_building(
            {"plan_id": plan["id"], "name": "Lincoln", "building_code": "LIN",
             "hardship_factor": 1.0},
            ADMIN,
        ),
        201,
    )
    resp = api.create_student(
        create_student_payload(plan["id"], building["id"], iep_service_level="BOGUS"),
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_assignment_create_with_stale_plan_version_rejected(api):
    """PRD §2.8: "Creating an assignment — `POST /sped-staffing/assignments` — requires the request body to carry `expected_plan_version`, the client’s last-observed `version` of the target staffing plan. If the plan’s current `version` has advanced since that observation (because the plan was activated, another assignment was created against it, reconciliation began, or the plan was closed), the create is rejected with `ERR_STALE_VERSION` (HTTP 412), protecting the client from committing budget against a plan state it never saw."

    Design: Corner/validations/occ_stale_plan_version_rejected
    """
    plan, building, plan_v = create_active_plan()
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1)
    s1 = create_active_student(plan_id, b1, iep_minutes_per_week=300)
    # First create advances the plan's version by one
    resp = api.create_assignment(
        create_assignment_payload(
            plan_id, s1["id"], p1["id"], b1, plan_v,
            days_of_week=["MON"], daily_start_minute=480, daily_end_minute=540,
        ),
        COORD,
    )
    validate_success(resp, 201)
    # The stale last-observed version is now one behind
    resp2 = api.create_assignment(
        create_assignment_payload(
            plan_id, s1["id"], p1["id"], b1, plan_v,
            days_of_week=["TUE"], daily_start_minute=480, daily_end_minute=540,
        ),
        COORD,
    )
    validate_error(resp2, ApiErrorId.ERR_STALE_VERSION)


def test_absence_create_with_stale_coverage_plan_version_rejected(api):
    """PRD §2.8: "Reporting an absence — `POST /sped-staffing/absence-reports` — likewise requires `expected_coverage_plan_version`, the client’s last-observed `version` of the resolved coverage plan; a mismatch with the coverage plan’s current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), protecting the caller from filing an absence against a coverage posture that has since been published, reopened, or locked."

    Design: Corner/validations/occ_stale_coverage_plan_version_rejected
    """
    plan, building, plan_v = create_active_plan()
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1)
    s1 = create_active_student(plan_id, b1, iep_service_level="ONE_TO_ONE")
    a1 = create_active_assignment(plan_id, s1["id"], p1["id"], b1, plan_v)
    cp = validate_success(
        api.create_coverage_plan(
            create_coverage_plan_payload(plan_id, b1, "2026-05-06"), COORD
        ),
        201,
    )
    stale_version = cp["version"]  # client holds the pre-publish version
    validate_success(api.publish_coverage_plan(cp["id"], COORD))  # advances version

    resp = api.create_absence(
        create_absence_payload(a1["id"], "2026-05-06", stale_version, "stale view"), TEACHER
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_coordinator_cannot_create_plan(api):
    """PRD §2.1: "Once the caller is authenticated, the role must additionally appear in the endpoint's authorized role list; a caller whose role is not permitted for the operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §2.1: "DistrictStaffingAdmin` is the district staffing administrator and owns plans, buildings, the paraprofessional roster and its training records, allocation formulas, allocation computation, service-change-order approval, and the logical clock."

    Design: Corner/rbac/coordinator_cannot_create_plan_returns_unauthorized
    """
    resp = api.create_plan(
        create_plan_payload(plan_name="Nope", total_budget_cents=1000), COORD
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_teacher_cannot_create_assignment(api):
    """PRD §2.1: "SpecialEdCoordinator` owns students, change-order filing and effectuation, the assignment lifecycle, coverage plans, absence escalation, and backfill offers."
    PRD §2.1: "Once the caller is authenticated, the role must additionally appear in the endpoint's authorized role list; a caller whose role is not permitted for the operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/teacher_cannot_create_assignment_returns_unauthorized
    """
    plan, building, plan_v = create_active_plan()
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1)
    s1 = create_active_student(plan_id, b1, iep_minutes_per_week=300)
    resp = api.create_assignment(
        create_assignment_payload(
            plan_id, s1["id"], p1["id"], b1, plan_v,
            days_of_week=["MON"], daily_start_minute=480, daily_end_minute=540,
        ),
        TEACHER,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_district_admin_cannot_countersign_evaluation(api):
    """PRD §2.1: "BuildingAdministrator` approves or rejects timesheets and countersigns or resolves evaluations."
    PRD §2.1: "Once the caller is authenticated, the role must additionally appear in the endpoint's authorized role list; a caller whose role is not permitted for the operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/admin_cannot_countersign_returns_unauthorized
    """
    from test_helpers import create_evaluation, make_teacher_headers

    plan, building, _ = create_active_plan()
    p1 = create_para(plan["id"], building["id"])
    ev = create_evaluation(plan["id"], p1["id"], author_headers=make_teacher_headers("teacher-1"))
    validate_success(api.submit_evaluation(ev["id"], make_teacher_headers("teacher-1")))

    resp = api.countersign_evaluation(ev["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_para_cannot_approve_own_timesheet(api):
    """PRD §2.1: "Once the caller is authenticated, the role must additionally appear in the endpoint's authorized role list; a caller whose role is not permitted for the operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §2.1: "BuildingAdministrator` approves or rejects timesheets and countersigns or resolves evaluations."

    Design: Corner/errors/para_cannot_approve_own_timesheet_returns_unauthorized
    """
    from test_helpers import setup_plan_with_active_assignment

    scenario = setup_plan_with_active_assignment()
    a1, p1 = scenario["a1"], scenario["p1"]
    t1 = log_timesheet(a1["id"], p1["id"], "2026-05-04", 480, 780)
    submit_timesheet(t1["id"], p1["id"])

    # The approve endpoint is BuildingAdministrator-only; a para — even the
    # entry's own para — is denied at the role check
    resp = api.approve_timesheet(t1["id"], make_para_headers(p1["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_backfill_accept_by_other_para_returns_not_own(api):
    """PRD §3.6: "The offered para answers personally: both acceptance and decline require `X-User-ID` to equal the offer’s `substitute_para_id`, else `ERR_BACKFILL_NOT_OWN`, and any other backfill transition from a wrong state is `ERR_BACKFILL_INVALID_STATE`."

    Design: Corner/errors/backfill_accept_by_other_para_returns_not_own
    """
    from test_helpers import setup_offered_backfill

    scenario = setup_offered_backfill()  # P2 created inside fixture
    plan_id, b1 = scenario["plan"]["id"], scenario["building"]["id"]
    bf, p2 = scenario["bf"], scenario["p2"]
    p3 = create_para(plan_id, b1, full_name="Late Lou", hire_date="2025-09-01")

    resp = api.accept_backfill(bf["id"], make_para_headers(p3["id"]))
    validate_error(resp, ApiErrorId.ERR_BACKFILL_NOT_OWN)
    after = validate_success(api.get_backfill(bf["id"], ANY))
    assert after["status"] == "OFFERED"


def test_absence_report_by_other_para_returns_not_own(api):
    """PRD §3.6: "A paraprofessional reporter must own the assignment — `X-User-ID` must equal the assignment’s `para_id` — else `ERR_ABSENCE_NOT_OWN`."

    Design: Corner/errors/absence_report_by_other_para_returns_not_own
    """
    plan, building, plan_v = create_active_plan()
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1, full_name="Pat Para")
    p2 = create_para(plan_id, b1, full_name="Sam Sub", hire_date="2025-09-01")
    s1 = create_active_student(plan_id, b1, iep_service_level="ONE_TO_ONE")
    a1 = create_active_assignment(plan_id, s1["id"], p1["id"], b1, plan_v)
    cp = validate_success(
        api.create_coverage_plan(
            create_coverage_plan_payload(plan_id, b1, "2026-05-06"), COORD
        ),
        201,
    )
    cp = validate_success(api.publish_coverage_plan(cp["id"], COORD))

    resp = api.create_absence(
        create_absence_payload(a1["id"], "2026-05-06", cp["version"], "not mine"),
        make_para_headers(p2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ABSENCE_NOT_OWN)
