"""Security layer: auth-context rejection, role permission denials, and
entity-backed ownership for teachers, substitutes, and coordinators."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    basic_world,
    create_absence_payload,
    create_district_payload,
    create_substitute_payload,
    make_coordinator_headers,
    make_school,
    make_staff,
    make_substitute_headers,
    make_teacher_headers,
    offer_assignment,
    onboard_substitute,
    report_absence,
    validate_error,
    validate_success,
)


def test_missing_auth_headers_returns_400(api, no_auth_headers):
    """PRD 2.1: "A request with a missing header or an unrecognized role value
    is rejected with `ERR_MISSING_OR_INVALID_AUTH_CONTEXT`."
    PRD 2.8: "Both headers present and the role recognized, else
    `ERR_MISSING_OR_INVALID_AUTH_CONTEXT` (400)."

    Design: Corner/validations/missing_auth_headers_returns_400
    """
    res = api.create_district(create_district_payload(), no_auth_headers)
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_AUTH_CONTEXT, expected_status=400)


def test_rbac_denials_across_roles(api):
    """PRD 2.1: "A request whose role is recognized but not permitted for the
    target endpoint is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD 2.8: "The role is listed for the endpoint in §4, else
    `ERR_FORBIDDEN_ROLE` (403)."

    Design: Corner/validations/rbac_denials_across_roles
    """
    ctx = basic_world()
    sub = onboard_substitute(activate=False)

    res = api.create_substitute(
        create_substitute_payload(full_name="Sub B", base_daily_rate_cents=100),
        make_teacher_headers(ctx["teacher"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)

    res = api.create_district(
        create_district_payload(name="D2"), TEST_USERS["payroll_clerk_headers"]
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)

    res = api.create_dispatch_batch(
        {"district_id": ctx["district"]["id"]}, make_substitute_headers(sub["id"])
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)


def test_ownership_violations_for_teacher_and_substitute(api):
    """PRD 2.1: "When `X-User-Role` is `Teacher`, `X-User-ID` is the `id` of
    the acting `StaffMember`; a teacher may only report or cancel absences
    whose `staff_member_id` equals their `X-User-ID`, and any attempt against
    another teacher's absence is rejected with
    `ERR_RESOURCE_OWNERSHIP_VIOLATION`."
    PRD 2.1: "When `X-User-Role` is `Substitute`, `X-User-ID` is the `id` of
    the acting `Substitute`; ownership checks on assignments and timesheets
    compare the resource's `substitute_id` to `X-User-ID`, and a substitute
    responding to, cancelling, or submitting against someone else's assignment
    is rejected with `ERR_RESOURCE_OWNERSHIP_VIOLATION`."

    Design: Corner/validations/ownership_violations_for_teacher_and_substitute
    """
    ctx = basic_world()
    teacher2 = make_staff(
        ctx["school"]["id"], full_name="Teach Two", subject="MATH", grade_band="HIGH"
    )
    sub_a = onboard_substitute(full_name="Sub A", rate_cents=20000)
    sub_b = validate_success(
        api.create_substitute(
            create_substitute_payload(full_name="Sub B", base_daily_rate_cents=18000),
            TEST_USERS["district_admin_headers"],
        ),
        201,
    )
    absence = report_absence(ctx["teacher"], start_date="2026-08-03", end_date="2026-08-03")
    coord_headers = make_coordinator_headers(ctx["coordinator"]["id"])
    offer = offer_assignment(absence["id"], sub_a["id"], coord_headers)

    res = api.cancel_absence(absence["id"], make_teacher_headers(teacher2["id"]))
    validate_error(res, ApiErrorId.ERR_RESOURCE_OWNERSHIP_VIOLATION, expected_status=403)

    res = api.respond_assignment(
        offer["id"], {"decision": "ACCEPT"}, make_substitute_headers(sub_b["id"])
    )
    validate_error(res, ApiErrorId.ERR_RESOURCE_OWNERSHIP_VIOLATION, expected_status=403)


def test_coordinator_cross_school_denial_and_positive_scope(api):
    """PRD 2.1: "When `X-User-Role` is `SchoolCoordinator`, `X-User-ID` is
    likewise the `id` of a `StaffMember` — one whose `is_coordinator` flag is
    true — and every write the coordinator performs must target a resource of
    the school whose `id` matches that staff record's `school_id`; acting on
    another school's resource is rejected with
    `ERR_RESOURCE_OWNERSHIP_VIOLATION`."
    PRD 3.1: "the `is_coordinator` flag, defaulting to false, is what elevates
    a staff record into the `SchoolCoordinator` identity of §2.1, so a write
    bearing a coordinator role whose staff record lacks the flag or belongs to
    another school fails ownership."

    Design: Corner/rbac/coordinator_cross_school_denial_and_positive_scope
    """
    ctx = basic_world(clock="2026-07-29T00:00:00Z")
    coord1 = ctx["coordinator"]
    school2 = make_school(ctx["district"]["id"], name="S2", budget=1_000_000)
    coord2 = make_staff(
        school2["id"], full_name="Coord Two", subject="ADMIN", grade_band="HIGH",
        is_coordinator=True,
    )
    teacher2 = make_staff(
        school2["id"], full_name="Teach Two", subject="MATH", grade_band="HIGH"
    )

    payload = create_absence_payload(teacher2["id"], start_date="2026-08-03",
                                   end_date="2026-08-03")
    res = api.create_absence(payload, make_coordinator_headers(coord1["id"]))
    validate_error(res, ApiErrorId.ERR_RESOURCE_OWNERSHIP_VIOLATION, expected_status=403)

    created = validate_success(
        api.create_absence(payload, make_coordinator_headers(coord2["id"])), 201
    )
    assert created["fill_status"] == "REPORTED"
    assert created["school_id"] == school2["id"]
