"""Auth, response envelope, pagination — PRD §2.1, §2.2, §2.3.

These tests exercise the universal request/response contract that all
endpoints inherit. They are intentionally small so failures here
isolate one envelope concern at a time.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_exhibition_payload,
    is_iso8601_timestamp,
    validate_error,
    validate_success,
)


# ===========================================================================
# Missing or unrecognized auth headers (PRD §2.1)
# ===========================================================================
class TestAuthHeaders:

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "Requests missing either header are rejected with
        ERR_AUTH_REQUIRED (401)."

        Claim: missing X-User-ID → ERR_AUTH_REQUIRED, 401.
        """
        headers = {"X-User-Role": "VenueAdmin"}
        res = api.create_exhibition(create_exhibition_payload(), headers)
        validate_error(res, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: "Requests missing either header are rejected with
        ERR_AUTH_REQUIRED (401)."

        Claim: missing X-User-Role → ERR_AUTH_REQUIRED, 401.
        """
        headers = {"X-User-ID": "anybody"}
        res = api.create_exhibition(create_exhibition_payload(), headers)
        validate_error(res, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_role_not_permitted_for_endpoint(self, api):
        """PRD §2.1: "Requests whose role is not on the endpoint's
        permitted list are rejected with ERR_FORBIDDEN (403)."

        Claim: Exhibitor cannot POST /exhibitions (VenueAdmin only).
        """
        res = api.create_exhibition(
            create_exhibition_payload(), TEST_USERS["exhibitor_headers"],
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_gate_operator_cannot_create_exhibition(self, api):
        """PRD §2.1: "Requests whose role is not on the endpoint's
        permitted list are rejected with ERR_FORBIDDEN (403)."

        Claim: GateOperator cannot POST /exhibitions.
        """
        res = api.create_exhibition(
            create_exhibition_payload(),
            TEST_USERS["gate_operator_headers"],
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Success envelope (PRD §2.2)
# ===========================================================================
class TestSuccessEnvelope:

    def test_success_envelope_carries_request_id_with_req_prefix(self, api):
        """PRD §2.2: "The api_request_id is a server-generated unique
        identifier for the request that starts with `req_`."

        Claim: success response.meta.api_request_id begins with 'req_'.
        """
        res = api.create_exhibition(
            create_exhibition_payload(),
            TEST_USERS["venue_admin_headers"],
        )
        # Read raw body — validate_success returns data only.
        body = res.json()
        assert body["meta"]["api_request_id"].startswith("req_"), (
            f"api_request_id must start with 'req_', got "
            f"{body['meta']['api_request_id']!r}"
        )

    def test_success_envelope_carries_iso8601_timestamp(self, api):
        """PRD §2.2: "The api_request_timestamp is a server-generated
        ISO 8601 UTC timestamp with three fractional digits."

        Claim: success response.meta.api_request_timestamp is ISO 8601.
        """
        res = api.create_exhibition(
            create_exhibition_payload(),
            TEST_USERS["venue_admin_headers"],
        )
        body = res.json()
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])

    def test_success_envelope_response_type_object(self, api):
        """PRD §2.2: "The response_type is either 'object' for a single
        resource or 'array' for a list of resources."

        Claim: a single-resource success returns response_type='object'.
        """
        res = api.create_exhibition(
            create_exhibition_payload(),
            TEST_USERS["venue_admin_headers"],
        )
        body = res.json()
        assert body["response_type"] == "object"


# ===========================================================================
# Error envelope (PRD §2.2)
# ===========================================================================
class TestErrorEnvelope:

    def test_error_envelope_shape(self, api):
        """PRD §2.2: "The error_id is a unique, machine-readable string
        that identifies the specific error."

        Claim: an error response carries response_type='error' and a
        data.error_id matching the documented identifier.
        """
        headers = {}  # neither X-User-ID nor X-User-Role
        res = api.create_exhibition(create_exhibition_payload(), headers)
        body = res.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == ApiErrorId.ERR_AUTH_REQUIRED.value
        assert "message" in body["data"]


# ===========================================================================
# NotFound on path-referenced resources (PRD §2.7)
# ===========================================================================
class TestNotFound:

    def test_get_exhibition_not_found_returns_404(self, api):
        """PRD §2.7: "Endpoints whose path embeds more than one
        identifier validate those identifiers strictly in left-to-right
        order, returning ERR_NOT_FOUND (404) for the first identifier
        that does not resolve."

        Claim: GET an unknown exhibition → ERR_NOT_FOUND, 404.
        """
        res = api.get_exhibition(
            NON_EXISTENT_UUID, TEST_USERS["venue_admin_headers"],
        )
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_create_hall_under_missing_exhibition_returns_404(self, api):
        """PRD §2.7: "A request that targets, for example, a booth
        under a non-existent hall fails at the hall step with
        ERR_NOT_FOUND and never reaches booth resolution."

        Claim: POST /exhibitions/{missing}/halls → ERR_NOT_FOUND, 404
        before any hall-payload validation runs.
        """
        from test_helpers import create_hall_payload
        res = api.create_hall(
            NON_EXISTENT_UUID, create_hall_payload(),
            TEST_USERS["venue_admin_headers"],
        )
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# Pagination defaults (PRD §2.3)
# ===========================================================================
class TestPagination:

    def test_list_booths_default_limit_meta_present(self, api):
        """PRD §2.3: "The meta object of every list response carries
        limit, offset, total_count, and has_more alongside the
        standard api_request_id and api_request_timestamp."

        Claim: pagination meta fields are present on list responses.
        """
        from test_helpers import (
            create_and_activate_floor_plan,
            create_exhibition,
            create_hall,
        )
        exh = create_exhibition()
        hall = create_hall(exh["id"])
        create_and_activate_floor_plan(hall["id"])
        # List should return an empty list with meta.
        res = api.list_booths(
            hall["id"], TEST_USERS["venue_admin_headers"],
        )
        body = res.json()
        assert "limit" in body["meta"]
        assert "offset" in body["meta"]
        assert "total_count" in body["meta"]
        assert "has_more" in body["meta"]
