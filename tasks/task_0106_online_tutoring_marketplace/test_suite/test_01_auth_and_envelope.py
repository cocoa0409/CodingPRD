"""Auth, RBAC, response envelope, pagination, and NotFound.

These tests exercise the cross-cutting checks defined in PRD §2.1
(auth/role), §2.2 (envelope), §2.3 (pagination), §2.5 (NotFound),
which apply across every endpoint.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_MAX_LIMIT,
    TEST_USERS,
    build_user_headers,
    create_tutor,
    create_tutor_payload,
    is_iso8601_timestamp,
    make_tutor_headers,
    setup_basic_booking_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# §2.1 Auth — missing headers / unknown role / unauthorized role
# ===========================================================================
class TestAuthHeaders:
    """PRD §2.1: every request must carry X-User-ID and X-User-Role."""

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: "If either header is missing or carries an unknown
        role, the request is rejected with ERR_AUTH_REQUIRED."

        Claim: a POST with neither header set returns ERR_AUTH_REQUIRED.
        """
        res = api.create_tutor(create_tutor_payload(), headers={})
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "If either header is missing or carries an unknown
        role, the request is rejected with ERR_AUTH_REQUIRED."

        Claim: omitting X-User-ID while supplying X-User-Role returns
        ERR_AUTH_REQUIRED.
        """
        res = api.create_tutor(
            create_tutor_payload(),
            headers={"X-User-Role": "PlatformAdmin"},
        )
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: "If either header is missing or carries an unknown
        role, the request is rejected with ERR_AUTH_REQUIRED."

        Claim: omitting X-User-Role while supplying X-User-ID returns
        ERR_AUTH_REQUIRED.
        """
        res = api.create_tutor(
            create_tutor_payload(),
            headers={"X-User-ID": "admin-001"},
        )
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_unknown_role_value_rejected(self, api):
        """PRD §2.1: "If either header is missing or carries an unknown
        role, the request is rejected with ERR_AUTH_REQUIRED."

        Claim: X-User-Role="Hacker" (not one of the six known roles)
        returns ERR_AUTH_REQUIRED.
        """
        res = api.list_tutors(
            headers=build_user_headers("rando-1", "Hacker"),
        )
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_unauthorized_role_for_endpoint_rejected(self, api):
        """PRD §2.1: "If the role is recognized but is not permitted
        for the requested endpoint, the request is rejected with
        ERR_FORBIDDEN."

        Claim: a Student calling POST /tutoring/tutors/{id}/suspend
        (PlatformAdmin-only per §4) returns ERR_FORBIDDEN.
        """
        tutor = create_tutor()
        res = api.suspend_tutor(
            tutor["id"],
            headers=build_user_headers("rando-student", "Student"),
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_tutor_cannot_arbitrate_dispute(self, api):
        """PRD §4 endpoint table: POST /tutoring/disputes/{id}/arbitrate
        authorized role is PlatformArbiter.
        PRD §2.1: "If the role is recognized but is not permitted for
        the requested endpoint, the request is rejected with
        ERR_FORBIDDEN."

        Claim: Tutor calling /arbitrate returns ERR_FORBIDDEN.
        """
        tutor = create_tutor()
        # Use a non-existent dispute id to test role gate before
        # existence; PRD §2.6 priority lists role before existence.
        from test_helpers import arbitrate_dispute_payload
        res = api.arbitrate_dispute(
            NON_EXISTENT_UUID,
            arbitrate_dispute_payload(decision="DENY"),
            make_tutor_headers(tutor["id"]),
        )
        validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# §2.2 Response envelope
# ===========================================================================
class TestResponseEnvelope:
    """PRD §2.2: success / error envelope shape."""

    def test_success_envelope_shape(self, api, admin_headers):
        """PRD §2.2: success responses carry meta with api_request_id
        that "starts with req_" and api_request_timestamp that is "ISO
        8601 UTC timestamp with three fractional digits".

        Claim: a successful response returns the documented envelope
        shape.
        """
        body = api.list_tutors(admin_headers, params={"limit": 1}).json()
        meta = body["meta"]
        assert meta["api_request_id"].startswith("req_"), (
            f"api_request_id must start with 'req_', got "
            f"{meta['api_request_id']!r}"
        )
        assert is_iso8601_timestamp(meta["api_request_timestamp"]), (
            f"api_request_timestamp must be ISO 8601, got "
            f"{meta['api_request_timestamp']!r}"
        )
        assert body["response_type"] in {"object", "array"}

    def test_error_envelope_shape(self, api, admin_headers):
        """PRD §2.2: error responses have response_type=error and
        data.error_id + data.message.

        Claim: a 404 NotFound carries the documented error envelope.
        """
        res = api.get_tutor(NON_EXISTENT_UUID, admin_headers)
        body = res.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str)
        assert body["data"]["message"]  # non-empty


