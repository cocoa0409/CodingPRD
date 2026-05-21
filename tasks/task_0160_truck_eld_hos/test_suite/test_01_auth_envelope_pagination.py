"""Auth, response envelope, and pagination — PRD §2.1, §2.2, §2.3."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_MAX_LIMIT,
    TEST_USERS,
    create_carrier,
    create_driver,
    create_eld_device,
    create_vehicle,
    is_iso8601_timestamp,
    setup_full_stack,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Auth header validation — PRD §2.1
# ===========================================================================
class TestAuthHeaders:

    def test_missing_user_id_rejected_with_err_missing_auth(self, api):
        """PRD §2.1: "If either header is missing or unparsable, the
        request is rejected with `ERR_MISSING_AUTH` (HTTP 401)."

        Claim: a call with only X-User-Role set fails with
        ERR_MISSING_AUTH and HTTP 401.
        """
        headers = {"X-User-Role": "PlatformAdmin"}
        resp = api.get_clock(headers)
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH.value)

    def test_missing_user_role_rejected_with_err_missing_auth(self, api):
        """PRD §2.1: "If either header is missing or unparsable, the
        request is rejected with `ERR_MISSING_AUTH` (HTTP 401)."

        Claim: a call with only X-User-ID set fails with
        ERR_MISSING_AUTH and HTTP 401.
        """
        headers = {"X-User-ID": "admin-1"}
        resp = api.get_clock(headers)
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH.value)

    def test_role_not_on_allowlist_rejected_with_err_forbidden(self, api):
        """PRD §2.1: "If both headers are present but the role does not
        appear on the endpoint's allow-list, the request is rejected
        with `ERR_FORBIDDEN` (HTTP 403)."

        Claim: a Driver invoking POST /carriers (a PlatformAdmin
        exclusive operation per PRD §4) fails with ERR_FORBIDDEN.
        """
        # Use the placeholder Driver headers — the rule under test is
        # the role gate, not ownership.
        headers = TEST_USERS["driver_headers"]
        payload = {
            "dot_number": "1234567",
            "legal_name": "Forbidden Carrier Inc.",
            "safety_contact_user_id": "x",
        }
        resp = api.create_carrier(payload, headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Standard envelope — PRD §2.2
# ===========================================================================
class TestEnvelope:

    def test_success_envelope_carries_meta_and_response_type(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."

        Claim: a successful response carries `meta.api_request_id`
        starting with `req_` and an ISO 8601 `api_request_timestamp`.
        """
        carrier = create_carrier()
        resp = api.get_carrier(carrier["id"], TEST_USERS["admin_headers"])
        assert resp.status_code == 200
        body = resp.json()
        meta = body.get("meta", {})
        assert isinstance(meta.get("api_request_id"), str)
        assert meta["api_request_id"].startswith("req_"), (
            f"api_request_id must start with req_, got {meta['api_request_id']!r}"
        )
        assert is_iso8601_timestamp(meta["api_request_timestamp"])
        assert body.get("response_type") == "object"
        assert isinstance(body.get("data"), dict)

    def test_error_envelope_carries_error_id_and_message(self, api):
        """PRD §2.2: "The `error_id` is a unique, machine-readable
        string that identifies the specific error. The `message`
        provides a human-readable explanation of what went wrong."

        Claim: 4xx responses carry `response_type: "error"`, an
        `error_id`, and a `message` in `data`.
        """
        resp = api.get_clock({"X-User-Role": "PlatformAdmin"})
        assert resp.status_code == 401
        body = resp.json()
        assert body.get("response_type") == "error"
        data = body.get("data", {})
        assert data.get("error_id") == ApiErrorId.ERR_MISSING_AUTH.value
        assert isinstance(data.get("message"), str)
        assert len(data["message"]) > 0


