"""Authentication, RBAC denial, Family ownership scoping, and 404 resolution
(PRD §2.1, §2.4, §4)."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    activate_program,
    create_fleet,
    create_program,
    enroll_student,
    intake_asset,
    make_family_headers,
    setup_confirmed_damage_fee,
    validate_error,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
TECH = TEST_USERS["tech_headers"]


def test_missing_user_context_headers_rejected(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. A request missing either header, or presenting a role outside the declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_user_context_header_rejected
    """
    res = api.create_program(
        {"program_name": "P", "school_year": "2026-2027"}, headers={}
    )
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_family_cannot_activate_program(api, family_headers):
    """PRD §2.1: "A caller whose role is not permitted to invoke an endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403); §4 enumerates the authorized roles for every endpoint."

    POST /api/programs/{progId}/activate is authorized for DistrictAdmin only.

    Design: Corner/validations/family_cannot_activate_program
    """
    program = create_program()
    create_fleet(program["id"])
    res = api.activate_program(program["id"], family_headers)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)


def test_registrar_cannot_retire_asset(api, registrar_headers):
    """PRD §2.1: "A caller whose role is not permitted to invoke an endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403); §4 enumerates the authorized roles for every endpoint."

    POST /api/programs/{progId}/asset-units/{assetId}/retire is authorized for
    DistrictAdmin only.

    Design: Corner/validations/registrar_cannot_retire_asset
    """
    program = create_program()
    fleet = create_fleet(program["id"])
    unit = intake_asset(program["id"], fleet["id"], "BC-RB-1", "SN-RB-1")
    activate_program(program["id"])
    res = api.retire_asset_unit(
        program["id"], unit["id"],
        {"expected_asset_unit_version": unit["version"]}, registrar_headers,
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)


def test_unknown_asset_id_returns_not_found(api, admin_headers):
    """PRD §2.4: "The first identifier in the path that fails to resolve rejects the request immediately with the matching 404 — `ERR_PROGRAM_NOT_FOUND`, `ERR_FLEET_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_DAMAGE_REPORT_NOT_FOUND`, `ERR_FEE_NOT_FOUND`, `ERR_LOANER_CHECKOUT_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, or `ERR_SWEEP_NOT_FOUND` — before later segments are even examined."

    Design: Corner/validations/not_found_on_unknown_asset_id
    """
    program = create_program()
    create_fleet(program["id"])
    activate_program(program["id"])
    res = api.get_asset_unit(program["id"], NON_EXISTENT_UUID, admin_headers)
    validate_error(res, ApiErrorId.ERR_ASSET_NOT_FOUND)


def test_family_can_only_read_own_student(api):
    """PRD §2.1: "In practice this scopes a guardian to their own student: student-scoped reads and writes require the `studentId` in the path to equal `X-User-ID`."

    A Family caller whose X-User-ID names student S1 is refused when reading
    student S2's record.

    Design: Corner/rbac/family_can_only_see_own_student
    """
    program = create_program()
    create_fleet(program["id"])
    activate_program(program["id"])
    s1 = enroll_student(program["id"], "SIS-OWN-1", "Own One")
    s2 = enroll_student(program["id"], "SIS-OWN-2", "Own Two")
    res = api.get_student(program["id"], s2["id"], make_family_headers(s1["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)


def test_site_technician_cannot_waive_fee(api, tech_headers):
    """PRD §2.1: "A caller whose role is not permitted to invoke an endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403); §4 enumerates the authorized roles for every endpoint."

    POST /api/programs/{progId}/students/{studentId}/fees/{feeId}/waive is
    authorized for DistrictAdmin only.

    Design: Corner/rbac/site_technician_cannot_waive_fee
    """
    ctx = setup_confirmed_damage_fee(damage_category="COSMETIC",
                                     observed_condition_grade="A",
                                     free_lunch=True)
    res = api.waive_fee(ctx["program"]["id"], ctx["student"]["id"],
                        ctx["fee"]["id"], tech_headers)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)
