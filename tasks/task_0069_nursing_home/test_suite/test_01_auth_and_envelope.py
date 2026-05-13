"""Authentication, RBAC, envelope, pagination, and resource-existence tests.

Anchored in PRD §2.1 (Auth), §2.2 (Envelope), §2.3 (Pagination),
§2.5 (Path / FK resolution), and §2.7 (Validation priority).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    create_elder_payload,
    create_room_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Authentication headers (PRD §2.1, §2.7 #1)
# ===========================================================================
class TestAuthHeaders:

    def test_missing_both_headers_yields_auth_missing(self):
        """PRD §2.1: "Every request must carry two headers: X-User-ID,
        the caller's identifier, and X-User-Role, the caller's role.
        Requests missing either header — or carrying a malformed value —
        are rejected with ERR_AUTH_MISSING at HTTP 401."

        Claim: a request with no auth headers fails ERR_AUTH_MISSING / 401.
        """
        resp = api_client._request("GET", "/elders", headers={})
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_missing_user_id_yields_auth_missing(self):
        """PRD §2.1: "Every request must carry two headers: X-User-ID,
        the caller's identifier, and X-User-Role, the caller's role.
        Requests missing either header — or carrying a malformed value —
        are rejected with ERR_AUTH_MISSING at HTTP 401."
        """
        resp = api_client._request(
            "GET", "/elders", headers={"X-User-Role": "Admin"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_missing_user_role_yields_auth_missing(self):
        """PRD §2.1: "Every request must carry two headers: X-User-ID,
        the caller's identifier, and X-User-Role, the caller's role.
        Requests missing either header — or carrying a malformed value —
        are rejected with ERR_AUTH_MISSING at HTTP 401."
        """
        resp = api_client._request(
            "GET", "/elders", headers={"X-User-ID": "u1"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_empty_user_id_yields_auth_missing(self):
        """PRD §2.1: "Every request must carry two headers: X-User-ID,
        the caller's identifier, and X-User-Role, the caller's role.
        Requests missing either header — or carrying a malformed value —
        are rejected with ERR_AUTH_MISSING at HTTP 401."

        Claim: empty X-User-ID is malformed → ERR_AUTH_MISSING / 401.
        """
        resp = api_client._request(
            "GET", "/elders",
            headers={"X-User-ID": "", "X-User-Role": "Admin"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)


# ===========================================================================
# Role authorization (PRD §2.1, §2.7 #2, §4)
# ===========================================================================
class TestRoleAuthorization:

    def test_caregiver_cannot_create_room(self):
        """PRD §2.1: "Requests that authenticate but whose role is not
        permitted for the targeted endpoint are rejected with ERR_FORBIDDEN
        at HTTP 403."

        Claim: POST /rooms is Admin-only; Caregiver gets ERR_FORBIDDEN.
        """
        resp = api_client.create_room(
            create_room_payload(), TEST_USERS["caregiver_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_family_cannot_create_elder(self):
        """PRD §2.1: "Requests that authenticate but whose role is not
        permitted for the targeted endpoint are rejected with ERR_FORBIDDEN
        at HTTP 403."

        Claim: POST /elders is Admin-only; Family gets ERR_FORBIDDEN.
        """
        resp = api_client.create_elder(
            create_elder_payload(), TEST_USERS["family_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_admin_can_create_room(self):
        """PRD §2.1: "`Admin` runs facility operations: rooms, beds,
        admissions, transfers, leave and return, discharge, epidemic
        posture, and the test-only operational capabilities."

        Claim: Admin can POST /rooms successfully (HTTP 201).
        """
        resp = api_client.create_room(
            create_room_payload(), TEST_USERS["admin_headers"],
        )
        validate_success(resp, expected_status=201)


# ===========================================================================
# Success envelope (PRD §2.2)
# ===========================================================================
class TestSuccessEnvelope:

    def test_success_envelope_carries_request_id_and_timestamp(self):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."

        Claim: success envelope.meta.api_request_id begins with 'req_'
        and api_request_timestamp parses as ISO 8601 with milliseconds.
        """
        resp = api_client.create_room(
            create_room_payload(), TEST_USERS["admin_headers"],
        )
        body = resp.json()
        meta = body["meta"]
        assert str(meta["api_request_id"]).startswith("req_"), \
            f"PRD §2.2 — api_request_id must start with 'req_': {meta['api_request_id']!r}"
        assert is_iso8601_timestamp(str(meta["api_request_timestamp"])), \
            f"PRD §2.2 — api_request_timestamp must be ISO 8601: {meta['api_request_timestamp']!r}"
        assert body["response_type"] == "object", \
            "PRD §2.2 — single-resource response_type is 'object'"