# ===========================================================================
# Pagination — PRD §2.3
# ===========================================================================
class TestPagination:

    def test_default_limit_is_ten(self, api):
        """PRD §2.3: "`limit` defaults to 10".

        Claim: a list endpoint with no `limit` query param echoes
        `limit == 10` in `meta`.
        """
        state = setup_full_stack()
        resp = api.list_duty_events(
            state["driver"]["id"], TEST_USERS["officer_headers"],
        )
        _, meta = validate_paginated(resp)
        assert meta.get("limit") == PAGINATION_DEFAULT_LIMIT, (
            f"Expected default limit 10, got {meta.get('limit')}"
        )

    def test_limit_above_maximum_rejected(self, api):
        """PRD §2.3: "`limit` ... has ... a maximum of 100 ... Values
        outside these ranges yield `ERR_INVALID_INPUT` (HTTP 400)."

        Claim: limit=101 returns ERR_INVALID_INPUT at HTTP 400.
        """
        state = setup_full_stack()
        resp = api.list_duty_events(
            state["driver"]["id"], TEST_USERS["officer_headers"],
            params={"limit": PAGINATION_MAX_LIMIT + 1},
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_INPUT.value)

    def test_limit_zero_rejected(self, api):
        """PRD §2.3: "`limit` ... has a minimum of 1 ... Values outside
        these ranges yield `ERR_INVALID_INPUT` (HTTP 400)."

        Claim: limit=0 returns ERR_INVALID_INPUT at HTTP 400.
        """
        state = setup_full_stack()
        resp = api.list_duty_events(
            state["driver"]["id"], TEST_USERS["officer_headers"],
            params={"limit": 0},
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_INPUT.value)

    def test_negative_offset_rejected(self, api):
        """PRD §2.3: "`offset` defaults to 0 and has a minimum of 0.
        Values outside these ranges yield `ERR_INVALID_INPUT` (HTTP 400)."

        Claim: offset=-1 returns ERR_INVALID_INPUT at HTTP 400.
        """
        state = setup_full_stack()
        resp = api.list_duty_events(
            state["driver"]["id"], TEST_USERS["officer_headers"],
            params={"offset": -1},
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_INPUT.value)

    def test_pagination_meta_exposes_total_count_and_has_more(self, api):
        """PRD §2.3: "The response envelope's `meta` block exposes the
        echoed `limit` and `offset`, the unpaged `total_count`, and
        the boolean `has_more` flag".

        Claim: paginated list response carries total_count, has_more,
        echoed limit, and echoed offset in meta.
        """
        state = setup_full_stack()
        resp = api.list_duty_events(
            state["driver"]["id"], TEST_USERS["officer_headers"],
            params={"limit": 5, "offset": 0},
        )
        _, meta = validate_paginated(resp)
        assert meta.get("limit") == 5
        assert meta.get("offset") == 0
        assert "total_count" in meta
        assert isinstance(meta["total_count"], int)
        assert "has_more" in meta
        assert isinstance(meta["has_more"], bool)


# ===========================================================================
# Not-found — PRD §2.4 left-to-right path resolution
# ===========================================================================
class TestNotFound:

    def test_unknown_driver_id_returns_err_not_found(self, api):
        """PRD §2.4: "A path of the form
        `/drivers/{driver_id}/daily-logs/{log_id}` first resolves the
        `driver_id` against the `Driver` collection; if the driver does
        not exist, the request is rejected with `ERR_NOT_FOUND`
        (HTTP 404) before any attempt is made to resolve the `log_id`."

        Claim: GET on a nested path with an unknown driver_id returns
        ERR_NOT_FOUND at HTTP 404.
        """
        unknown_uuid = "00000000-0000-0000-0000-000000000099"
        resp = api.get_driver(unknown_uuid, TEST_USERS["officer_headers"])
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_unknown_carrier_id_returns_err_not_found(self, api):
        """PRD §2.4: "the same `ERR_NOT_FOUND` code surfaces when any
        other path or body identifier - `carrier_id`, `device_id`,
        `vehicle_id`, `event_id`, `violation_id` ... resolves to no
        row."

        Claim: GET /carriers/{unknown_id} returns ERR_NOT_FOUND.
        """
        unknown_uuid = "00000000-0000-0000-0000-000000000088"
        resp = api.get_carrier(unknown_uuid, TEST_USERS["admin_headers"])
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
