"""Authentication, validation-pipeline ordering, and role-based access control."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_race_payload,
    create_registration_payload,
    validate_error,
)

SP = TEST_USERS["spectator_headers"]
OP = TEST_USERS["timing_operator_headers"]
CLERK = TEST_USERS["registration_clerk_headers"]
OF = TEST_USERS["race_official_headers"]
CO = TEST_USERS["certification_officer_headers"]


class TestAuthentication:
    def test_missing_auth_headers_returns_401(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, declaring their
        operational capacity. A request in which either header is missing or
        empty is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_returns_401
        """
        resp = api.get_race(NON_EXISTENT_UUID, {})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)

    def test_auth_beats_business_priority(self, api):
        """PRD §2.7: "Every mutating request passes through a fixed validation
        pipeline, and the first failing stage produces the response. The stages
        run in this order: first authentication (the headers of §2.1), then role
        authorization, then existence of every referenced identifier per §2.10"

        Design: Corner/validations/auth_beats_business_priority
        """
        # Unauthenticated AND targeting a non-existent registration: the 401 wins.
        resp = api.confirm_registration(NON_EXISTENT_UUID, {})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestRoleAuthorization:
    def test_spectator_cannot_create_race(self, api):
        """PRD §2.1: "Access to each operation is restricted by role; a caller
        whose role is not on an endpoint's authorized list is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: POST /race-timing/races is authorized for RaceDirector only.

        Design: Corner/validations/spectator_cannot_create_race
        """
        resp = api.create_race(
            create_race_payload(name="Nope", distance_km=5.0,
                                course_type="UNCERTIFIED_COURSE",
                                course_time_limit_minutes=90),
            SP)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)

    def test_timing_operator_cannot_publish_results(self, api):
        """PRD §2.7: "The stages run in this order: first authentication (the
        headers of §2.1), then role authorization, then existence of every
        referenced identifier per §2.10" — the role check lands before the
        existence check, so even an unknown race id draws the 403.
        PRD §2.1: "a caller whose role is not on an endpoint's authorized list
        is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/timing_operator_cannot_publish_results
        """
        resp = api.publish_results(NON_EXISTENT_UUID, 1, OP)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)

    def test_clerk_cannot_resolve_result_flag(self, api):
        """PRD §2.1: "Access to each operation is restricted by role; a caller
        whose role is not on an endpoint's authorized list is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: POST /race-timing/result-flags/{flag_id}/resolve is authorized
        for RaceOfficial only.

        Design: Corner/rbac/clerk_cannot_resolve_result_flag
        """
        resp = api.resolve_result_flag(NON_EXISTENT_UUID, "CONFIRMED", CLERK)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)

    def test_official_cannot_create_registration(self, api):
        """PRD §2.1: "Access to each operation is restricted by role; a caller
        whose role is not on an endpoint's authorized list is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: POST /race-timing/registrations is authorized for
        RegistrationClerk only.

        Design: Corner/rbac/official_cannot_create_registration
        """
        resp = api.create_registration(
            create_registration_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID,
                                        "1", "X", "1990-01-01", "M"),
            OF)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)

    def test_certification_officer_cannot_lock_timing(self, api):
        """PRD §2.1: "Access to each operation is restricted by role; a caller
        whose role is not on an endpoint's authorized list is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: POST /race-timing/races/{race_id}/lock-timing is authorized for
        RaceDirector only.

        Design: Corner/rbac/certification_officer_cannot_lock_timing
        """
        resp = api.lock_timing(NON_EXISTENT_UUID, CO)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)