# ===========================================================================
# Error envelope (PRD §2.2)
# ===========================================================================
class TestErrorEnvelope:

    def test_error_envelope_shape(self):
        """PRD §2.2: "The error_id is a unique, machine-readable string
        that identifies the specific error. The message provides a
        human-readable explanation of what went wrong."

        Claim: error response has response_type=='error' and data carries
        error_id + message.
        """
        resp = api_client._request("GET", "/elders", headers={})
        body = resp.json()
        assert body["response_type"] == "error"
        data = body["data"]
        assert "error_id" in data and isinstance(data["error_id"], str)
        assert "message" in data and isinstance(data["message"], str)


# ===========================================================================
# Pagination defaults and bounds (PRD §2.3)
# ===========================================================================
class TestPaginationDefaults:

    def test_list_meta_has_pagination_fields(self):
        """PRD §2.3: "The meta envelope of a list response carries the four
        fields limit, offset, total_count, and has_more; has_more is true
        precisely when offset + limit is below total_count."

        Claim: list endpoint meta exposes all four pagination fields.
        """
        resp = api_client.list_elders(TEST_USERS["admin_headers"])
        data, meta = validate_paginated(resp)
        assert "limit" in meta and "offset" in meta
        assert "total_count" in meta and "has_more" in meta
        assert isinstance(meta["limit"], int)
        assert isinstance(meta["offset"], int)
        assert isinstance(meta["total_count"], int)
        assert isinstance(meta["has_more"], bool)

    def test_default_limit_is_10(self):
        """PRD §2.3: "`limit` defaults to 10 when omitted, may not be lower
        than 1, and may not exceed 100."

        Claim: when ``limit`` is omitted, server returns meta.limit == 10.
        """
        resp = api_client.list_elders(TEST_USERS["admin_headers"])
        _, meta = validate_paginated(resp)
        assert meta["limit"] == 10, \
            f"PRD §2.3 — default limit must be 10, got {meta['limit']}"

    def test_limit_above_100_rejected(self):
        """PRD §2.3: "`limit` defaults to 10 when omitted, may not be lower
        than 1, and may not exceed 100."

        Claim: limit=101 → ERR_VALIDATION / 422.
        """
        resp = api_client.list_elders(
            TEST_USERS["admin_headers"], params={"limit": 101},
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_limit_below_one_rejected(self):
        """PRD §2.3: "`limit` defaults to 10 when omitted, may not be lower
        than 1, and may not exceed 100."

        Claim: limit=0 → ERR_VALIDATION / 422.
        """
        resp = api_client.list_elders(
            TEST_USERS["admin_headers"], params={"limit": 0},
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_negative_offset_rejected(self):
        """PRD §2.3: "`offset` defaults to 0 and may not be lower than 0."

        Claim: offset=-1 → ERR_VALIDATION / 422.
        """
        resp = api_client.list_elders(
            TEST_USERS["admin_headers"], params={"offset": -1},
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ===========================================================================
# Resource existence (PRD §2.5, §2.7 #3 / #4)
# ===========================================================================
class TestResourceExistence:

    def test_get_nonexistent_elder_yields_not_found(self):
        """PRD §2.5: "the first missing resource encountered along the chain
        yields ERR_NOT_FOUND at HTTP 404."

        Claim: GET /elders/{unknown} → ERR_NOT_FOUND.
        """
        resp = api_client.get_elder(
            NON_EXISTENT_UUID, TEST_USERS["admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_admit_with_unknown_bed_id_yields_fk_not_found(self):
        """PRD §2.5: "Foreign-key fields in a POST or PATCH body — elder_id,
        room_id, based_on_assessment_id, bed_id, target_bed_id, new_plan_id,
        administration_id, prescription_id — are validated separately; an
        unknown reference in the body yields ERR_FK_NOT_FOUND, also at
        HTTP 404."

        Claim: POST /elders/{id}/admit with unknown bed_id → ERR_FK_NOT_FOUND.
        """
        # Create elder first; the path resolves; bed_id in body does not.
        elder_resp = api_client.create_elder(
            create_elder_payload(), TEST_USERS["admin_headers"],
        )
        elder = validate_success(elder_resp, expected_status=201)
        resp = api_client.admit_elder(
            elder["id"], {"bed_id": NON_EXISTENT_UUID},
            TEST_USERS["admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND.value)


# ===========================================================================
# Resource identity (PRD §2.4)
# ===========================================================================
class TestResourceIdentity:

    def test_created_room_has_uuid_id_and_version_1(self):
        """PRD §2.4: "Every resource is identified by a server-minted id —
        a UUID without any type prefix." and "version, an integer that
        begins at 1 on creation and increments by one on every successful
        mutation."

        Claim: POST /rooms returns id as UUID, version == 1.
        """
        resp = api_client.create_room(
            create_room_payload(), TEST_USERS["admin_headers"],
        )
        room = validate_success(resp, expected_status=201)
        assert is_valid_uuid(room["id"]), f"id must be UUID, got {room['id']!r}"
        assert room["version"] == 1, \
            f"PRD §2.4 — version starts at 1, got {room['version']}"
