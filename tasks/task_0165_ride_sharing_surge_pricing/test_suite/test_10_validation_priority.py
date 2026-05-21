"""Validation-priority ordering: when two checks could fail, the
higher-priority one fires first per PRD §2.9.

Per the skill's silence-pattern rules: we ONLY assert priority ordering
when PRD prose explicitly names the precedence. PRD §2.9 enumerates a
fixed list "First ... Sixteenth" and §2.9's last paragraph gives the
canonical worked example. Both are sufficient verbatim PRD support."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    create_and_online_driver,
    create_completed_ride,
    create_dispute_payload,
    create_driver,
    create_grid,
    create_requested_ride,
    create_rider,
    make_driver_headers,
    make_rider_headers,
    setup_completed_ride_with_known_fare,
    setup_disputed_ride,
    setup_grid_with_supply,
    validate_error,
)


# ===========================================================================
# PRD §2.9 worked example (canonical) — state vs business_fiscal.
# ===========================================================================
class TestStateVsFiscalDispute:

    def test_dispute_already_exists_trumps_refund_exceeds_fare(self, api):
        """PRD §2.9 last paragraph: "The ordering is load-bearing. For
        example, if a rider sends a duplicate POST /disputes with a
        malformed requested_refund_cents, the higher-priority state and
        uniqueness checks fire before the fiscal validation, so the
        response is ERR_DISPUTE_ALREADY_EXISTS (not
        ERR_REFUND_EXCEEDS_FARE)."
        """
        scenario = setup_disputed_ride(distance_km=5.0,
                                       requested_refund_cents=100)
        # ride.final_fare_cents == 850. Try to file a second dispute
        # with refund=9999 (exceeds fare). Per PRD: existence check
        # wins → ERR_DISPUTE_ALREADY_EXISTS.
        resp = api.create_dispute(
            create_dispute_payload(
                ride_id=scenario["ride"]["id"],
                requested_refund_cents=9_999,
            ),
            make_rider_headers(scenario["rider"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DISPUTE_ALREADY_EXISTS.value)


# ===========================================================================
# state (priority 7) vs business_fiscal (priority 13) on dispute create.
# ===========================================================================
class TestStateOverFiscalOnDisputeCreate:

    def test_state_invalid_trumps_refund_exceeds_fare(self, api):
        """PRD §2.9: "Seventh, state preconditions (the target resource
        must be in a state from which the requested transition is
        allowed) yield ERR_INVALID_STATE on any state-transition
        endpoint." vs "Thirteenth, on dispute creation,
        requested_refund_cents must be strictly greater than zero and
        less than or equal to the underlying Ride.final_fare_cents,
        otherwise ERR_REFUND_EXCEEDS_FARE." Seventh fires before
        thirteenth.

        Setup: ride in ASSIGNED state (not COMPLETED) — state check
        fails — AND refund=9999 — fiscal check would also fail.
        State (priority 7) wins.
        # difficulty: priority_pair_validation_conflict/state_vs_business_fiscal_dispute_create
        """
        # Stage a Ride in ASSIGNED state.
        grid, _ = setup_grid_with_supply(num_drivers=1)
        rider = create_rider()
        from test_helpers import assign_ride
        ride = create_requested_ride(rider["id"], grid["code"],
                                     distance_km=5.0)
        assign_ride(ride["id"])
        # State check fails (ride NOT COMPLETED) AND refund=9999 would
        # exceed any possible final fare.
        resp = api.create_dispute(
            create_dispute_payload(
                ride_id=ride["id"], requested_refund_cents=9_999,
            ),
            make_rider_headers(rider["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Two business_constraint priorities — airport-grid before driver-grid.
# ===========================================================================
class TestAirportGridOverDriverGridOnJoin:

    def test_not_airport_grid_trumps_driver_not_in_grid(self, api):
        """PRD §2.9: "Ninth, on POST /airport-queue/join the target
        grid's is_airport flag must be true, otherwise
        ERR_NOT_AIRPORT_GRID." vs "Tenth, also on POST
        /airport-queue/join, the joining driver's current_grid_code
        must match the request body's grid_code, otherwise
        ERR_DRIVER_NOT_IN_GRID." Ninth fires before tenth.

        Stage: target grid is_airport=False AND driver is in a
        different grid. Ninth wins → ERR_NOT_AIRPORT_GRID.
        # difficulty: priority_pair_validation_conflict/business_referential_vs_business_constraint_airport_join
        """
        non_airport = create_grid(is_airport=False, rush_hour_eligible=False)
        other = create_grid(is_airport=False, rush_hour_eligible=False)
        # Driver is in "other" grid, NOT in "non_airport".
        driver = create_and_online_driver(other["code"])
        from test_helpers import airport_queue_join_payload
        # Both grid is_airport=false AND driver not in target grid.
        resp = api.airport_queue_join(
            airport_queue_join_payload(non_airport["code"]),
            make_driver_headers(driver["id"]),
        )
        # Ninth priority fires.
        validate_error(resp, ApiErrorId.ERR_NOT_AIRPORT_GRID.value)


# ===========================================================================
# Auth precedes everything — PRD §2.9 first.
# ===========================================================================
class TestAuthBeforeOther:

    def test_missing_headers_trumps_invalid_payload(self, api):
        """PRD §2.9: "First, authentication: missing or malformed
        headers yield ERR_AUTH_MISSING."

        Even a payload missing required fields must yield AUTH_MISSING
        when headers are absent.
        """
        resp = api._request(
            "POST", "/rides",
            payload={"distance_km": -1},
            headers={"Content-Type": "application/json"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)


# ===========================================================================
# Role-forbidden precedes existence — PRD §2.9 second over third.
# ===========================================================================
class TestRoleBeforeExistence:

    def test_forbidden_role_trumps_not_found(self, api):
        """PRD §2.9: "Second, role authorization: a present-but-disallowed
        role yields ERR_FORBIDDEN." Then "Third, path-id existence
        (left-to-right) yields ERR_NOT_FOUND on the first miss." Role
        fires before existence.

        A Rider hits POST /grids (PlatformAdmin only) — but the
        endpoint doesn't have a path-id existence concern; pick
        PATCH /grids/{id} with a fake id and Rider role: role check
        (priority 2) trumps existence (priority 3).
        """
        rider = create_rider()
        from test_helpers import NON_EXISTENT_UUID
        resp = api.patch_grid(
            NON_EXISTENT_UUID, {"name": "x", "version": 1},
            make_rider_headers(rider["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
