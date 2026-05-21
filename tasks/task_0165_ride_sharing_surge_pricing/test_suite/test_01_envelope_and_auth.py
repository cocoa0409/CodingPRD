"""Envelope shape, auth headers, RBAC, ownership, and 404 cascade."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_completed_ride,
    create_driver,
    create_grid,
    create_requested_ride,
    create_rider,
    driver_go_online,
    make_driver_headers,
    make_rider_headers,
    setup_completed_ride_with_known_fare,
    setup_grid_with_supply,
    validate_error,
    validate_success,
)


# ===========================================================================
# Success envelope — PRD §2.2.
# ===========================================================================
class TestSuccessEnvelope:

    def test_create_grid_success_envelope(self, api, admin_headers):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their
        JSON body" — meta, response_type, data.
        """
        from test_helpers import create_grid_payload
        payload = create_grid_payload(is_airport=False,
                                      rush_hour_eligible=True)
        resp = api.create_grid(payload, admin_headers)
        body = resp.json()
        assert "meta" in body
        assert "response_type" in body
        assert body["response_type"] == "object"
        assert "data" in body
        assert body["meta"]["api_request_id"].startswith("req_"), (
            "PRD §2.2: api_request_id is a server-generated unique "
            "identifier for the request that starts with req_."
        )

    def test_list_grids_returns_array_envelope(self, api, admin_headers):
        """PRD §2.2: "The response_type is either 'object' for a single
        resource or 'array' for a list of resources."
        """
        # Ensure at least one grid exists.
        create_grid()
        resp = api.list_grids(admin_headers)
        body = resp.json()
        assert body["response_type"] == "array", (
            "PRD §2.2: list endpoints return response_type 'array'."
        )
        # PRD §2.3 pagination fields surfaced in meta.
        for field in ("limit", "offset", "total_count", "has_more"):
            assert field in body["meta"], (
                f"PRD §2.3: pagination field {field!r} must appear in meta."
            )


# ===========================================================================
# Auth headers — PRD §2.1.
# ===========================================================================
class TestAuthHeaders:

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "If either header is missing or malformed, the
        request is rejected with ERR_AUTH_MISSING."
        """
        bad = {"X-User-Role": "PlatformAdmin",
               "Content-Type": "application/json"}
        resp = api._request("GET", "/grids", headers=bad)
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: "If either header is missing or malformed, the
        request is rejected with ERR_AUTH_MISSING."
        """
        bad = {"X-User-ID": "some-id", "Content-Type": "application/json"}
        resp = api._request("GET", "/grids", headers=bad)
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_empty_user_id_header_rejected(self, api):
        """PRD §2.1: "If either header is missing or malformed, the
        request is rejected with ERR_AUTH_MISSING."
        """
        bad = {"X-User-ID": "", "X-User-Role": "PlatformAdmin",
               "Content-Type": "application/json"}
        resp = api._request("GET", "/grids", headers=bad)
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)


