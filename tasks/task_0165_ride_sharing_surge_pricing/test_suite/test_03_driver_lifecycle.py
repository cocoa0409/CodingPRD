"""Driver lifecycle: go-online / go-offline, airport queue branching."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_airport_queue_row,
    assert_driver,
    create_and_online_driver,
    create_driver,
    create_grid,
    driver_go_offline,
    driver_go_online,
    find_in_list,
    get_driver,
    get_grid,
    go_online_payload,
    join_airport_queue,
    leave_airport_queue,
    list_airport_queue,
    make_driver_headers,
    setup_airport_grid_with_queued_driver,
    setup_grid_with_supply,
    validate_error,
    validate_success,
)


# ===========================================================================
# go-online / go-offline transitions.
# ===========================================================================
class TestGoOnlineOffline:

    def test_create_driver_initial_state_offline(self):
        """PRD §3.2: "the driver starts in OFFLINE status, with
        current_grid_code null, quest_id null, quest_completed_rides at
        zero, and total_earnings_cents at zero."
        """
        driver = create_driver()
        assert driver["status"] == "OFFLINE"
        assert driver["current_grid_code"] is None
        assert driver["quest_id"] is None
        assert driver["quest_completed_rides"] == 0
        assert driver["total_earnings_cents"] == 0

    def test_go_online_transitions_to_available(self):
        """PRD §3.2: "the transition advances status from OFFLINE to
        AVAILABLE, sets current_grid_code to that grid_code, increments
        the destination grid's active_driver_count by 1, and triggers a
        fresh surge recomputation on that grid."
        """
        grid = create_grid()
        driver = create_driver()
        result = driver_go_online(driver["id"], grid["code"])
        assert result["status"] == "AVAILABLE"
        assert result["current_grid_code"] == grid["code"]
        grid_after = get_grid(grid["id"])
        assert grid_after["active_driver_count"] == 1

    def test_go_offline_resets_grid_code(self):
        """PRD §3.2: "Going offline reverses these effects: from
        AVAILABLE, the driver returns to OFFLINE, the grid's
        active_driver_count is decremented by 1, the grid's multiplier
        is recomputed, and current_grid_code is set to null."
        """
        grid, drivers = setup_grid_with_supply(num_drivers=1)
        d = drivers[0]
        result = driver_go_offline(d["id"])
        assert result["status"] == "OFFLINE"
        assert result["current_grid_code"] is None
        grid_after = get_grid(grid["id"])
        assert grid_after["active_driver_count"] == 0

    def test_go_online_from_already_available_is_invalid_state(self, api):
        """PRD §2.9 (seventh): "state preconditions ... yield
        ERR_INVALID_STATE on any state-transition endpoint."
        PRD §3.2 (Driver state machine §1.2): go-online requires
        Driver.status == OFFLINE.
        """
        grid, drivers = setup_grid_with_supply(num_drivers=1)
        d = drivers[0]
        resp = api.go_online(
            d["id"], go_online_payload(grid["code"]),
            make_driver_headers(d["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_go_offline_from_offline_is_invalid_state(self, api):
        """PRD §3.2: go-offline requires Driver.status == AVAILABLE."""
        d = create_driver()
        resp = api.go_offline(d["id"], make_driver_headers(d["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Airport queue — branching from AVAILABLE.
# ===========================================================================
class TestAirportQueue:

    def test_join_airport_queue_succeeds_from_available(self, api):
        """PRD §3.2: "A driver who is AVAILABLE and physically located
        in a grid whose is_airport flag is true may join the queue."
        Side effects: "writes a new AirportQueue row whose position is
        one greater than the current maximum position in that grid and
        whose joined_at is set to the current server time; the driver's
        status advances to IN_AIRPORT_QUEUE; the grid's
        active_driver_count is decremented by one (queued drivers do
        not count toward supply); the grid's surge is recomputed."
        # difficulty: non_linear_state_machine/driver_branching_airport_queue_dimension
        """
        grid = create_grid(is_airport=True)
        driver = create_and_online_driver(grid["code"])
        from test_helpers import airport_queue_join_payload
        resp = api.airport_queue_join(
            airport_queue_join_payload(grid["code"]),
            make_driver_headers(driver["id"]),
        )
        row = validate_success(resp, expected_status=201)
        assert_airport_queue_row(row)
        assert row["position"] == 1
        # Driver moved to IN_AIRPORT_QUEUE.
        d_after = get_driver(driver["id"])
        assert d_after["status"] == "IN_AIRPORT_QUEUE"
        # Active count decremented (queued drivers do NOT count).
        grid_after = get_grid(grid["id"])
        assert grid_after["active_driver_count"] == 0, (
            "PRD §3.2: queued drivers do NOT count toward supply."
        )

    def test_join_airport_queue_assigns_sequential_positions(self):
        """PRD §3.2: position is "one greater than the current maximum
        position in that grid"."""
        grid = create_grid(is_airport=True)
        d1 = create_and_online_driver(grid["code"])
        d2 = create_and_online_driver(grid["code"])
        d3 = create_and_online_driver(grid["code"])
        r1 = join_airport_queue(d1["id"], grid["code"])
        r2 = join_airport_queue(d2["id"], grid["code"])
        r3 = join_airport_queue(d3["id"], grid["code"])
        assert r1["position"] == 1
        assert r2["position"] == 2
        assert r3["position"] == 3

    def test_join_non_airport_grid_rejected(self, api):
        """PRD §2.9 (ninth): "on POST /airport-queue/join the target
        grid's is_airport flag must be true, otherwise
        ERR_NOT_AIRPORT_GRID."
        """
        grid = create_grid(is_airport=False)
        driver = create_and_online_driver(grid["code"])
        from test_helpers import airport_queue_join_payload
        resp = api.airport_queue_join(
            airport_queue_join_payload(grid["code"]),
            make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_AIRPORT_GRID.value)

    def test_join_when_driver_in_wrong_grid_rejected(self, api):
        """PRD §2.9 (tenth): "also on POST /airport-queue/join, the
        joining driver's current_grid_code must match the request
        body's grid_code, otherwise ERR_DRIVER_NOT_IN_GRID."
        """
        airport = create_grid(is_airport=True)
        other = create_grid(is_airport=False)
        # Driver online at OTHER grid, tries to join AIRPORT queue.
        driver = create_and_online_driver(other["code"])
        from test_helpers import airport_queue_join_payload
        resp = api.airport_queue_join(
            airport_queue_join_payload(airport["code"]),
            make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DRIVER_NOT_IN_GRID.value)

    def test_leave_airport_queue_renumbers_subsequent_positions(self):
        """PRD §3.2: "Leaving the queue voluntarily moves status back
        to AVAILABLE, deletes the driver's queue row, re-numbers the
        remaining rows so that each later position decrements by one
        (preserving the dense, unique 1-indexed ordering), increments
        the grid's active_driver_count by one, and recomputes the
        grid's surge."
        """
        grid = create_grid(is_airport=True)
        d1 = create_and_online_driver(grid["code"])
        d2 = create_and_online_driver(grid["code"])
        d3 = create_and_online_driver(grid["code"])
        join_airport_queue(d1["id"], grid["code"])  # pos 1
        join_airport_queue(d2["id"], grid["code"])  # pos 2
        join_airport_queue(d3["id"], grid["code"])  # pos 3
        # D2 leaves; remaining positions become D1=1, D3=2.
        leave_airport_queue(d2["id"])
        queue = list_airport_queue(grid["code"])
        d1_row = find_in_list(queue, driver_id=d1["id"])
        d3_row = find_in_list(queue, driver_id=d3["id"])
        assert d1_row is not None and d1_row["position"] == 1
        assert d3_row is not None and d3_row["position"] == 2, (
            "PRD §3.2: positions after a leave are renumbered dense."
        )
        # Driver D2 is now AVAILABLE again.
        d2_after = get_driver(d2["id"])
        assert d2_after["status"] == "AVAILABLE"
        # Grid count restored to 1 (D2 back in the active pool).
        grid_after = get_grid(grid["id"])
        assert grid_after["active_driver_count"] == 1

    def test_airport_branching_population_conservation(self):
        """PRD §3.2 forward + compensating: join then leave restores the
        original state. Verifies the conservation invariant.
        # difficulty: compensating_invariant/airport_queue_position_count_conservation
        """
        airport = create_grid(is_airport=True, rush_hour_eligible=False)
        d1 = create_and_online_driver(airport["code"])
        # Before join: active=1, queue empty.
        g = get_grid(airport["id"])
        assert g["active_driver_count"] == 1
        # After join: active=0, queue=1.
        join_airport_queue(d1["id"], airport["code"])
        g_after_join = get_grid(airport["id"])
        assert g_after_join["active_driver_count"] == 0
        queue_after_join = list_airport_queue(airport["code"])
        assert len(queue_after_join) == 1
        # After leave: active=1, queue empty (population restored).
        leave_airport_queue(d1["id"])
        g_after_leave = get_grid(airport["id"])
        assert g_after_leave["active_driver_count"] == 1
        queue_after_leave = list_airport_queue(airport["code"])
        assert len(queue_after_leave) == 0
        # Driver's status and grid restored.
        d1_after = get_driver(d1["id"])
        assert d1_after["status"] == "AVAILABLE"
        assert d1_after["current_grid_code"] == airport["code"]

    def test_branching_at_airport_vs_regular_grid(self):
        """PRD §3.2: branching fork — from AVAILABLE the driver may go
        directly to EN_ROUTE_PICKUP (regular dispatch) OR detour
        through IN_AIRPORT_QUEUE before EN_ROUTE_PICKUP. The two
        branches have different side-effect sets — entering
        IN_AIRPORT_QUEUE decrements active_driver_count separately
        from a regular dispatch.
        # difficulty: non_linear_state_machine/driver_branching_airport_queue_dimension
        """
        scenario = setup_airport_grid_with_queued_driver()
        # D1 (airport, queued) has different status and contributes
        # differently to supply than D2 (non-airport, AVAILABLE).
        assert scenario["d1"]["status"] == "IN_AIRPORT_QUEUE"
        assert scenario["d2"]["status"] == "AVAILABLE"
        assert scenario["airport"]["active_driver_count"] == 0, (
            "PRD §3.2: queued driver removed from supply count."
        )
        assert scenario["g002"]["active_driver_count"] == 1
        # And a queue row exists for D1.
        queue = list_airport_queue(scenario["airport"]["code"])
        d1_row = find_in_list(queue, driver_id=scenario["d1"]["id"])
        assert d1_row is not None
        assert d1_row["position"] == 1
