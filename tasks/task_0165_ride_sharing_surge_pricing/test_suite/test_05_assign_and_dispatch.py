"""Ride assignment: driver selection policy, cancellation, three-hop cascade."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_ride,
    assign_ride,
    create_and_online_driver,
    create_driver,
    create_grid,
    create_requested_ride,
    create_rider,
    driver_go_online,
    get_driver,
    get_grid,
    grid_code_with_numeric,
    join_airport_queue,
    list_airport_queue,
    make_driver_headers,
    make_rider_headers,
    setup_grid_with_supply,
    setup_three_hop_assign_cascade,
    setup_two_adjacent_grids,
    validate_error,
    validate_success,
)


# ===========================================================================
# Basic assign / cascade.
# ===========================================================================
class TestAssignBasic:

    def test_assign_requested_ride_succeeds_with_available_driver(self):
        """PRD §3.3: "Assignment is performed by a PlatformAdmin and is
        the bridge between REQUESTED and ASSIGNED." Side effects: ride
        gets driver_id, driver→EN_ROUTE_PICKUP, etc.
        """
        grid, drivers = setup_grid_with_supply(num_drivers=1)
        rider = create_rider()
        ride = create_requested_ride(rider["id"], grid["code"])
        assigned = assign_ride(ride["id"])
        assert assigned["status"] == "ASSIGNED"
        assert assigned["driver_id"] == drivers[0]["id"]

    def test_assign_three_hop_cascade(self):
        """PRD §3.3: depth-3 cascade — Ride.status REQUESTED→ASSIGNED;
        the selected driver's status advances to EN_ROUTE_PICKUP; the
        pickup grid's open_demand_count is decremented by 1, its
        active_driver_count is decremented by 1, and the surge is
        recomputed.
        # difficulty: transitive_cascade/assign_cascade_three_hops
        """
        scenario = setup_three_hop_assign_cascade()
        grid = scenario["grid"]
        # Before: active=1, demand=1, ratio=1.0 → multiplier=1.00.
        assert grid["active_driver_count"] == 1
        assert grid["open_demand_count"] == 1
        assert grid["current_multiplier"] == 1.00
        # Trigger.
        assigned = assign_ride(scenario["ride"]["id"])
        # Hop 1.
        assert assigned["status"] == "ASSIGNED"
        # Hop 2.
        driver_after = get_driver(scenario["driver"]["id"])
        assert driver_after["status"] == "EN_ROUTE_PICKUP", (
            "PRD §3.3: assignment advances driver status to "
            "EN_ROUTE_PICKUP."
        )
        # Hop 3.
        grid_after = get_grid(grid["id"])
        assert grid_after["active_driver_count"] == 0
        assert grid_after["open_demand_count"] == 0
        assert grid_after["current_multiplier"] == 1.00

    def test_assign_no_drivers_available_without_neighbor(self, api,
                                                          admin_headers):
        """PRD §3.3: "If no candidate exists, the request body may
        include allow_neighbor_grid set to true ... If even after the
        optional neighbor expansion no candidate exists, the
        assignment is rejected with ERR_NO_DRIVERS_AVAILABLE."
        # difficulty: cross_entity_state_dependency/ride_assign_requires_driver_available_pair
        """
        grid = create_grid()
        # Driver exists but is OFFLINE — not eligible.
        create_driver()
        rider = create_rider()
        ride = create_requested_ride(rider["id"], grid["code"])
        resp = api.assign_ride(ride["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_NO_DRIVERS_AVAILABLE.value)

    def test_assign_already_assigned_ride_invalid_state(self, api,
                                                       admin_headers):
        """PRD §2.9 (seventh): state precondition. Ride must be in
        REQUESTED, otherwise ERR_INVALID_STATE."""
        grid, drivers = setup_grid_with_supply(num_drivers=1)
        rider = create_rider()
        ride = create_requested_ride(rider["id"], grid["code"])
        assign_ride(ride["id"])
        # Second assign should fail.
        resp = api.assign_ride(ride["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Driver selection policy — PRD §3.3.
# ===========================================================================
class TestDriverSelection:

    def test_airport_grid_picks_queue_head(self):
        """PRD §3.3: "When the pickup grid's is_airport flag is true,
        the eligible candidate set is the airport-queue rows for that
        grid, ranked by position ascending; the head of the queue is
        selected (positions are unique within a grid, so no further
        tie-break is needed)."
        """
        airport = create_grid(is_airport=True)
        d1 = create_and_online_driver(airport["code"])
        d2 = create_and_online_driver(airport["code"])
        d3 = create_and_online_driver(airport["code"])
        # Queue order: D1 (pos 1), D2 (pos 2), D3 (pos 3).
        join_airport_queue(d1["id"], airport["code"])
        join_airport_queue(d2["id"], airport["code"])
        join_airport_queue(d3["id"], airport["code"])
        rider = create_rider()
        ride = create_requested_ride(rider["id"], airport["code"])
        assigned = assign_ride(ride["id"])
        assert assigned["driver_id"] == d1["id"], (
            "PRD §3.3: airport grid picks the head of the queue."
        )
        # D1 removed from queue; remaining renumbered.
        queue_after = list_airport_queue(airport["code"])
        assert len(queue_after) == 2
        # PRD §3.3 / §3.2: "remaining queue rows are renumbered so that
        # each later position decrements by one."
        positions = sorted(row["position"] for row in queue_after)
        assert positions == [1, 2]

    def test_airport_grid_falls_through_when_queue_empty(self):
        """PRD §3.3: "If the airport queue is empty for that grid, the
        policy falls through to the non-airport branch on the same
        pickup grid."
        """
        airport = create_grid(is_airport=True)
        # Driver AVAILABLE at airport but NOT queued.
        d = create_and_online_driver(airport["code"])
        rider = create_rider()
        ride = create_requested_ride(rider["id"], airport["code"])
        assigned = assign_ride(ride["id"])
        assert assigned["driver_id"] == d["id"], (
            "PRD §3.3: when the airport queue is empty, fallback picks "
            "an AVAILABLE driver in the same grid."
        )

    def test_allow_neighbor_grid_expands_candidate_set(self):
        """PRD §3.3: "the request body may include allow_neighbor_grid
        set to true: in that case, the candidate set expands to
        drivers whose status equals AVAILABLE and whose
        current_grid_code is lexicographically adjacent to the pickup
        grid in the sense that the numeric portion of the two grid
        codes differ by exactly one (so G-007 is adjacent to G-006 and
        G-008)."
        """
        grid_a, grid_b = setup_two_adjacent_grids()
        # Driver online at grid_b (adjacent), nothing at grid_a.
        d_b = create_and_online_driver(grid_b["code"])
        rider = create_rider()
        ride = create_requested_ride(rider["id"], grid_a["code"])
        assigned = assign_ride(ride["id"], allow_neighbor_grid=True)
        assert assigned["driver_id"] == d_b["id"], (
            "PRD §3.3: neighbor-grid expansion picks the driver in the "
            "adjacent grid."
        )


# ===========================================================================
# Start / Cancel — PRD §3.3.
# ===========================================================================
class TestStartAndCancel:

    def test_start_ride_transitions_to_on_trip(self):
        """PRD §3.3: "the only side effect is that the driver's status
        advances to ON_TRIP."
        """
        grid, drivers = setup_grid_with_supply(num_drivers=1)
        rider = create_rider()
        ride = create_requested_ride(rider["id"], grid["code"])
        assign_ride(ride["id"])
        from test_helpers import start_ride
        started = start_ride(ride["id"], drivers[0]["id"])
        assert started["status"] == "ON_TRIP"

    def test_cancel_requested_decrements_open_demand(self):
        """PRD §3.3: "Cancellation from REQUESTED decrements the pickup
        grid's open_demand_count by 1 and recomputes that grid's
        surge."
        """
        grid, drivers = setup_grid_with_supply(num_drivers=1)
        rider = create_rider()
        ride = create_requested_ride(rider["id"], grid["code"])
        # Verify demand=1 before cancel.
        g1 = get_grid(grid["id"])
        assert g1["open_demand_count"] == 1
        from test_helpers import cancel_ride
        canceled = cancel_ride(ride["id"], rider["id"])
        assert canceled["status"] == "CANCELED"
        g2 = get_grid(grid["id"])
        assert g2["open_demand_count"] == 0

    def test_cancel_assigned_restores_driver(self):
        """PRD §3.3: "Cancellation from ASSIGNED is more involved: the
        previously assigned driver's status reverts from
        EN_ROUTE_PICKUP to AVAILABLE, the driver's current_grid_code is
        left unchanged ..., the active count of that grid is
        incremented by 1, and that grid's surge is recomputed."
        """
        grid, drivers = setup_grid_with_supply(num_drivers=1)
        rider = create_rider()
        ride = create_requested_ride(rider["id"], grid["code"])
        assign_ride(ride["id"])
        # Driver is now EN_ROUTE_PICKUP, grid.active=0.
        g_assigned = get_grid(grid["id"])
        assert g_assigned["active_driver_count"] == 0
        from test_helpers import cancel_ride
        cancel_ride(ride["id"], rider["id"])
        # Driver back to AVAILABLE.
        d_after = get_driver(drivers[0]["id"])
        assert d_after["status"] == "AVAILABLE"
        # Grid active count incremented.
        g_after = get_grid(grid["id"])
        assert g_after["active_driver_count"] == 1

    def test_cancel_completed_ride_invalid_state(self, api):
        """PRD §3.3: cancel is allowed from either REQUESTED or
        ASSIGNED. Cancellation from any other state must yield
        ERR_INVALID_STATE per PRD §2.9 (seventh)."""
        from test_helpers import create_completed_ride
        grid, _ = setup_grid_with_supply(num_drivers=1)
        rider = create_rider()
        ride, _ = create_completed_ride(rider["id"], grid["code"])
        resp = api.cancel_ride(
            ride["id"], make_rider_headers(rider["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
