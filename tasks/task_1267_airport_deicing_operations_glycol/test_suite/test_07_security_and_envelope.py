"""Tests for RBAC, response envelopes, pagination, and error shape."""
import pytest

from test_helpers import (

    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_airline,
    create_pad_payload,
    create_station,
    make_airline_rep_headers,
    setup_operation_spraying,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAuthentication:
    def test_missing_role_header_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, declaring the
        operational capacity in which they act. A request missing either
        header, or presenting a role value the system does not declare, is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_role_header_unauthenticated
        """
        resp = api.create_pad(
            create_pad_payload(NON_EXISTENT_UUID),
            headers={},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleDenial:
    def test_airline_rep_cannot_create_pad_forbidden(self, api):
        """PRD §2.1: "Once authenticated, the caller's role must be permitted
        on the target endpoint; a role violation, or an `AirlineRep` attempting
        to touch a resource belonging to a different airline, is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/airline_rep_cannot_create_pad_forbidden
        """
        station = create_station()
        airline = create_airline()
        resp = api.create_pad(
            create_pad_payload(station["id"]),
            make_airline_rep_headers(airline["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_inspector_cannot_complete_operation_forbidden(self, api):
        """PRD §2.1: "Once authenticated, the caller's role must be permitted
        on the target endpoint; a role violation... is rejected with
        `ERR_FORBIDDEN` (HTTP 403)." PRD §4: `POST
        /deice-ops/deice-operations/{id}/complete` is authorized for
        `PadOperator` only.

        Design: Corner/rbac/inspector_cannot_complete_operation_forbidden
        """
        station, permit, tank, pad, airline, request, operation = (
            setup_operation_spraying()
        )
        resp = api.complete_deice_operation(
            operation["id"],
            {"actual_liters": 100, "collected_liters": 60},
            TEST_USERS["inspector_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        resp = api.get_deice_operation(
            operation["id"], TEST_USERS["pad_operator_headers"]
        )
        assert validate_success(resp)["status"] == "SPRAYING"


class TestOwnershipScope:
    def test_airline_rep_scoped_to_own_airline(self, api):
        """PRD §2.1: "When `X-User-Role` is `AirlineRep`, `X-User-ID` is the
        `id` of the acting `Airline`; ownership checks on any resource that
        references an `Airline` (requests, invoices, the airline record itself)
        compare the resource's `airline_id` field to `X-User-ID`, and list
        results are restricted to that airline."

        Design: Corner/rbac/airline_rep_scoped_to_own_airline
        """
        airline_a = create_airline(code="AA", name="Air A")
        airline_b = create_airline(code="BB", name="Air B")

        # Cross-airline read is forbidden.
        resp = api.get_airline(
            airline_b["id"], make_airline_rep_headers(airline_a["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        # Own read succeeds.
        resp = api.get_airline(
            airline_a["id"], make_airline_rep_headers(airline_a["id"])
        )
        assert validate_success(resp)["code"] == "AA"


class TestResponseEnvelope:
    def test_create_response_envelope_shape(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body" with
        `meta` containing `api_request_id` and `api_request_timestamp`,
        `response_type` of "object" for a single resource, and `data`
        containing the resource object.
        PRD §3.1: "A new station starts with posture `NORMAL`,
        `active_supply_alert` false, an empty `collected_pool_liters` of zero,
        and `ops_epoch_index` at zero."

        Design: Corner/endpoints/create_response_envelope_shape
        """
        resp = api.create_station(
            {"code": "ST1", "name": "Station One"},
            TEST_USERS["station_admin_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert data["id"]
        assert data["posture"] == "NORMAL"
        assert data["active_supply_alert"] is False
        assert data["collected_pool_liters"] == 0
        assert data["ops_epoch_index"] == 0

    def test_list_pagination_envelope_fields(self, api):
        """PRD §2.3: "List endpoints accept two query parameters. The `limit`
        parameter caps the number of items returned; it defaults to 10, with a
        minimum of 1 and a maximum of 100. The `offset` parameter skips that
        many items from the front of the result set and defaults to 0. All list
        endpoints sort by `created_at` in ascending order unless otherwise
        specified. The `meta` object of a list response carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/list_pagination_envelope_fields
        """
        station = create_station()
        api.create_pad(
            create_pad_payload(station["id"], code="P1", max_size_class="SMALL"),
            TEST_USERS["station_admin_headers"],
        )
        api.create_pad(
            create_pad_payload(station["id"], code="P2", max_size_class="LARGE"),
            TEST_USERS["station_admin_headers"],
        )

        # Page 1.
        resp = api.list_pads(
            TEST_USERS["station_admin_headers"],
            params={"station_id": station["id"], "limit": 1, "offset": 0},
        )
        data, meta = validate_paginated(resp)
        assert len(data) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert meta["limit"] == 1
        assert meta["offset"] == 0

        # Page 2.
        resp = api.list_pads(
            TEST_USERS["station_admin_headers"],
            params={"station_id": station["id"], "limit": 1, "offset": 1},
        )
        data, meta = validate_paginated(resp)
        assert len(data) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert meta["limit"] == 1
        assert meta["offset"] == 1


class TestNotFound:
    def test_operation_get_not_found_returns_404(self, api):
        """PRD §2.8: "Existence of every referenced resource follows — path
        identifiers first, validated left-to-right, then body-referenced
        identifiers — yielding `ERR_NOT_FOUND`."

        Design: Corner/entities/operation_get_not_found_returns_404
        """
        resp = api.get_deice_operation(
            "123e4567-e89b-42d3-a456-426614174000",
            TEST_USERS["station_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestPadValidation:
    def test_pad_missing_code_returns_invalid_request(self, api):
        """PRD §2.8: "Independently of this business ordering, malformed
        payloads — missing required fields, bad enum values, malformed
        datetimes, a `window_end` not later than its `window_start`, or
        non-positive quantities — are rejected as request-shape errors with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/pad_missing_code_returns_invalid_request
        """
        station = create_station()
        payload = create_pad_payload(station["id"])
        del payload["code"]
        resp = api.create_pad(payload, TEST_USERS["station_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_pad_invalid_enum_returns_invalid_request(self, api):
        """PRD §2.8: "Independently of this business ordering, malformed
        payloads — missing required fields, bad enum values, malformed
        datetimes, a `window_end` not later than its `window_start`, or
        non-positive quantities — are rejected as request-shape errors with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/pad_invalid_enum_returns_invalid_request
        """
        station = create_station()
        payload = create_pad_payload(station["id"], max_size_class="HUGE")
        resp = api.create_pad(payload, TEST_USERS["station_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
