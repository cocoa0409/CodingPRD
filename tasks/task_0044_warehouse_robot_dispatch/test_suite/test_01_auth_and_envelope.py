"""Authentication, role authorisation, not-found, and response envelope tests.

These tests verify the cross-cutting contract specified in PRD sections
2.1, 2.2, 2.6, and 2.7.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    advance_clock_payload,
    api_client,
    build_user_headers,
    create_fleet,
    create_fleet_payload,
    create_map_node_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    open_fault_payload,
    setup_empty_fleet,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class TestAuthentication:
    def test_missing_user_id_header_rejected(self, api):
        """PRD section 2.1: 'Every request to the API must carry two HTTP
        headers: X-User-ID, identifying the caller, and X-User-Role,
        naming the caller's role.' and 'A missing or unrecognised header
        pair is rejected with ERR_UNAUTHENTICATED (HTTP 401).'

        Claim: omitting X-User-ID -> ERR_UNAUTHENTICATED 401.
        """
        headers = {"X-User-Role": "FleetAdmin"}
        resp = api.create_fleet(create_fleet_payload(), headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_missing_user_role_header_rejected(self, api):
        """PRD section 2.1: 'A missing or unrecognised header pair is
        rejected with ERR_UNAUTHENTICATED (HTTP 401).'

        Claim: omitting X-User-Role -> ERR_UNAUTHENTICATED 401.
        """
        headers = {"X-User-ID": "anything"}
        resp = api.create_fleet(create_fleet_payload(), headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_unrecognised_role_rejected(self, api):
        """PRD section 2.1: 'Three roles are recognised, spelled exactly
        as follows: Operator, FleetAdmin, and WMS. A missing or
        unrecognised header pair is rejected with ERR_UNAUTHENTICATED
        (HTTP 401).'

        Claim: unknown role string -> ERR_UNAUTHENTICATED 401.
        """
        headers = build_user_headers("u-1", "SuperAdmin")
        resp = api.create_fleet(create_fleet_payload(), headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------
class TestRBAC:
    def test_operator_cannot_create_fleet(self, api, operator_headers):
        """PRD section 2.1: 'FleetAdmin owns configuration: fleet
        creation, map-node creation, map-edge creation, charging-station
        creation, and robot registration.' and section 2.1: 'A request
        whose role is recognised but not authorised for the endpoint
        (per the section 4 table) is rejected with ERR_FORBIDDEN
        (HTTP 403).'

        Claim: Operator calling POST /fleets -> ERR_FORBIDDEN 403.
        """
        resp = api.create_fleet(create_fleet_payload(), operator_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_wms_cannot_create_robot(self, api, wms_headers, fleet_admin_headers):
        """PRD section 2.1: 'FleetAdmin owns configuration: ... robot
        registration.' and 'A request whose role is recognised but not
        authorised for the endpoint (per the section 4 table) is
        rejected with ERR_FORBIDDEN (HTTP 403).'

        Claim: WMS calling POST /robots -> ERR_FORBIDDEN 403.
        """
        fleet = create_fleet(headers=fleet_admin_headers)
        node_resp = api.create_map_node(
            fleet["id"],
            create_map_node_payload(kind="LANE"),
            fleet_admin_headers,
        )
        node = validate_success(node_resp, expected_status=201)
        resp = api.create_robot(
            fleet["id"],
            {"code": "R1", "position_node_id": node["id"]},
            wms_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_operator_can_create_task(self, api, operator_headers, fleet_admin_headers):
        """PRD section 2.1: 'It also shares task creation with WMS,
        shares dispatch and clock advancement and fault opening with
        FleetAdmin, and shares all read endpoints with the other two
        roles.'

        Claim: Operator POST /tasks succeeds.
        """
        fleet = create_fleet(headers=fleet_admin_headers)
        p = validate_success(
            api.create_map_node(
                fleet["id"], create_map_node_payload(kind="LANE", x=0, y=0),
                fleet_admin_headers,
            ),
            expected_status=201,
        )
        d = validate_success(
            api.create_map_node(
                fleet["id"], create_map_node_payload(kind="LANE", x=1, y=0),
                fleet_admin_headers,
            ),
            expected_status=201,
        )
        validate_success(
            api.create_map_edge(
                fleet["id"],
                {"from_node_id": p["id"], "to_node_id": d["id"]},
                fleet_admin_headers,
            ),
            expected_status=201,
        )
        resp = api.create_task(
            fleet["id"],
            {
                "source": "INBOUND",
                "pickup_node_id": p["id"],
                "dropoff_node_id": d["id"],
            },
            operator_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "QUEUED"

    def test_wms_can_emit_event(self, api, wms_headers, fleet_admin_headers):
        """PRD section 2.1: 'WMS is exclusively the source of equipment
        and external task events emitted through the events endpoint.'

        Claim: WMS POST /events:emit succeeds (200).
        """
        fleet = create_fleet(headers=fleet_admin_headers)
        resp = api.emit_event(
            fleet["id"],
            {"event_kind": "WMS_SYNC"},
            wms_headers,
        )
        validate_success(resp, expected_status=200)


# ---------------------------------------------------------------------------
# Not found
# ---------------------------------------------------------------------------
class TestNotFound:
    def test_get_fleet_with_nonexistent_id_returns_404(self, api, operator_headers):
        """PRD section 2.6: 'Path-segment resolution proceeds strictly
        left to right: the fleet_id segment is resolved first ... The
        first segment whose target cannot be found yields ERR_NOT_FOUND
        (HTTP 404), and resolution stops at that point so that the
        response identifies the leftmost missing segment.'

        Claim: GET /fleets/{nonexistent} -> ERR_NOT_FOUND 404.
        """
        resp = api.get_fleet(NON_EXISTENT_UUID, operator_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_task_in_existing_fleet_with_nonexistent_id(
        self, api, operator_headers, fleet_admin_headers
    ):
        """PRD section 2.6: 'The first segment whose target cannot be
        found yields ERR_NOT_FOUND (HTTP 404).'

        Claim: GET /fleets/{ok}/tasks/{nonexistent} -> ERR_NOT_FOUND.
        """
        fleet = create_fleet(headers=fleet_admin_headers)
        resp = api.get_task(fleet["id"], NON_EXISTENT_UUID, operator_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------
class TestEnvelope:
    def test_success_envelope_has_meta_response_type_data(
        self, api, fleet_admin_headers
    ):
        """PRD section 2.2: 'All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their JSON
        body' showing meta with api_request_id, api_request_timestamp,
        and a top-level response_type and data field.

        Claim: a success response carries meta.api_request_id (starting
        req_), meta.api_request_timestamp (ISO 8601), response_type,
        and data.
        """
        resp = api.create_fleet(create_fleet_payload(), fleet_admin_headers)
        assert resp.status_code == 201
        body = resp.json()
        assert "meta" in body
        meta = body["meta"]
        assert "api_request_id" in meta and meta["api_request_id"].startswith(
            "req_"
        ), f"api_request_id must start with req_, got {meta.get('api_request_id')!r}"
        assert is_iso8601_timestamp(meta["api_request_timestamp"])
        assert body["response_type"] in ("object", "array")
        assert "data" in body
        # Data should carry the new fleet
        assert is_valid_uuid(body["data"]["id"])

    def test_error_envelope_has_error_id_and_message(self, api):
        """PRD section 2.2: 'All error API responses (4xx status codes)
        follow this standard envelope format' with response_type 'error'
        and data containing error_id and message.

        Claim: an error response carries response_type=='error' and
        data.error_id, data.message.
        """
        resp = api.create_fleet(create_fleet_payload(), {})
        assert resp.status_code == 401
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_UNAUTHENTICATED"
        assert isinstance(body["data"].get("message"), str)


# ---------------------------------------------------------------------------
# Bad request shape
# ---------------------------------------------------------------------------
class TestBadRequest:
    def test_advance_clock_with_zero_delta_rejected(self, api, operator_headers):
        """PRD section 2.4: 'Clock movement must be strictly forward:
        delta_seconds must be at least 1 and the resulting clock_now must
        be strictly greater than the current clock_now. A request that
        violates either condition is rejected with ERR_CLOCK_BACKWARDS.'

        Claim: delta_seconds=0 -> ERR_CLOCK_BACKWARDS 422.
        """
        fleet = setup_empty_fleet(headers=TEST_USERS["fleet_admin_headers"])
        resp = api.advance_clock(
            fleet["id"], advance_clock_payload(delta_seconds=0), operator_headers
        )
        validate_error(resp, ApiErrorId.ERR_CLOCK_BACKWARDS.value)

    def test_advance_clock_with_negative_delta_rejected(
        self, api, operator_headers
    ):
        """PRD section 2.4: 'delta_seconds must be at least 1 and the
        resulting clock_now must be strictly greater than the current
        clock_now. A request that violates either condition is rejected
        with ERR_CLOCK_BACKWARDS.'

        Claim: delta_seconds=-1 -> ERR_CLOCK_BACKWARDS 422.
        """
        fleet = setup_empty_fleet(headers=TEST_USERS["fleet_admin_headers"])
        resp = api.advance_clock(
            fleet["id"], advance_clock_payload(delta_seconds=-1), operator_headers
        )
        validate_error(resp, ApiErrorId.ERR_CLOCK_BACKWARDS.value)
