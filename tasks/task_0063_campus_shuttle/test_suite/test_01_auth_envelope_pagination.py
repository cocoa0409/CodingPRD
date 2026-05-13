"""Authentication, RBAC, response envelope, and pagination.

Covers PRD §2.1 (RBAC), §2.2 (envelope), §2.3 (pagination), §2.4 (common
fields), §2.7 (nested resource retrieval).
"""
from __future__ import annotations
import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_stop_payload,
    create_active_stop,
)


# ===========================================================================
# Auth — missing / invalid headers (PRD §2.1)
# ===========================================================================
class TestAuthHeaders:

    def test_missing_user_id_returns_auth_missing(self):
        """PRD §2.1: "Every request must carry two HTTP headers: X-User-ID
        (the acting principal's identifier) and X-User-Role (their
        operational capacity). If either header is missing or empty, the
        request is rejected with ERR_AUTH_MISSING."

        Claim: missing X-User-ID -> ERR_AUTH_MISSING.
        """
        resp = api_client.create_stop(
            create_stop_payload(),
            headers={"X-User-Role": "Dispatcher"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING)

    def test_missing_user_role_returns_auth_missing(self):
        """PRD §2.1: "Every request must carry two HTTP headers: X-User-ID
        (the acting principal's identifier) and X-User-Role (their
        operational capacity). If either header is missing or empty, the
        request is rejected with ERR_AUTH_MISSING."

        Claim: missing X-User-Role -> ERR_AUTH_MISSING.
        """
        resp = api_client.create_stop(
            create_stop_payload(),
            headers={"X-User-ID": "operator-1"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING)

    def test_empty_user_id_returns_auth_missing(self):
        """PRD §2.1: "If either header is missing or empty, the request is
        rejected with ERR_AUTH_MISSING."

        Claim: empty X-User-ID -> ERR_AUTH_MISSING.
        """
        resp = api_client.create_stop(
            create_stop_payload(),
            headers={"X-User-ID": "", "X-User-Role": "Dispatcher"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING)

    def test_empty_user_role_returns_auth_missing(self):
        """PRD §2.1: "If either header is missing or empty, the request is
        rejected with ERR_AUTH_MISSING."

        Claim: empty X-User-Role -> ERR_AUTH_MISSING.
        """
        resp = api_client.create_stop(
            create_stop_payload(),
            headers={"X-User-ID": "operator-1", "X-User-Role": ""},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING)

    def test_invalid_role_returns_invalid_role(self):
        """PRD §2.1: "The system recognises four roles, spelled exactly as:
        Dispatcher, Driver, Employee, and Auditor. A header value outside
        this set is rejected with ERR_INVALID_ROLE."

        Claim: an unrecognised role -> ERR_INVALID_ROLE.
        """
        resp = api_client.create_stop(
            create_stop_payload(),
            headers={"X-User-ID": "x", "X-User-Role": "SuperAdmin"},
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_ROLE)


# ===========================================================================
# RBAC — forbidden roles (PRD §2.1 + §4 endpoint table)
# ===========================================================================
class TestForbidden:

    def test_employee_cannot_create_stop(self):
        """PRD §2.1: "When a recognised role attempts an operation that the
        role-permission matrix does not grant it, the request is rejected
        with ERR_FORBIDDEN."

        Claim: POST /shuttle/stops requires Dispatcher; Employee -> ERR_FORBIDDEN.
        """
        resp = api_client.create_stop(
            create_stop_payload(),
            headers={"X-User-ID": "emp-1", "X-User-Role": "Employee"},
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_driver_cannot_create_route(self):
        """PRD §2.1: "When a recognised role attempts an operation that the
        role-permission matrix does not grant it, the request is rejected
        with ERR_FORBIDDEN."

        Claim: POST /shuttle/routes requires Dispatcher; Driver -> ERR_FORBIDDEN.
        """
        resp = api_client.create_route(
            {
                "code": "RT-X1Y2",
                "name": "X",
                "start_stop_id": NON_EXISTENT_UUID,
                "end_stop_id": NON_EXISTENT_UUID,
                "intermediate_stop_ids": [],
                "peak_frequency_minutes": 10,
                "offpeak_frequency_minutes": 30,
                "peak_windows": [],
            },
            headers={"X-User-ID": "drv-1", "X-User-Role": "Driver"},
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_auditor_cannot_create_bill(self):
        """PRD §2.1: "When a recognised role attempts an operation that the
        role-permission matrix does not grant it, the request is rejected
        with ERR_FORBIDDEN."

        Claim: POST /shuttle/bills requires Dispatcher; Auditor -> ERR_FORBIDDEN.
        """
        resp = api_client.create_bill(
            {"billing_month": "2024-01", "payer_scope": "EMPLOYEE",
             "payer_id": "EMP1"},
            headers={"X-User-ID": "aud-1", "X-User-Role": "Auditor"},
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


# ===========================================================================
# Success envelope (PRD §2.2, §2.4)
# ===========================================================================
class TestSuccessEnvelope:

    def test_success_envelope_shape_on_create_stop(self, dispatcher_headers):
        """PRD §2.2: "All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body...
        meta.api_request_id... api_request_timestamp... response_type...
        data..."

        Claim: 2xx create response contains meta.api_request_id starting
        with req_, an ISO 8601 millisecond timestamp, response_type='object',
        and a data object.
        """
        resp = api_client.create_stop(create_stop_payload(),
                                      dispatcher_headers)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        meta = body["meta"]
        assert isinstance(meta["api_request_id"], str)
        assert meta["api_request_id"].startswith("req_"), \
            f"api_request_id must start with 'req_', got {meta['api_request_id']!r}"
        assert is_iso8601_timestamp(meta["api_request_timestamp"])
        assert body["response_type"] == "object"
        data = body["data"]
        assert is_valid_uuid(data["id"])

    def test_common_fields_on_versioned_entity(self, dispatcher_headers):
        """PRD §2.4: "All top-level resources (Route, Stop, Vehicle, Driver,
        RunSheet, Reservation, MonthlyBill) carry a standard set of
        system-managed fields: id is a server-minted UUID with no type
        prefix. created_at is an ISO 8601 UTC timestamp... updated_at is
        an ISO 8601 UTC timestamp... version is a non-negative integer
        that begins at 1 and increments by one on every mutation."

        Claim: a freshly-created Stop carries id, created_at, updated_at,
        and version=1.
        """
        resp = api_client.create_stop(create_stop_payload(),
                                      dispatcher_headers)
        data = validate_success(resp, 201)
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert is_iso8601_timestamp(data["updated_at"])
        assert isinstance(data["version"], int)
        assert data["version"] == 1, \
            f"Stop.version must begin at 1 (PRD §2.4), got {data['version']}"


# ===========================================================================
# Path resolution (PRD §2.7)
# ===========================================================================
class TestPathResolution:

    def test_get_nonexistent_stop_returns_not_found(self, dispatcher_headers):
        """PRD §2.7: "URL paths that contain multiple resource identifiers
        are validated left-to-right. A request that references a
        non-existent parent (for example, a run-sheet id that does not
        resolve) is rejected with ERR_NOT_FOUND before the server attempts
        to look up any child identifier or evaluate any body validation."

        Claim: GET on an unknown id -> ERR_NOT_FOUND.
        """
        resp = api_client.get_run_sheet(NON_EXISTENT_UUID, dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_create_reservation_unknown_run_sheet_returns_not_found(
            self, dispatcher_headers):
        """PRD §2.7: "URL paths that contain multiple resource identifiers
        are validated left-to-right. A request that references a
        non-existent parent (for example, a run-sheet id that does not
        resolve) is rejected with ERR_NOT_FOUND before the server attempts
        to look up any child identifier or evaluate any body validation."

        Claim: POST /shuttle/run-sheets/{unknown}/reservations -> ERR_NOT_FOUND
        without consulting the body.
        """
        resp = api_client.create_reservation(
            NON_EXISTENT_UUID,
            {"employee_id": "X", "boarding_stop_id": "Y",
             "alighting_stop_id": "Z", "payer_mode": "SELF_PAY"},
            dispatcher_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_run_sheet_unknown_route_returns_reference_not_found(
            self, dispatcher_headers):
        """PRD §2.7: "Once path identifiers are resolved, request bodies that
        carry foreign-key references — route_id, assigned_driver_id, an
        optional assigned_vehicle_id, boarding_stop_id, alighting_stop_id,
        reservation_id, start_stop_id, end_stop_id, and entries in
        intermediate_stop_ids — are validated to point at existing rows;
        an unresolved body FK is rejected with ERR_REFERENCE_NOT_FOUND."

        Claim: POST /shuttle/run-sheets with route_id = unknown UUID ->
        ERR_REFERENCE_NOT_FOUND.
        """
        resp = api_client.create_run_sheet(
            {"route_id": NON_EXISTENT_UUID,
             "scheduled_date": "2026-06-01T00:00:00.000Z",
             "scheduled_departure": "2026-06-01T08:00:00.000Z",
             "assigned_driver_id": NON_EXISTENT_UUID},
            dispatcher_headers,
        )
        # Any of the unresolved FKs is acceptable (PRD does not pin which
        # is checked first); validate_error_is_one_of would suit, but
        # ERR_REFERENCE_NOT_FOUND covers both.
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)


# ===========================================================================
# Pagination (PRD §2.3)
# ===========================================================================
class TestPagination:

    def test_pagination_meta_present_on_list(self, dispatcher_headers):
        """PRD §2.3: "The meta block of every list response includes limit,
        offset, total_count, and has_more."

        Claim: GET list endpoint returns the four pagination meta fields.
        """
        # Seed a few stops so total_count > 0.
        for _ in range(3):
            create_active_stop()
        data, meta = validate_paginated(
            api_client.list_stops(dispatcher_headers, params={"limit": 2}),
        )
        assert "limit" in meta
        assert "offset" in meta
        assert "total_count" in meta
        assert "has_more" in meta
        assert isinstance(meta["total_count"], int)
        assert isinstance(meta["has_more"], bool)
        assert len(data) <= 2

    @pytest.mark.parametrize("bad_params", [
        {"limit": 0},
        {"limit": 101},
        {"limit": -1},
        {"offset": -1},
    ])
    def test_invalid_pagination_rejected(self, dispatcher_headers, bad_params):
        """PRD §2.3: "The limit parameter is an integer, defaults to 10, has
        a minimum of 1, and a maximum of 100; the offset parameter is an
        integer, defaults to 0, with a minimum of 0. Any value outside
        these bounds, or any non-integer value, is rejected with
        ERR_INVALID_PAGINATION."

        Claim: limit/offset outside bounds -> ERR_INVALID_PAGINATION.
        """
        resp = api_client.list_stops(dispatcher_headers, params=bad_params)
        validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION)

    def test_offset_beyond_total_returns_empty(self, dispatcher_headers):
        """PRD §2.3: "The meta block of every list response includes limit,
        offset, total_count, and has_more."

        Claim: very large offset -> empty data list, has_more=False.
        """
        data, meta = validate_paginated(
            api_client.list_stops(
                dispatcher_headers,
                params={"limit": 10, "offset": 99_999},
            ),
        )
        assert data == []
        assert meta["has_more"] is False
