"""Auth/RBAC, response envelope, and pagination tests for the IP Management API.

Covers PRD §2.1 (auth + RBAC), §2.2 (envelope), §2.3 (pagination),
§2.6 (path resolution), §2.7 (validation priority — auth before everything).
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    PAGINATION,
    api_client,
    build_user_headers,
    create_business_unit,
    create_business_unit_payload,
    setup_foundation,
    validate_error,
    validate_paginated,
    validate_success,
)


# ─────────────────────────────────────────────────────────────
# Authentication (PRD §2.1)
# ─────────────────────────────────────────────────────────────


class TestAuthenticationHeaders:
    """Both X-User-ID and X-User-Role headers must be present and non-empty,
    per PRD §2.1."""

    def test_missing_x_user_id_returns_unauthenticated(self, api):
        """PRD §2.1: "a missing or blank value is rejected with
        ERR_UNAUTHENTICATED at HTTP 401."

        Claim: omitting X-User-ID → ERR_UNAUTHENTICATED (401).
        """
        resp = api.list_business_units({"X-User-Role": "Admin"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)

    def test_missing_x_user_role_returns_unauthenticated(self, api):
        """PRD §2.1: "a missing or blank value is rejected with
        ERR_UNAUTHENTICATED at HTTP 401."

        Claim: omitting X-User-Role → ERR_UNAUTHENTICATED (401).
        """
        resp = api.list_business_units({"X-User-ID": "anyone"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)

    def test_blank_x_user_id_returns_unauthenticated(self, api):
        """PRD §2.1: "a missing or blank value is rejected with
        ERR_UNAUTHENTICATED at HTTP 401."

        Claim: blank (empty-string) X-User-ID → ERR_UNAUTHENTICATED.
        """
        resp = api.list_business_units({"X-User-ID": "", "X-User-Role": "Admin"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)

    def test_blank_x_user_role_returns_unauthenticated(self, api):
        """PRD §2.1: "a missing or blank value is rejected with
        ERR_UNAUTHENTICATED at HTTP 401.

        Claim: blank X-User-Role → ERR_UNAUTHENTICATED.
        """
        resp = api.list_business_units({"X-User-ID": "u1", "X-User-Role": ""})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


# ─────────────────────────────────────────────────────────────
# Authorization (PRD §2.1 + §4)
# ─────────────────────────────────────────────────────────────


class TestAuthorization:
    """A role not listed for the endpoint is rejected with ERR_FORBIDDEN, per
    PRD §2.1."""

    def test_non_admin_cannot_create_business_unit(
        self, api, ip_manager_headers
    ):
        """PRD §2.1: "the role is checked against the operation's
        authorization list (see §4); a role outside that list is rejected with
        ERR_FORBIDDEN at HTTP 403."

        Claim: POST /business-units by IPManager → ERR_FORBIDDEN (PRD §4 lists
        Admin only).
        """
        resp = api.create_business_unit(
            create_business_unit_payload(), ip_manager_headers
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_counsel_cannot_create_ip_right(self, api, counsel_headers):
        """PRD §2.1: "a role outside that list is rejected with ERR_FORBIDDEN
        at HTTP 403."

        Claim: POST /ip-rights by Counsel → ERR_FORBIDDEN (PRD §4 lists
        IPManager only).
        """
        resp = api.create_ip_right(
            {
                "ip_type": "PATENT",
                "title": "x",
                "handling_mode": "SELF",
                "business_unit_id": "00000000-0000-0000-0000-000000000000",
                "primary_jurisdiction": "US",
            },
            counsel_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


# ─────────────────────────────────────────────────────────────
# Path-bound NOT_FOUND (PRD §2.6, §2.7 priority 3)
# ─────────────────────────────────────────────────────────────


class TestPathBoundNotFound:
    """Path-bound id failures resolve to ERR_NOT_FOUND (404)."""

    def test_get_unknown_business_unit_returns_not_found(self, api, admin_headers):
        """PRD §2.6: "A non-existent path-bound id at any position returns
        ERR_NOT_FOUND at HTTP 404."

        Claim: GET /business-units/{unknown} → ERR_NOT_FOUND (404).
        """
        resp = api.get_business_unit(NON_EXISTENT_UUID, admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    def test_get_unknown_ip_right_returns_not_found(self, api, admin_headers):
        """PRD §2.6: "A non-existent path-bound id at any position returns
        ERR_NOT_FOUND at HTTP 404."

        Claim: GET /ip-rights/{unknown} → ERR_NOT_FOUND.
        """
        resp = api.get_ip_right(NON_EXISTENT_UUID, admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


# ─────────────────────────────────────────────────────────────
# Response envelope (PRD §2.2)
# ─────────────────────────────────────────────────────────────


class TestResponseEnvelope:
    """All 2xx and 4xx responses carry the §2.2 envelope."""

    def test_success_envelope_has_meta_and_data(self, api, admin_headers):
        """PRD §2.2: "All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body."

        Claim: 2xx body contains meta (with api_request_id starting "req_")
        and a data block.
        """
        resp = api.create_business_unit(
            create_business_unit_payload(), admin_headers
        )
        # validate_success enforces the §2.2 envelope shape internally.
        data = validate_success(resp, expected_status=201)
        assert "id" in data
        body = resp.json()
        assert body["meta"]["api_request_id"].startswith("req_"), (
            "PRD §2.2: api_request_id must start with 'req_'"
        )
        assert body["response_type"] == "object"

    def test_error_envelope_has_error_id_and_message(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format ... The `error_id` is a unique,
        machine-readable string that identifies the specific error."

        Claim: 4xx body has data.error_id and data.message.
        """
        resp = api.list_business_units({"X-User-Role": "Admin"})
        body = resp.json()
        assert body["response_type"] == "error"
        assert "error_id" in body["data"]
        assert "message" in body["data"]


