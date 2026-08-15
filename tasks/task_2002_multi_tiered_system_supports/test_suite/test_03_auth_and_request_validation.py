"""Authentication context, role-based access control, and request-body shape
validation (PRD §2.1, §2.5, §4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    build_user_headers,
    create_district_payload,
    create_screening_window_payload,
    setup_district_school,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
COORD = TEST_USERS["district_coordinator_headers"]
REGISTRAR = TEST_USERS["school_registrar_headers"]
TEACHER = TEST_USERS["teacher_headers"]
LEAD = TEST_USERS["team_lead_headers"]
SPED = TEST_USERS["sped_director_headers"]


class TestMissingUserContext:
    @pytest.mark.parametrize("headers", [
        {},
        {"X-User-ID": "test-user-1"},
        {"X-User-Role": "Teacher"},
    ], ids=["no-headers", "only-user-id", "only-role"])
    def test_missing_or_malformed_user_context_rejected(self, api, headers):
        """PRD §2.1: "All interactions with the API must be authenticated through
        a pair of mandatory HTTP headers. Each request must include `X-User-ID`
        to identify the acting user and `X-User-Role` to specify their
        operational capacity. A request in which either header is missing or
        malformed is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_user_context_header
        """
        resp = api.list_districts(headers)
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)


class TestRoleBasedAccess:
    @pytest.mark.parametrize("headers", [
        TEACHER, COORD, REGISTRAR, LEAD, SPED,
    ], ids=["Teacher", "DistrictCoordinator", "SchoolRegistrar", "TeamLead",
            "SpEdDirector"])
    def test_district_create_is_platform_admin_only(self, api, headers):
        """PRD §2.1: "Access to every operation is restricted by role, and an
        attempt to act outside the caller's designated role is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: POST `/districts` — "Create a district | PlatformAdmin".

        Design: Corner/validations/insufficient_permissions_wrong_role
        """
        resp = api.create_district(
            create_district_payload(name="X", academic_year="2025-2026"), headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)

    def test_screening_window_create_is_coordinator_only(self, api):
        """PRD §2.1: "Access to every operation is restricted by role, and an
        attempt to act outside the caller's designated role is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: POST `/districts/{districtId}/schools/{schoolId}/screening-windows`
        — "Create a screening window | DistrictCoordinator".

        Design: Corner/validations/insufficient_permissions_wrong_role
        """
        district, school = setup_district_school(api)
        resp = api.create_screening_window(
            district["id"], school["id"],
            create_screening_window_payload(), TEACHER)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)

    def test_every_authenticated_role_can_read(self, api):
        """PRD §2.1: "An eighth name, `Any`, is a marker role used in this
        document to indicate that read-only endpoints accept any authenticated
        role."
        PRD §4: GET `/districts/{districtId}/schools/{schoolId}` — "Get a school
        | Any".

        Design: Corner/rbac/any_role_can_read_resources
        """
        district, school = setup_district_school(api)
        all_headers = [
            ADMIN, COORD, REGISTRAR, TEACHER,
            build_user_headers("reader-interventionist", "InterventionistRole"),
            LEAD, SPED,
        ]
        for headers in all_headers:
            resp = api.get_school(district["id"], school["id"], headers)
            data = validate_success(resp, 200)
            assert data["id"] == school["id"], (
                f"role {headers['X-User-Role']} must be able to read a school")


class TestRequestBodyShape:
    def test_window_kind_enum_out_of_range_rejected(self, api):
        """PRD §2.5: "Independently of this pipeline, a request body that is
        missing a required field, carries a value of the wrong type, or uses an
        enum value outside its defined range is rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.3: "A window is defined by its `window_kind` — `FALL`, `WINTER`,
        or `SPRING` — and inclusive `opens_on` and `closes_on` dates."

        Design: Corner/entities/invalid_enum_value_rejected
        """
        district, school = setup_district_school(api)
        resp = api.create_screening_window(
            district["id"], school["id"],
            create_screening_window_payload(window_kind="SUMMER"), COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