# ===========================================================================
# §2.3 Pagination
# ===========================================================================
class TestPagination:
    """PRD §2.3: limit defaults to 10, min 1, max 100; offset defaults
    to 0."""

    def test_default_pagination_limit(self, api, admin_headers):
        """PRD §2.3: "List endpoints accept two query parameters: limit,
        defaulting to 10, with a minimum of 1 and a maximum of 100, and
        offset, defaulting to 0."

        Claim: a list endpoint without `limit` returns meta.limit == 10
        and at most 10 items.
        """
        # Seed at least 12 tutors so the page is forced to cap.
        for _ in range(12):
            create_tutor()
        data, meta = validate_paginated(api.list_tutors(admin_headers))
        assert meta["limit"] == PAGINATION_DEFAULT_LIMIT
        assert len(data) <= PAGINATION_DEFAULT_LIMIT

    def test_pagination_meta_fields_present(self, api, admin_headers):
        """PRD §2.3: "Every list response carries limit, offset,
        total_count, and has_more inside meta."

        Claim: every list response has all four pagination fields with
        correct types.
        """
        create_tutor()
        data, meta = validate_paginated(
            api.list_tutors(admin_headers, params={"limit": 1}),
        )
        for field in ("limit", "offset", "total_count", "has_more"):
            assert field in meta, f"meta missing field {field!r}"
        assert isinstance(meta["limit"], int)
        assert isinstance(meta["offset"], int)
        assert isinstance(meta["total_count"], int)
        assert isinstance(meta["has_more"], bool)

    def test_pagination_offset_skips_items(self, api, admin_headers):
        """PRD §2.3: "Unless otherwise stated, list endpoints return
        resources sorted by created_at ascending."

        Claim: with offset>0 the returned items skip the first N rows
        (non-overlapping pages).
        """
        for _ in range(5):
            create_tutor()
        first_page, _ = validate_paginated(
            api.list_tutors(admin_headers, params={"limit": 2, "offset": 0}),
        )
        second_page, _ = validate_paginated(
            api.list_tutors(admin_headers, params={"limit": 2, "offset": 2}),
        )
        ids_first = {r["id"] for r in first_page}
        ids_second = {r["id"] for r in second_page}
        assert ids_first.isdisjoint(ids_second), (
            "offset window must not overlap the previous page"
        )

    def test_has_more_flag_logic(self, api, admin_headers):
        """PRD §2.3: "The has_more flag is true when
        offset + limit < total_count."

        Claim: a page covering all items has has_more=false; a partial
        page has has_more=true.
        """
        for _ in range(5):
            create_tutor()
        data, meta = validate_paginated(
            api.list_tutors(admin_headers, params={"limit": 2, "offset": 0}),
        )
        expected = (meta["offset"] + meta["limit"] < meta["total_count"])
        assert meta["has_more"] is expected


# ===========================================================================
# §2.5 NotFound resolution
# ===========================================================================
class TestNotFound:
    """PRD §2.5: path identifiers resolved left-to-right; missing → 404."""

    def test_get_tutor_nonexistent_returns_404(self, api, admin_headers):
        """PRD §2.5 + §5: ERR_NOT_FOUND fires when "Path or FK resource
        does not exist."

        Claim: GET /tutoring/tutors/{unknown UUID} returns ERR_NOT_FOUND.
        """
        res = api.get_tutor(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_get_session_nonexistent_returns_404(self, api, admin_headers):
        """PRD §2.5 + §5: ERR_NOT_FOUND fires for unknown id.

        Claim: GET /tutoring/sessions/{unknown UUID} returns
        ERR_NOT_FOUND.
        """
        res = api.get_session(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_get_dispute_nonexistent_returns_404(self, api, admin_headers):
        """PRD §2.5 + §5: ERR_NOT_FOUND fires for unknown id.

        Claim: GET /tutoring/disputes/{unknown UUID} returns
        ERR_NOT_FOUND.
        """
        res = api.get_dispute(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_nested_path_validates_outer_first(self, api):
        """PRD §2.5: "The server validates path identifiers strictly
        left-to-right and returns ERR_NOT_FOUND for the first missing
        one. A request for a credential under a non-existent tutor
        surfaces the missing tutor before the missing credential is
        ever considered."

        Claim: approving a credential under a non-existent tutor
        returns ERR_NOT_FOUND.
        """
        res = api.approve_credential(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID,
            TEST_USERS["verifier_headers"],
        )
        validate_error(res, "ERR_NOT_FOUND")
