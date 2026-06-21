"""Resource-temporal overlap (technician buffered-closed windows vs vehicle
half-open occupancy) and optimistic-concurrency control on task creation and
plan switching.
"""
from test_helpers import (
    validate_success,
    validate_error,
    make_rider_headers,
    ApiErrorId,
    TEST_USERS,
    fixtures as fx,
)

_ADMIN = TEST_USERS["admin_headers"]


def test_technician_buffered_window_overlap_rejected(api):
    """PRD §3.7: "It also enforces a buffered no-overlap rule: the task's window,
    widened by 600 seconds on each side to form the closed interval from
    `window_start` minus 600 seconds through `window_end` plus 600 seconds, must
    not overlap the (identically buffered) window of any other task already
    `ASSIGNED` to that same technician; an overlap is rejected with
    `ERR_TECH_WINDOW_OVERLAP`."

    Task 1 window 10:00-11:00 is assigned to a technician. Task 2 starts at 11:05,
    only 300s after task 1 ends — within the 600s buffer — so the buffered
    intervals collide and assignment returns ERR_TECH_WINDOW_OVERLAP (409).

    Design: Difficulty/resource_temporal_overlap/technician_assigned_windows_buffered_overlap_rejected
    """
    zone = fx.create_zone(zone_type="RIDE_OK", priority=5)
    technician = fx.create_technician(zone["id"], name="Tech T")
    veh1 = fx.create_vehicle(zone["id"], qr_code="QR-O1", battery_pct=50)
    veh2 = fx.create_vehicle(zone["id"], qr_code="QR-O2", battery_pct=50)
    task1, _ = fx.create_move_task(veh1, zone["id"], "2026-06-12T10:00:00Z", "2026-06-12T11:00:00Z")
    task2, _ = fx.create_move_task(veh2, zone["id"], "2026-06-12T11:05:00Z", "2026-06-12T12:00:00Z")
    fx.assign_task(task1, technician)
    resp = api.assign_rebalancing_task(task2["id"], {"technician_id": technician["id"]}, _ADMIN)
    validate_error(resp, ApiErrorId.ERR_TECH_WINDOW_OVERLAP.value)


def test_technician_window_outside_buffer_assigns_successfully(api):
    """PRD §3.7: "It also enforces a buffered no-overlap rule: the task's window,
    widened by 600 seconds on each side to form the closed interval from
    `window_start` minus 600 seconds through `window_end` plus 600 seconds, must
    not overlap the (identically buffered) window of any other task already
    `ASSIGNED` to that same technician; an overlap is rejected with
    `ERR_TECH_WINDOW_OVERLAP`."

    Task 1 ends at 11:00; task 2 starts at 11:25 — 1500s later, well outside the
    600s+600s buffer span, so the buffered intervals do NOT collide and the second
    assignment succeeds (task 2 -> ASSIGNED). This pins the buffer boundary from
    the accepting side.

    Design: Difficulty/resource_temporal_overlap/technician_assigned_windows_buffered_overlap_rejected
    """
    zone = fx.create_zone(zone_type="RIDE_OK", priority=5)
    technician = fx.create_technician(zone["id"], name="Tech T")
    veh1 = fx.create_vehicle(zone["id"], qr_code="QR-OB1", battery_pct=50)
    veh2 = fx.create_vehicle(zone["id"], qr_code="QR-OB2", battery_pct=50)
    task1, _ = fx.create_move_task(veh1, zone["id"], "2026-06-12T10:00:00Z", "2026-06-12T11:00:00Z")
    task2, _ = fx.create_move_task(veh2, zone["id"], "2026-06-12T11:25:00Z", "2026-06-12T12:00:00Z")
    fx.assign_task(task1, technician)
    assigned = validate_success(
        api.assign_rebalancing_task(task2["id"], {"technician_id": technician["id"]}, _ADMIN))
    assert assigned["status"] == "ASSIGNED", f"expected ASSIGNED, got {assigned['status']}"


def test_vehicle_occupied_in_use_blocks_second_start(api):
    """PRD §3.3: "The vehicle must currently be `AVAILABLE`; a vehicle that is
    already reserved or in use cannot be unlocked again, and such an attempt is
    rejected with `ERR_VEHICLE_NOT_AVAILABLE`."

    The closed side of the half-open occupancy: while rider 1's trip still holds
    the vehicle IN_USE, rider 2's start is rejected with ERR_VEHICLE_NOT_AVAILABLE
    (409).

    Design: Difficulty/resource_temporal_overlap/vehicle_no_overlapping_active_trip_half_open
    """
    plan = fx.create_standard_plan()
    zone = fx.create_zone(zone_type="RIDE_OK", priority=5)
    vehicle = fx.create_vehicle(zone["id"])
    rider1 = fx.create_funded_rider(plan["id"])
    rider2 = fx.create_funded_rider(plan["id"])
    fx.start_trip(rider1, vehicle, "2026-06-13T00:00:00Z")
    headers2 = make_rider_headers(rider2["id"])
    resp = api.create_trip({"rider_id": rider2["id"], "vehicle_id": vehicle["id"]}, headers2)
    validate_error(resp, ApiErrorId.ERR_VEHICLE_NOT_AVAILABLE.value)