# ===========================================================================
# Role-not-permitted — PRD §2.1.
# ===========================================================================
class TestRoleForbidden:

    def test_rider_cannot_create_grid(self, api):
        """PRD §4 table: POST /grids is PlatformAdmin only. PRD §2.1:
        "If the header is present and well-formed but the supplied role
        is not permitted to call the requested endpoint, the response
        is ERR_FORBIDDEN."
        """
        rider = create_rider()
        from test_helpers import create_grid_payload
        resp = api.create_grid(
            create_grid_payload(),
            make_rider_headers(rider["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_driver_cannot_create_quest_bonus(self, api):
        """PRD §4 table: POST /quest-bonuses is PlatformAdmin only.
        PRD §2.1: ERR_FORBIDDEN."""
        driver = create_driver()
        from test_helpers import create_quest_bonus_payload
        resp = api.create_quest_bonus(
            create_quest_bonus_payload(),
            make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_dispute_ops_cannot_run_clock_advance(
            self, api, dispute_ops_headers):
        """PRD §4 table: POST /_clock/advance is PlatformAdmin only.
        PRD §2.1: ERR_FORBIDDEN."""
        resp = api.clock_advance(
            {"target_timestamp": "2099-01-01T00:00:00.000Z"},
            dispute_ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_rider_cannot_approve_dispute(self, api):
        """PRD §4 table: POST /disputes/{id}/approve is DisputeOps only.
        PRD §2.1: ERR_FORBIDDEN."""
        scenario = setup_completed_ride_with_known_fare(distance_km=5.0)
        from test_helpers import create_open_dispute
        dispute = create_open_dispute(
            scenario["ride"]["id"], scenario["rider"]["id"],
            requested_refund_cents=100,
        )
        resp = api.approve_dispute(
            dispute["id"],
            make_rider_headers(scenario["rider"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Ownership — PRD §2.1.
# ===========================================================================
class TestOwnership:

    def test_rider_cannot_cancel_other_riders_ride(self, api):
        """PRD §2.1: "ownership checks on a ride compare the resource's
        rider_id field to X-User-ID."
        PRD §2.9 (validation order, sixth): "rider-side ownership on
        POST /rides/{id}/cancel and on POST /disputes requires
        X-User-ID (under role Rider) to equal the resource's rider_id,
        otherwise ERR_NOT_OWNER."
        """
        grid, drivers = setup_grid_with_supply(num_drivers=1)
        owner = create_rider()
        intruder = create_rider()
        ride = create_requested_ride(owner["id"], grid["code"])
        resp = api.cancel_ride(
            ride["id"], make_rider_headers(intruder["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_OWNER.value)

    def test_driver_cannot_start_other_drivers_ride(self, api):
        """PRD §2.9 (validation order, fifth): "driver-side ownership on
        ride-progress and driver-management endpoints (POST
        /rides/{id}/start, POST /rides/{id}/complete, ...) requires the
        acting Driver.id (i.e., X-User-ID under role Driver) to equal
        the resource's driver_id or the path id, otherwise
        ERR_NOT_OWNER."
        """
        grid, drivers = setup_grid_with_supply(num_drivers=1)
        rider = create_rider()
        from test_helpers import assign_ride
        ride = create_requested_ride(rider["id"], grid["code"])
        assign_ride(ride["id"])
        # An UNASSOCIATED driver tries to /start.
        intruder = create_driver()
        resp = api.start_ride(
            ride["id"], make_driver_headers(intruder["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_OWNER.value)

    def test_driver_cannot_go_online_as_other_driver(self, api):
        """PRD §2.9 (validation order, fifth): driver-side ownership on
        POST /drivers/{id}/go-online requires the acting Driver.id
        (X-User-ID under role Driver) to equal the path id, otherwise
        ERR_NOT_OWNER."""
        target = create_driver()
        intruder = create_driver()
        grid = create_grid()
        from test_helpers import go_online_payload
        resp = api.go_online(
            target["id"], go_online_payload(grid["code"]),
            make_driver_headers(intruder["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_OWNER.value)


# ===========================================================================
# Path-id existence — PRD §2.8.
# ===========================================================================
class TestNotFound:

    def test_get_grid_nonexistent_returns_not_found(self, api,
                                                    admin_headers):
        """PRD §2.8: "Path identifiers are validated strictly
        left-to-right in their URL order. ... the first identifier in
        the path that does not reference an existing resource yields
        ERR_NOT_FOUND immediately."
        """
        resp = api.get_grid(NON_EXISTENT_UUID, admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_driver_nonexistent_returns_not_found(self, api,
                                                      admin_headers):
        """PRD §2.8: path-id existence yields ERR_NOT_FOUND on the
        first miss."""
        resp = api.get_driver(NON_EXISTENT_UUID, admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_ride_nonexistent_returns_not_found(self, api,
                                                    admin_headers):
        """PRD §2.8: path-id existence yields ERR_NOT_FOUND on the
        first miss."""
        resp = api.get_ride(NON_EXISTENT_UUID, admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_dispute_nonexistent_returns_not_found(
            self, api, dispute_ops_headers):
        """PRD §2.8: path-id existence yields ERR_NOT_FOUND on the
        first miss."""
        resp = api.get_dispute(NON_EXISTENT_UUID, dispute_ops_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# Foreign-key existence — PRD §2.8.
# ===========================================================================
class TestReferenceNotFound:

    def test_create_ride_with_nonexistent_pickup_grid(self, api):
        """PRD §2.8: "Foreign-key fields supplied in request bodies —
        including ... pickup_grid_code, dropoff_grid_code ... A foreign
        key that does not resolve produces ERR_REFERENCE_NOT_FOUND.
        This check applies to POST /rides, POST /disputes, and PATCH
        /drivers/{id}."
        """
        rider = create_rider()
        resp = api.create_ride(
            {"pickup_grid_code": "G-999", "dropoff_grid_code": "G-999",
             "distance_km": 3.0},
            make_rider_headers(rider["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)

    def test_create_dispute_with_nonexistent_ride_id(self, api):
        """PRD §2.8: ERR_REFERENCE_NOT_FOUND for POST /disputes when
        ride_id does not resolve."""
        rider = create_rider()
        resp = api.create_dispute(
            {"ride_id": NON_EXISTENT_UUID,
             "reason_code": "OVERCHARGE",
             "requested_refund_cents": 100},
            make_rider_headers(rider["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)