# ─────────────────────────────────────────────────────────────
# Pagination (PRD §2.3)
# ─────────────────────────────────────────────────────────────


class TestPagination:
    """limit ∈ [1, 100], offset >= 0; meta.has_more semantics per PRD §2.3."""

    def test_default_limit_is_ten(self, api, admin_headers):
        """PRD §2.3: "`limit` defaults to 10, has a minimum of 1, and a
        maximum of 100."

        Claim: omitted limit → meta.limit == 10.
        """
        resp = api.list_business_units(admin_headers)
        _data, meta = validate_paginated(resp)
        assert meta["limit"] == PAGINATION["DEFAULT_LIMIT"]
        assert meta["offset"] == PAGINATION["DEFAULT_OFFSET"]

    def test_limit_above_max_is_rejected(self, api, admin_headers):
        """PRD §2.3: "`limit` ... has a minimum of 1, and a maximum of 100;
        values outside this range are rejected as invalid input."

        Claim: limit=101 → an error (any 4xx error_id is acceptable; PRD
        does not name the specific id here, only that out-of-range is
        rejected — we just assert it's not a 2xx).
        """
        resp = api.list_business_units(admin_headers, params={"limit": 101})
        assert 400 <= resp.status_code < 500, (
            f"PRD §2.3 says values outside [1,100] are rejected; got "
            f"{resp.status_code}"
        )

    def test_pagination_has_more_flag(self, api, admin_headers):
        """PRD §2.3: "`has_more` (true if more rows exist beyond `offset +
        limit`)."

        Claim: with limit=1 and total_count >= 2, has_more is true.
        """
        # Seed two rows.
        create_business_unit(api)
        create_business_unit(api)
        resp = api.list_business_units(admin_headers, params={"limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] >= 2
        assert meta["has_more"] is True
        assert len(data) == 1


# ─────────────────────────────────────────────────────────────
# Validation priority (PRD §2.7) — auth precedes everything else
# ─────────────────────────────────────────────────────────────


class TestValidationPriority:
    """Authentication beats every other check (PRD §2.7 priority 1)."""

    def test_unauthenticated_beats_not_found(self, api):
        """PRD §2.7: "Authentication is evaluated first — missing or blank
        `X-User-ID` / `X-User-Role` headers always surface as
        `ERR_UNAUTHENTICATED` before any other check."

        Claim: missing headers + unknown path → ERR_UNAUTHENTICATED (not
        ERR_NOT_FOUND).
        """
        resp = api.get_business_unit(NON_EXISTENT_UUID, {})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)

    def test_forbidden_beats_not_found(self, api, counsel_headers):
        """PRD §2.7: "Authorization comes next: a role not listed for the
        endpoint returns `ERR_FORBIDDEN`. Once the caller is authenticated
        and authorized, the server resolves every path-bound id and returns
        `ERR_NOT_FOUND` for any that fail."

        Claim: a forbidden role on an unknown path → ERR_FORBIDDEN, not
        ERR_NOT_FOUND.
        """
        # /agents/{id}/verify is Admin-only per PRD §4; calling as Counsel.
        resp = api.verify_agent(NON_EXISTENT_UUID, {}, counsel_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
