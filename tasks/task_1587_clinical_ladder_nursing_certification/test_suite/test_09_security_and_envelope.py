"""Authentication, role authorization, and pagination bound handling
(PRD §2.1, §2.3, §2.8)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_ladder_criterion_payload,
    create_nurse,
    make_nurse_headers,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["program_admin_headers"]


class TestAuthentication:
    def test_missing_auth_header_returns_unauthenticated(self, api):
        """PRD §2.1: "Every request carries two identity headers: `X-User-ID`
        and `X-User-Role`. A request missing either header, or presenting a
        role string outside the declared set, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_header_returns_unauthenticated
        """
        resp = api.list_nurses(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)
        resp_no_id = api.list_nurses(headers={"X-User-Role": "ProgramAdmin"})
        validate_error(resp_no_id, ApiErrorId.ERR_UNAUTHENTICATED, 401)
        resp_bad_role = api.list_nurses(
            headers={"X-User-Role": "SuperUser", "X-User-ID": "x-1"}
        )
        validate_error(resp_bad_role, ApiErrorId.ERR_UNAUTHENTICATED, 401)


class TestRoleAuthorization:
    def test_nurse_cannot_create_criterion_forbidden(self, api):
        """PRD §2.1: "A request whose role is not permitted to invoke the
        endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: POST /clinical-ladder/ladder-criteria is authorized for
        ProgramAdmin only.

        Design: Corner/validations/nurse_cannot_create_criterion_forbidden
        """
        nurse = create_nurse(employee_code="RN-RB1", full_name="Rb One")
        resp = api.create_ladder_criterion(
            create_ladder_criterion_payload(), make_nurse_headers(nurse["id"])
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)


class TestPaginationBounds:
    def test_pagination_limit_bounds(self, api):
        """PRD §2.3: "List endpoints accept two query parameters: `limit`,
        defaulting to 10 with a minimum of 1 and a maximum of 100, and
        `offset`, defaulting to 0. The `meta` block of every list response
        carries `limit`, `offset`, `total_count`, and `has_more`."

        A limit of 100 (the stated maximum) must be accepted; a limit of 101
        exceeds the stated maximum and must not be served as a larger page —
        the service either rejects it or clamps the effective limit to its
        documented maximum.

        Design: Corner/cross_cutting_layers/pagination_limit_clamped
        """
        create_nurse(employee_code="RN-PG", full_name="Pg Nurse")
        data, meta = validate_paginated(
            api.list_nurses(ADMIN, params={"limit": 100, "offset": 0})
        )
        assert isinstance(data, list)
        assert meta["limit"] <= 100

        resp = api.list_nurses(ADMIN, params={"limit": 101, "offset": 0})
        if resp.status_code == 200:
            _, meta = validate_paginated(resp)
            assert meta["limit"] <= 100, (
                f"limit=101 must not yield a page larger than the maximum, got {meta['limit']}"
            )
        else:
            validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
