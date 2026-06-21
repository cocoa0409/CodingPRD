"""Routing and program-activation gates: capacity boundary, empty-collection guards,
the seasonal cross-entity gates, temporal-overlap rules, the validation-priority pair,
and the optimistic-concurrency check on route-stop creation.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_customer_property_system,
    create_customer,
    create_property,
    create_system,
    create_zone,
    create_technician,
    create_work_order,
    create_route,
    create_route_stop,
    create_program,
    fill_route_with_stops,
    winterize_then_startup_system,
    make_technician_headers,
    TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ===========================================================================
# Queue A — boundary_precision_check
# ===========================================================================
def test_ninth_route_stop_exceeds_capacity(api):
    """PRD §3.6: "the route's prospective stop count — its current `stops_used` plus one —
    would exceed the per-route maximum of 8 stops". PRD §3.6: "The stop-count limit bites
    only when the prospective count is strictly greater than 8."

    Design: Difficulty/boundary_precision_check/route_capacity_max_stops_boundary
    """
    _cust, _prop, sys = setup_customer_property_system(company_name="Cap Co")
    tech = create_technician(full_name="Cap Tech", shift_start_sec=0, shift_end_sec=86399)
    route_id, version, _wo_ids = fill_route_with_stops(
        sys["id"], tech["id"], n_stops=8, route_date="2026-05-03",
        window_minutes=10, start_spacing_sec=3600, first_start_sec=0)

    route = validate_success(api.get_route(route_id, DISPATCHER))
    assert route["stops_used"] == 8, f"route should hold 8 stops, got {route['stops_used']}"

    # The 9th stop (prospective_stops=9 > 8) must be rejected.
    w9 = create_work_order(sys["id"], job_type="HEAD_REPAIR",
                           estimated_minutes=10, estimated_cost_cents=1000)
    resp = api.create_route_stop(
        {"route_id": route_id, "work_order_id": w9["id"], "arrival_start_sec": 28800,
         "window_minutes": 10, "expected_route_version": version}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_ROUTE_CAPACITY_EXCEEDED.value)


def test_activate_program_with_zero_slots_rejected(api):
    """PRD §3.2: "its `slots` array must be non-empty (otherwise `ERR_EMPTY_PROGRAM`)".

    Design: Difficulty/boundary_precision_check/empty_program_zero_slots_rejected
    """
    _cust, _prop, sys = setup_customer_property_system(company_name="Emp Co")
    tech = create_technician(full_name="Emp Tech")
    prog = create_program(sys["id"], [])
    tech_headers = make_technician_headers(tech["id"])
    resp = api.activate_program(prog["id"], tech_headers)
    validate_error(resp, ApiErrorId.ERR_EMPTY_PROGRAM.value)


# ===========================================================================
# Queue A — cross_entity_state_dependency
# ===========================================================================
def test_startup_stop_blocked_on_non_winterized_system(api):
    """PRD §3.6: "If the work order's `job_type` is `STARTUP`, the serviced system's
    `season_state` must be `WINTERIZED` (otherwise `ERR_SEASON_STATE_BLOCKS_STARTUP`) — a
    system can only be started up after it has been winterized."

    Design: Difficulty/cross_entity_state_dependency/startup_schedule_requires_system_winterized
    """
    _cust, _prop, sys = setup_customer_property_system(company_name="Ce1 Co")
    tech = create_technician(full_name="Ce1 Tech")
    wo = create_work_order(sys["id"], job_type="STARTUP",
                           estimated_minutes=30, estimated_cost_cents=6000)
    route = create_route(tech["id"], route_date="2026-03-15")

    system = validate_success(api.get_system(sys["id"], DISPATCHER))
    assert system["season_state"] == "DORMANT"

    resp = api.create_route_stop(
        {"route_id": route["id"], "work_order_id": wo["id"], "arrival_start_sec": 28800,
         "window_minutes": 60, "expected_route_version": route["version"]}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_SEASON_STATE_BLOCKS_STARTUP.value)


def test_activate_program_blocked_when_season_not_active(api):
    """PRD §3.2: "the system's `season_state` must be `ACTIVE` (otherwise
    `ERR_SEASON_STATE_BLOCKS_PROGRAM`)".

    Design: Difficulty/cross_entity_state_dependency/program_activate_requires_season_active
    """
    _cust, _prop, sys = setup_customer_property_system(company_name="Ce2 Co")
    zone = create_zone(sys["id"], 1, plant_type="TURF", head_count=8, gpm_per_head=18)
    tech = create_technician(full_name="Ce2 Tech")
    prog = create_program(sys["id"], [{"zone_id": zone["id"], "start_sec": 21600, "run_minutes": 20}])

    system = validate_success(api.get_system(sys["id"], DISPATCHER))
    assert system["season_state"] == "DORMANT"

    tech_headers = make_technician_headers(tech["id"])
    resp = api.activate_program(prog["id"], tech_headers)
    validate_error(resp, ApiErrorId.ERR_SEASON_STATE_BLOCKS_PROGRAM.value)


# ===========================================================================
# Queue A — resource_temporal_overlap
# ===========================================================================
def test_route_stop_overlapping_existing_window_rejected(api):
    """PRD §3.6: "The new stop's window must not overlap the half-open window of any other
    `SCHEDULED` stop already on the same route (otherwise `ERR_ROUTESTOP_TIME_OVERLAP`)."

    Design: Difficulty/resource_temporal_overlap/route_stop_half_open_overlap_rejected_adjacent_allowed
    """
    _cust, _prop, sys = setup_customer_property_system(company_name="To1 Co")
    tech = create_technician(full_name="To1 Tech", shift_start_sec=0, shift_end_sec=86399)
    w1 = create_work_order(sys["id"], job_type="HEAD_REPAIR",
                           estimated_minutes=60, estimated_cost_cents=2000)
    w2 = create_work_order(sys["id"], job_type="HEAD_REPAIR",
                           estimated_minutes=60, estimated_cost_cents=2000)
    route = create_route(tech["id"], route_date="2026-05-04")
    # First stop occupies [28800, 32400).
    route_after = create_route_stop(route["id"], w1["id"], route["version"],
                                    arrival_start_sec=28800, window_minutes=60)
    # Second stop starts at 30000 — inside the first window — must be rejected.
    resp = api.create_route_stop(
        {"route_id": route["id"], "work_order_id": w2["id"], "arrival_start_sec": 30000,
         "window_minutes": 30, "expected_route_version": route_after["version"]}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_ROUTESTOP_TIME_OVERLAP.value)


def test_program_slot_adjacent_without_buffer_rejected(api):
    """PRD §3.2: "For a pair where the earlier slot ends at or before the later one begins,
    a conflict exists when the gap between the earlier slot's end and the later slot's start
    is less than the valve-switch buffer of 120 seconds. Because the comparison is strictly
    less than the buffer, two slots placed exactly end-to-end with no gap at all are
    rejected, not merely those that physically overlap. The first adjacent pair that
    violates the buffer causes the activation to be rejected with `ERR_PROGRAM_SLOT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/program_slot_buffered_overlap_rejected
    """
    cust = create_customer(company_name="To2 Co")
    prop = create_property(cust["id"])
    sys = create_system(prop["id"], static_psi=60)
    z1 = create_zone(sys["id"], 1, plant_type="TURF", head_count=8, gpm_per_head=18)
    z2 = create_zone(sys["id"], 2, plant_type="SHRUB", head_count=4, gpm_per_head=12)
    tech = create_technician(full_name="To2 Tech")
    winterize_then_startup_system(sys["id"], tech["id"], route_date="2026-10-02")

    # Slot A [21600, 22800), Slot B starts at 22800 — gap 0 < 120s buffer.
    prog = create_program(sys["id"], [
        {"zone_id": z1["id"], "start_sec": 21600, "run_minutes": 20},
        {"zone_id": z2["id"], "start_sec": 22800, "run_minutes": 20},
    ])
    tech_headers = make_technician_headers(tech["id"])
    resp = api.activate_program(prog["id"], tech_headers)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_SLOT_OVERLAP.value)


# ===========================================================================
# Queue A — priority_pair_validation_conflict
# ===========================================================================
def test_state_error_precedes_capacity_error_on_scheduled_workorder(api):
    """PRD §2.5: "State preconditions for the requested transition are checked fifth,
    yielding the state-specific conflict error described alongside each workflow. Then come
    the domain-specific business gates — the optimistic concurrency check, the backflow
    safety and device gates, the seasonal gates, the program and route structural gates,
    the temporal-overlap and capacity checks, and the empty-collection guards". PRD §3.6:
    "its `dispatch_status` must be `UNSCHEDULED` (otherwise `ERR_WORKORDER_ALREADY_SCHEDULED`)".

    Design: Difficulty/priority_pair_validation_conflict/schedule_state_beats_capacity_fiscal
    """
    _cust, _prop, sys = setup_customer_property_system(company_name="PP1 Co")
    # Short shift: 28800..30600 -> 30 minute capacity.
    tech = create_technician(full_name="Short Shift", shift_start_sec=28800, shift_end_sec=30600)
    wo = create_work_order(sys["id"], job_type="LEAK_REPAIR",
                           estimated_minutes=30, estimated_cost_cents=4000)
    route = create_route(tech["id"], route_date="2026-05-02")
    route_after = create_route_stop(route["id"], wo["id"], route["version"],
                                    arrival_start_sec=28800, window_minutes=30)
    route_now = validate_success(api.get_route(route["id"], DISPATCHER))

    # Re-schedule the SAME (now SCHEDULED) work order with a window that would also blow
    # capacity. The state check (ALREADY_SCHEDULED) precedes the capacity check.
    resp = api.create_route_stop(
        {"route_id": route["id"], "work_order_id": wo["id"], "arrival_start_sec": 60000,
         "window_minutes": 600, "expected_route_version": route_now["version"]}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_WORKORDER_ALREADY_SCHEDULED.value)


# ===========================================================================
# Queue B — errors / cross_cutting (OCC on route version)
# ===========================================================================
def test_stale_route_version_rejected_on_second_stop(api):
    """PRD §2.8: "The server compares `expected_route_version` to the route's current
    `version`. If they differ — because another writer has advanced the route's `version`
    since the client read it — the request is rejected with `ERR_STALE_ROUTE_VERSION`
    (HTTP 412), and no stop is created."

    Design: Corner/errors/stale_route_version_on_stop_create
    """
    _cust, _prop, sys = setup_customer_property_system(company_name="Occ Co")
    tech = create_technician(full_name="Occ Tech", shift_start_sec=0, shift_end_sec=86399)
    w1 = create_work_order(sys["id"], job_type="HEAD_REPAIR",
                           estimated_minutes=20, estimated_cost_cents=1000)
    w2 = create_work_order(sys["id"], job_type="HEAD_REPAIR",
                           estimated_minutes=20, estimated_cost_cents=1000)
    route = create_route(tech["id"], route_date="2026-05-10")
    stale_version = route["version"]
    # First stop advances the route version.
    create_route_stop(route["id"], w1["id"], stale_version, arrival_start_sec=0, window_minutes=30)

    # Second stop still carries the pre-first-stop version -> stale.
    resp = api.create_route_stop(
        {"route_id": route["id"], "work_order_id": w2["id"], "arrival_start_sec": 3600,
         "window_minutes": 30, "expected_route_version": stale_version}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_STALE_ROUTE_VERSION.value)


def test_route_stop_with_correct_version_succeeds_and_bumps_version(api):
    """PRD §3.6: "When a stop is accepted, the referenced work order's `dispatch_status`
    advances `UNSCHEDULED → SCHEDULED`... The route's `stops_used` and `minutes_committed`
    are recomputed, and the route's `version` is incremented by one".

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_and_increments
    """
    _cust, _prop, sys = setup_customer_property_system(company_name="OccOk Co")
    tech = create_technician(full_name="OccOk Tech")
    wo = create_work_order(sys["id"], job_type="HEAD_REPAIR",
                           estimated_minutes=20, estimated_cost_cents=1000)
    route = create_route(tech["id"], route_date="2026-05-12")
    assert route["version"] == 1

    stop = validate_success(api.create_route_stop(
        {"route_id": route["id"], "work_order_id": wo["id"], "arrival_start_sec": 28800,
         "window_minutes": 30, "expected_route_version": route["version"]}, DISPATCHER),
        expected_status=201)
    assert stop["stop_state"] == "SCHEDULED"

    route_now = validate_success(api.get_route(route["id"], DISPATCHER))
    assert route_now["stops_used"] == 1
    assert route_now["version"] == 2, f"route version should be 2, got {route_now['version']}"