def test_vehicle_half_open_occupancy_allows_immediate_reuse(api):
    """PRD §3.3: "The vehicle must currently be `AVAILABLE`; a vehicle that is
    already reserved or in use cannot be unlocked again, and such an attempt is
    rejected with `ERR_VEHICLE_NOT_AVAILABLE`."
    PRD §3.5: "and if its `battery_pct` is at least 20 it transitions
    `IN_USE → AVAILABLE`."

    Rider 1 ends a trip at 00:05:00, returning the vehicle to AVAILABLE; rider 2
    immediately starts a new trip on the same vehicle (half-open, end-exclusive
    occupancy), which succeeds 201 ACTIVE.

    Design: Difficulty/resource_temporal_overlap/vehicle_no_overlapping_active_trip_half_open
    """
    plan = fx.create_standard_plan()
    zone = fx.create_zone(zone_type="RIDE_OK", priority=5)
    vehicle = fx.create_vehicle(zone["id"])
    rider1 = fx.create_funded_rider(plan["id"])
    rider2 = fx.create_funded_rider(plan["id"])
    trip1 = fx.start_trip(rider1, vehicle, "2026-06-13T00:00:00Z")
    fx.end_trip(rider1, trip1, zone["id"], "2026-06-13T00:05:00Z")
    headers2 = make_rider_headers(rider2["id"])
    resp = api.create_trip({"rider_id": rider2["id"], "vehicle_id": vehicle["id"]}, headers2)
    trip2 = validate_success(resp, 201)
    assert trip2["status"] == "ACTIVE", f"expected ACTIVE, got {trip2['status']}"


def test_occ_stale_vehicle_version_on_task_create_rejected(api):
    """PRD §2.7: "If the vehicle's version has advanced since the client last read
    it — for instance because the vehicle was sent to maintenance, or because an
    earlier swap task already superseded the operator's intent — the create is
    rejected with `ERR_STALE_VEHICLE_VERSION` (HTTP 412), preventing the operator
    from scheduling work against a stale view of the vehicle."
    PRD §2.7: "A successful create increments the vehicle's `version`."

    A first task create bumps the vehicle's version; a second create still carrying
    the pre-advance expected_vehicle_version is rejected with
    ERR_STALE_VEHICLE_VERSION (412).

    Design: Corner/cross_cutting_complexity_layers/occ_stale_vehicle_version_on_task_create_returns_412
    """
    zone = fx.create_zone(zone_type="RIDE_OK", priority=5)
    vehicle = fx.create_vehicle(zone["id"], battery_pct=50)
    original_version = vehicle["version"]
    # First create advances the vehicle version.
    validate_success(api.create_rebalancing_task({
        "vehicle_id": vehicle["id"], "task_type": "MOVE", "target_zone_id": zone["id"],
        "window_start": "2026-07-21T10:00:00Z", "window_end": "2026-07-21T11:00:00Z",
        "expected_vehicle_version": original_version,
    }, _ADMIN), 201)
    # Second create reuses the now-stale version.
    resp = api.create_rebalancing_task({
        "vehicle_id": vehicle["id"], "task_type": "MOVE", "target_zone_id": zone["id"],
        "window_start": "2026-07-21T14:00:00Z", "window_end": "2026-07-21T15:00:00Z",
        "expected_vehicle_version": original_version,
    }, _ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_VEHICLE_VERSION.value)


def test_occ_correct_vehicle_version_succeeds_and_bumps(api):
    """PRD §2.7: "The create request must carry `expected_vehicle_version` matching
    the current `version` of the `Vehicle` named by `vehicle_id`."
    PRD §2.7: "A successful create increments the vehicle's `version`."

    A task create carrying the vehicle's current version succeeds (201) and bumps
    Vehicle.version by 1.

    Design: Corner/cross_cutting_complexity_layers/occ_correct_vehicle_version_succeeds
    """
    zone = fx.create_zone(zone_type="RIDE_OK", priority=5)
    vehicle = fx.create_vehicle(zone["id"], battery_pct=50)
    before = vehicle["version"]
    validate_success(api.create_rebalancing_task({
        "vehicle_id": vehicle["id"], "task_type": "MOVE", "target_zone_id": zone["id"],
        "window_start": "2026-07-22T10:00:00Z", "window_end": "2026-07-22T11:00:00Z",
        "expected_vehicle_version": before,
    }, _ADMIN), 201)
    veh_after = validate_success(api.get_vehicle(vehicle["id"], _ADMIN))
    assert veh_after["version"] == before + 1, (
        f"expected version {before + 1}, got {veh_after['version']}")


def test_occ_stale_rider_version_on_change_plan_rejected(api):
    """PRD §2.7: "If another writer has advanced the rider's version since the
    client last read it — for instance by already changing the plan — the request
    is rejected with `ERR_STALE_RIDER_VERSION` (HTTP 412)."

    A rider read at version v0; a topup advances the version; a change-plan to
    LOW_INCOME (with an approved application present) carrying the pre-topup
    expected_rider_version is rejected with ERR_STALE_RIDER_VERSION (412).

    Design: Corner/cross_cutting_complexity_layers/occ_stale_rider_version_on_change_plan_returns_412
    """
    std = fx.create_standard_plan()
    li = fx.create_low_income_plan()
    rider = fx.create_rider(std["id"])
    v0 = rider["version"]
    headers = make_rider_headers(rider["id"])
    app = validate_success(api.create_low_income_application(
        {"rider_id": rider["id"], "household_size": 1, "annual_income_cents": 2000000}, headers), 201)
    validate_success(api.approve_low_income_application(app["id"], _ADMIN))
    # Topup advances the rider version past v0.
    validate_success(api.topup_rider(rider["id"], {"amount_cents": 1000}, headers), 201)
    resp = api.change_plan(rider["id"], {"plan_id": li["id"], "expected_rider_version": v0}, headers)
    validate_error(resp, ApiErrorId.ERR_STALE_RIDER_VERSION.value)
