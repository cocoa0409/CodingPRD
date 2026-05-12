"""Auth, RBAC, pagination, and envelope tests (PRD §2.1, §2.2, §2.3, §2.6)."""
from __future__ import annotations
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    bring_counselor_to_active,
    create_appointment_payload,
    create_client,
    create_counselor_payload,
    create_counselor,
    make_admin_headers,
    make_client_headers,
    make_counselor_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAuthHeaders:
    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying a malformed
        value, is rejected with `ERR_AUTH_MISSING` and HTTP 401."
        """
        res = api.create_counselor(create_counselor_payload(), headers={})
        validate_error(res, "ERR_AUTH_MISSING", expected_status=401)

    def test_missing_user_id_rejected(self, api):
        """PRD §2.1: "A request missing either header ... is rejected with
        `ERR_AUTH_MISSING` and HTTP 401."
        """
        res = api.create_counselor(
            create_counselor_payload(),
            headers={"X-User-Role": "PlatformAdmin"},
        )
        validate_error(res, "ERR_AUTH_MISSING", expected_status=401)

    def test_missing_user_role_rejected(self, api):
        """PRD §2.1: "A request missing either header ... is rejected with
        `ERR_AUTH_MISSING` and HTTP 401."
        """
        res = api.create_counselor(
            create_counselor_payload(),
            headers={"X-User-ID": "admin-001"},
        )
        validate_error(res, "ERR_AUTH_MISSING", expected_status=401)


class TestRoleAuthorization:
    def test_client_cannot_register_counselor(self, api):
        """PRD §4 endpoint table: POST /counseling/counselors authorized roles
        is `PlatformAdmin`. PRD §2.1: "A request whose role is not authorised
        for the targeted endpoint is rejected with `ERR_FORBIDDEN` and HTTP 403."
        """
        client_headers = make_client_headers("client-stranger")
        res = api.create_counselor(create_counselor_payload(), client_headers)
        validate_error(res, "ERR_FORBIDDEN", expected_status=403)

    def test_counselor_cannot_register_client(self, api):
        """PRD §4 endpoint table: POST /counseling/clients authorized roles
        is `PlatformAdmin`. PRD §2.1: "A request whose role is not authorised
        for the targeted endpoint is rejected with `ERR_FORBIDDEN` and HTTP 403."
        """
        from test_helpers import create_client_payload
        counselor_headers = make_counselor_headers("counselor-stranger")
        res = api.create_client(create_client_payload(), counselor_headers)
        validate_error(res, "ERR_FORBIDDEN", expected_status=403)

    def test_public_cannot_create_appointment(self, api):
        """PRD §4 endpoint table: POST /counseling/appointments authorized
        role is `Client`. PRD §2.1: "A request whose role is not authorised
        for the targeted endpoint is rejected with `ERR_FORBIDDEN` and HTTP 403."
        """
        from test_helpers import make_public_headers
        public_headers = make_public_headers()
        # Use any UUID-shaped ids — auth/RBAC fires before existence check.
        payload = create_appointment_payload(
            counselor_id=NON_EXISTENT_UUID,
            client_id=NON_EXISTENT_UUID,
            slot_id=NON_EXISTENT_UUID,
        )
        res = api.create_appointment(payload, public_headers)
        validate_error(res, "ERR_FORBIDDEN", expected_status=403)


class TestExistence:
    def test_get_nonexistent_counselor_returns_404(self, api, admin_headers):
        """PRD §2.6: "the server resolves them strictly left to right and
        rejects with `ERR_NOT_FOUND` and HTTP 404 the moment the first
        non-existent identifier is encountered."
        """
        res = api.get_counselor(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, "ERR_NOT_FOUND", expected_status=404)

    def test_get_nonexistent_client_returns_404(self, api, admin_headers):
        """PRD §2.6: "the server resolves them strictly left to right and
        rejects with `ERR_NOT_FOUND` and HTTP 404 the moment the first
        non-existent identifier is encountered."
        """
        res = api.get_client(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, "ERR_NOT_FOUND", expected_status=404)

    def test_appointment_with_missing_slot_ref_is_422(self, api, admin_headers):
        """PRD §2.6: "Body-referenced foreign keys (such as a slot identifier
        inside an appointment-creation payload, or an appointment identifier
        inside a counseling-record payload) are validated after path
        resolution; an unresolvable body reference is rejected with
        `ERR_REF_NOT_FOUND` and HTTP 422."
        """
        # Need a valid Client to act as caller and pass RBAC. Create a Client
        # row first (admin-driven), then attempt the appointment with a
        # non-existent slot_id, so the ERR_REF_NOT_FOUND check is the first
        # one that fires.
        client = create_client()
        counselor = create_counselor()
        payload = create_appointment_payload(
            counselor_id=counselor["id"],
            client_id=client["id"],
            slot_id=NON_EXISTENT_UUID,
        )
        res = api.create_appointment(payload, make_client_headers(client["id"]))
        validate_error(res, "ERR_REF_NOT_FOUND", expected_status=422)


class TestEnvelopeAndPagination:
    def test_success_envelope_shape(self, api, admin_headers):
        """PRD §2.2: "All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body" —
        meta with api_request_id (starts with req_), api_request_timestamp,
        response_type "object" or "array", and data.
        """
        counselor = create_counselor()
        body = api.get_counselor(counselor["id"], admin_headers).json()
        assert "meta" in body and "data" in body and "response_type" in body
        assert body["response_type"] in ("object", "array")
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_"), \
            "PRD §2.2: api_request_id must start with 'req_'"

    def test_error_envelope_carries_error_id_and_message(self, api, admin_headers):
        """PRD §2.2: error response data contains `error_id` and `message`."""
        res = api.get_counselor(NON_EXISTENT_UUID, admin_headers)
        body = res.json()
        assert body["response_type"] == "error"
        assert "error_id" in body["data"]
        assert "message" in body["data"]

    def test_pagination_default_limit_is_10(self, api, admin_headers):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        if omitted it defaults to 10, has a minimum of 1 and a maximum of 100."
        """
        # Create a few counselors so there's something to list.
        for _ in range(3):
            create_counselor()
        res = api.list_counselors(admin_headers)
        data, meta = validate_paginated(res)
        assert meta["limit"] == 10

    def test_pagination_negative_offset_rejected(self, api, admin_headers):
        """PRD §2.3: "Values outside these bounds — `limit` below 1, `limit`
        above 100, or `offset` below 0 — are rejected with `ERR_PAGINATION_INVALID`."
        """
        res = api.list_counselors(admin_headers, params={"offset": -1})
        validate_error(res, "ERR_PAGINATION_INVALID", expected_status=422)

    def test_pagination_limit_above_max_rejected(self, api, admin_headers):
        """PRD §2.3: "Values outside these bounds — `limit` below 1, `limit`
        above 100, or `offset` below 0 — are rejected with `ERR_PAGINATION_INVALID`."
        """
        res = api.list_counselors(admin_headers, params={"limit": 101})
        validate_error(res, "ERR_PAGINATION_INVALID", expected_status=422)

    def test_pagination_limit_zero_rejected(self, api, admin_headers):
        """PRD §2.3: "Values outside these bounds — `limit` below 1, `limit`
        above 100, or `offset` below 0 — are rejected with `ERR_PAGINATION_INVALID`."
        """
        res = api.list_counselors(admin_headers, params={"limit": 0})
        validate_error(res, "ERR_PAGINATION_INVALID", expected_status=422)


class TestPublicCatalogue:
    def test_public_can_browse_counselors(self, api, public_headers):
        """PRD §3.4: "A client browsing the catalogue calls the public
        counselor list and the public availability list."
        PRD §4 endpoint table: GET /counseling/counselors authorized roles
        include Public.
        """
        res = api.list_counselors(public_headers)
        # Should succeed (200) regardless of contents.
        validate_paginated(res)
