"""Entity creation, field shape, defaults, system-initialized fields,
list/pagination envelopes, reverse-reachability filters, and the MDS half-open
trip-count window.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    is_valid_uuid,
    make_rider_headers,
    ApiErrorId,
    TEST_USERS,
    fixtures as fx,
)

_ADMIN = TEST_USERS["admin_headers"]
_ANON = TEST_USERS["anonymous_headers"]
_REGULATOR = TEST_USERS["regulator_headers"]


# ---------------------------------------------------------------------------
# entities
# ---------------------------------------------------------------------------
def test_create_plan_returns_201_with_fields(api):
    """PRD §3.1: "A plan fixes a flat `unlock_fee_cents` charged at the start of
    every trip, a `per_minute_cents` rate applied to billable minutes, and a
    `daily_cap_cents` ceiling on the total fare of a single trip; a `daily_cap_cents`
    of 0 means the trip fare is uncapped."
    PRD §2.4: "The `id` is a server-minted UUID with no type prefix."
    PRD §2.4: "The `version` field is an integer that starts at its initial value
    and increments by one on every mutation."

    Creating a plan echoes the input rates and mints id/version server-side.

    Design: Corner/entities/create_plan_returns_201_with_all_fields
    """
    resp = api.create_plan({
        "code": "STANDARD", "unlock_fee_cents": 100, "per_minute_cents": 30,
        "daily_cap_cents": 0, "slow_zone_discount_pct": 0.25, "active": True,
    }, _ADMIN)
    plan = validate_success(resp, 201)
    assert plan["code"] == "STANDARD"
    assert plan["unlock_fee_cents"] == 100
    assert plan["per_minute_cents"] == 30
    assert plan["daily_cap_cents"] == 0
    assert plan["version"] == 1, f"expected version 1, got {plan['version']}"
    assert is_valid_uuid(plan["id"]), f"id must be a bare UUID, got {plan['id']!r}"


def test_get_vehicle_not_found(api):
    """PRD §2.8: "Existence is checked next: every resource named in the request
    path is validated left to right, and the first identifier that does not resolve
    to an existing resource yields `ERR_NOT_FOUND`."

    Fetching a vehicle by a non-existent UUID returns ERR_NOT_FOUND (404).

    Design: Corner/entities/get_vehicle_not_found_returns_404
    """
    resp = api.get_vehicle("00000000-0000-4000-8000-000000000000", _ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_vehicle_missing_qr_code_invalid_request(api):
    """PRD §2.8: "and finally field-level shape validation (`ERR_INVALID_REQUEST`)
    for missing required fields, invalid enum members, or out-of-range numeric
    values on any create or action body."
    PRD §3.1: "A **Vehicle** is registered with a `vehicle_type` of either
    `SCOOTER` or `EBIKE`, a unique `qr_code` scannable for unlock, an initial
    `battery_pct` (an integer from 0 to 100, defaulting to 100), and a
    `current_zone_id` naming the zone it is parked in."

    Omitting the required qr_code returns ERR_INVALID_REQUEST (400).

    Design: Corner/entities/create_vehicle_missing_required_qr_code_returns_invalid_request
    """
    zone = fx.create_zone(zone_type="RIDE_OK", priority=5)
    resp = api.create_vehicle({"vehicle_type": "SCOOTER", "current_zone_id": zone["id"]}, _ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_zone_invalid_enum_zone_type_invalid_request(api):
    """PRD §2.8: "and finally field-level shape validation (`ERR_INVALID_REQUEST`)
    for missing required fields, invalid enum members, or out-of-range numeric
    values on any create or action body."
    PRD §2.5: "The `zone_type` is one of `RIDE_OK`, `SLOW`, `NO_RIDE`, or
    `NO_PARK`."

    A zone_type outside the enum returns ERR_INVALID_REQUEST (400).

    Design: Corner/entities/create_zone_invalid_enum_zone_type_returns_invalid_request
    """
    resp = api.create_zone({"name": "Bad", "zone_type": "TELEPORT", "priority": 1}, _ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_vehicle_battery_defaults_to_100(api):
    """PRD §3.1: "A **Vehicle** is registered with a `vehicle_type` of either
    `SCOOTER` or `EBIKE`, a unique `qr_code` scannable for unlock, an initial
    `battery_pct` (an integer from 0 to 100, defaulting to 100), and a
    `current_zone_id` naming the zone it is parked in."
    PRD §3.1: "A vehicle's `status` is one of `AVAILABLE`, `RESERVED`, `IN_USE`,
    `LOW_BATTERY`, `MAINTENANCE`, or `RETIRED`, beginning at `AVAILABLE`."

    Omitting battery_pct applies the default 100; status begins AVAILABLE.

    Design: Corner/entities/vehicle_battery_pct_defaults_to_100_when_omitted
    """
    zone = fx.create_zone(zone_type="RIDE_OK", priority=5)
    resp = api.create_vehicle(
        {"vehicle_type": "EBIKE", "qr_code": "QR-DEF1", "current_zone_id": zone["id"]}, _ADMIN)
    vehicle = validate_success(resp, 201)
    assert vehicle["battery_pct"] == 100, f"expected default 100, got {vehicle['battery_pct']}"
    assert vehicle["status"] == "AVAILABLE", f"expected AVAILABLE, got {vehicle['status']}"


def test_rider_wallet_and_status_system_initialized(api):
    """PRD §3.2: "A rider's `wallet_balance_cents` begins at 0 and tracks prepaid
    funds; their `outstanding_fine_cents` begins at 0 and equals the sum of
    `amount_cents` over their fines still in `PENDING` settlement status. A rider's
    account `status` is `ACTIVE` or `SUSPENDED`, beginning at `ACTIVE`."

    A newly registered rider has wallet 0, outstanding 0, and status ACTIVE.

    Design: Corner/entities/rider_wallet_and_status_system_initialized
    """
    plan = fx.create_standard_plan()
    resp = api.create_rider({"email": "sys@x.com", "full_name": "Sys", "plan_id": plan["id"]}, _ANON)
    rider = validate_success(resp, 201)
    assert rider["wallet_balance_cents"] == 0, f"expected 0, got {rider['wallet_balance_cents']}"
    assert rider["outstanding_fine_cents"] == 0, f"expected 0, got {rider['outstanding_fine_cents']}"
    assert rider["status"] == "ACTIVE", f"expected ACTIVE, got {rider['status']}"


def test_list_vehicles_pagination_envelope(api):
    """PRD §2.3: "Every list response carries the pagination fields `limit`,
    `offset`, `total_count`, and `has_more` inside the `meta` object of the
    envelope."

    Listing vehicles with one vehicle present returns total_count 1 and
    has_more false.

    Design: Corner/entities/list_vehicles_pagination_envelope_fields_present
    """
    zone = fx.create_zone(zone_type="RIDE_OK", priority=5)
    fx.create_vehicle(zone["id"], qr_code="QR-PG1")
    data, meta = validate_paginated(api.list_vehicles(_ADMIN, params={"limit": 10, "offset": 0}))
    assert meta["total_count"] == 1, f"expected total_count 1, got {meta['total_count']}"
    assert meta["has_more"] is False, f"expected has_more False, got {meta['has_more']}"


def test_create_rider_nonexistent_plan_reference_not_found(api):
    """PRD §2.8: "After path existence, any foreign-key id supplied in the request
    body is checked against its referenced resource, and a dangling reference yields
    `ERR_REFERENCE_NOT_FOUND`; this body-reference check applies to creating a trip,
    creating a rebalancing task, registering a rider, submitting a low-income
    application, and changing a rider's plan."

    Registering a rider with a plan_id that references no Plan returns
    ERR_REFERENCE_NOT_FOUND (404).

    Design: Corner/entities/create_rider_with_nonexistent_plan_returns_reference_not_found
    """
    resp = api.create_rider(
        {"email": "nope@x.com", "full_name": "Nope",
         "plan_id": "00000000-0000-4000-8000-000000000abc"}, _ANON)
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# endpoints — reverse-reachability filters
# ---------------------------------------------------------------------------
def test_list_trips_filtered_by_rider(api):
    """PRD §4 lists `GET /api/trips` "List trips; filter by rider, vehicle, or
    zone"; PRD §2.1: "a `Rider` may only act on a `Trip`, `Fine`, or
    `LowIncomeApplication` whose `rider_id` equals their own `X-User-ID`, as well as
    on their own `Rider` record and its wallet ledger."

    Filtering trips by rider_id returns exactly that rider's one trip.

    Design: Corner/endpoints/list_trips_filtered_by_rider_id_reverse_reachability
    """
    plan, zone, vehicle, rider, trip = fx.setup_active_trip("2026-07-10T00:00:00Z")
    headers = make_rider_headers(rider["id"])
    data, meta = validate_paginated(api.list_trips(headers, params={"rider_id": rider["id"]}))
    assert meta["total_count"] == 1, f"expected total_count 1, got {meta['total_count']}"
    assert data[0]["id"] == trip["id"]


def test_list_trip_segments_subresource(api):
    """PRD §3.4: "A trip's elapsed time is recorded as an ordered series of
    **TripSegment** rows, each owned by its `trip_id`."
    PRD §3.4: "Pausing closes the open ride segment — stamping its `ended_at` and
    computing its `duration_seconds` — and opens a fresh pause segment whose
    `started_at` is the current clock."

    After one pause, the trip's segments list contains a closed RIDE (120s) and an
    open PAUSE segment; total_count == 2.

    Design: Corner/endpoints/list_trip_segments_subresource_reverse_reachability
    """
    plan, zone, vehicle = fx.setup_world()
    rider = fx.create_funded_rider(plan["id"])
    headers = make_rider_headers(rider["id"])
    trip = fx.start_trip(rider, vehicle, "2026-07-11T00:00:00Z")
    fx.set_clock("2026-07-11T00:02:00Z")
    validate_success(api.pause_trip(trip["id"], headers))
    data, meta = validate_paginated(api.list_trip_segments_subresource(trip["id"], headers))
    assert meta["total_count"] == 2, f"expected 2 segments, got {meta['total_count']}"
    types = {seg["segment_type"] for seg in data}
    assert types == {"RIDE", "PAUSE"}, f"expected RIDE+PAUSE, got {types}"
    ride = next(seg for seg in data if seg["segment_type"] == "RIDE")
    assert ride["duration_seconds"] == 120, (
        f"expected closed RIDE of 120s, got {ride['duration_seconds']}")


def test_wallet_transactions_subresource_lists_topup(api):
    """PRD §3.2: "A top-up creates a wallet ledger entry of type `TOPUP` carrying
    the positive `amount_cents`, adds that amount to `wallet_balance_cents`, and
    increments the rider's `version`."

    A single 5000 top-up produces one TOPUP ledger row in the rider's
    wallet-transactions sub-resource.

    Design: Corner/endpoints/wallet_transactions_subresource_lists_ledger
    """
    plan = fx.create_standard_plan()
    rider = fx.create_rider(plan["id"])
    headers = make_rider_headers(rider["id"])
    validate_success(api.topup_rider(rider["id"], {"amount_cents": 5000}, headers), 201)
    data, meta = validate_paginated(api.list_rider_wallet_transactions(rider["id"], headers))
    assert meta["total_count"] == 1, f"expected 1 ledger row, got {meta['total_count']}"
    assert data[0]["txn_type"] == "TOPUP"
    assert data[0]["amount_cents"] == 5000, f"expected 5000, got {data[0]['amount_cents']}"


def test_list_rebalancing_tasks_filtered_by_technician(api):
    """PRD §4 lists `GET /api/rebalancing-tasks` "List tasks; filter by vehicle,
    technician, or target zone".
    PRD §3.7: "An administrator assigns an `OPEN` task to a technician by supplying
    the `technician_id`, transitioning the task `OPEN → ASSIGNED` and recording the
    technician on it."

    Filtering tasks by technician_id returns exactly that technician's one
    ASSIGNED task.

    Design: Corner/endpoints/list_rebalancing_tasks_by_technician_reverse_reachability
    """
    zone = fx.create_zone(zone_type="RIDE_OK", priority=5)
    technician = fx.create_technician(zone["id"], name="TechZ")
    vehicle = fx.create_vehicle(zone["id"], battery_pct=50)
    task, _ = fx.create_move_task(vehicle, zone["id"], "2026-07-12T10:00:00Z", "2026-07-12T11:00:00Z")
    fx.assign_task(task, technician)
    data, meta = validate_paginated(
        api.list_rebalancing_tasks(_ADMIN, params={"technician_id": technician["id"]}))
    assert meta["total_count"] == 1, f"expected 1 task, got {meta['total_count']}"
    assert data[0]["id"] == task["id"]


def test_list_fines_filtered_by_trip(api):
    """PRD §3.5: "if and only if the resolved end zone is a `NO_PARK` zone, a
    **Fine** is raised against the trip's rider with reason `BAD_PARKING_NO_PARK`
    and settlement status `PENDING`."
    PRD §4 lists `GET /api/fines` "List fines; filter by rider or trip".

    Filtering fines by trip_id returns the one BAD_PARKING_NO_PARK fine raised by
    that trip.

    Design: Corner/endpoints/list_fines_by_trip_reverse_reachability
    """
    plan, ok_zone, np_zone, vehicle, rider, trip, fine = fx.setup_trip_ended_in_no_park(
        "2026-07-13T00:00:00Z", "2026-07-13T00:01:30Z")
    headers = make_rider_headers(rider["id"])
    data, meta = validate_paginated(api.list_fines(headers, params={"trip_id": trip["id"]}))
    assert meta["total_count"] == 1, f"expected 1 fine, got {meta['total_count']}"
    assert data[0]["reason"] == "BAD_PARKING_NO_PARK"


def test_list_low_income_applications_filtered_by_rider(api):
    """PRD §3.2: "Riders seeking reduced rates submit a **LowIncomeApplication**
    naming their `rider_id`, their `household_size` (at least 1), and their declared
    `annual_income_cents` (at least 0)."
    PRD §4 lists `GET /api/low-income-applications` "List applications; filter by
    rider".

    Filtering applications by rider_id returns exactly that rider's one
    application.

    Design: Corner/endpoints/list_low_income_applications_by_rider_reverse_reachability
    """
    plan = fx.create_standard_plan()
    rider = fx.create_rider(plan["id"])
    headers = make_rider_headers(rider["id"])
    app = validate_success(api.create_low_income_application(
        {"rider_id": rider["id"], "household_size": 3, "annual_income_cents": 5000000}, headers), 201)
    data, meta = validate_paginated(
        api.list_low_income_applications(_ADMIN, params={"rider_id": rider["id"]}))
    assert meta["total_count"] == 1, f"expected 1 application, got {meta['total_count']}"
    assert data[0]["id"] == app["id"]


def test_list_vehicles_filtered_by_current_zone(api):
    """PRD §4 lists `GET /api/vehicles` "List vehicles; filter by status or current
    zone".
    PRD §3.1: "and a `current_zone_id` naming the zone it is parked in."

    Filtering vehicles by current_zone_id returns the vehicle parked in that zone.

    Design: Corner/endpoints/list_vehicles_by_current_zone_reverse_reachability
    """
    zone = fx.create_zone(zone_type="RIDE_OK", priority=5)
    vehicle = fx.create_vehicle(zone["id"], qr_code="QR-E8")
    data, meta = validate_paginated(api.list_vehicles(_ADMIN, params={"current_zone_id": zone["id"]}))
    assert meta["total_count"] == 1, f"expected 1 vehicle, got {meta['total_count']}"
    assert data[0]["id"] == vehicle["id"]


def test_list_riders_filtered_by_plan(api):
    """PRD §4 lists `GET /api/riders` "List riders; filter by plan".
    PRD §3.2: "Anyone may self-register as a **Rider** without authentication,
    supplying an `email` (unique across all riders), a `full_name`, and the
    `plan_id` of the plan they start on."

    Filtering riders by plan_id returns the rider registered on that plan.

    Design: Corner/endpoints/list_riders_by_plan_reverse_reachability
    """
    plan = fx.create_standard_plan()
    rider = fx.create_rider(plan["id"])
    data, meta = validate_paginated(api.list_riders(_ADMIN, params={"plan_id": plan["id"]}))
    assert meta["total_count"] == 1, f"expected 1 rider, got {meta['total_count']}"
    assert data[0]["id"] == rider["id"]


def test_list_wallet_transactions_filtered_by_fine(api):
    """PRD §3.5: "Third, raising that fine immediately charges the wallet again: a
    `WalletTransaction` of type `FINE_CHARGE` is created carrying the negative fine
    `amount_cents`, `Rider.wallet_balance_cents` is reduced by the fine amount, and
    `Rider.outstanding_fine_cents` is increased by the fine amount."
    PRD §4 lists `GET /api/wallet-transactions` "List wallet transactions; filter by
    rider, trip, or fine".

    Filtering the flat ledger by fine_id returns the one FINE_CHARGE row of -2500
    for that fine.

    Design: Corner/endpoints/list_wallet_transactions_by_fine_reverse_reachability
    """
    plan, ok_zone, np_zone, vehicle, rider, trip, fine = fx.setup_trip_ended_in_no_park(
        "2026-07-14T00:00:00Z", "2026-07-14T00:01:30Z")
    data, meta = validate_paginated(api.list_wallet_transactions(_ADMIN, params={"fine_id": fine["id"]}))
    assert meta["total_count"] == 1, f"expected 1 ledger row, got {meta['total_count']}"
    assert data[0]["txn_type"] == "FINE_CHARGE"
    assert data[0]["amount_cents"] == -2500, f"expected -2500, got {data[0]['amount_cents']}"


def test_list_rebalancing_tasks_filtered_by_vehicle(api):
    """PRD §4 lists `GET /api/rebalancing-tasks` "List tasks; filter by vehicle,
    technician, or target zone".
    PRD §3.7: "A rebalancing task names the `vehicle_id` it concerns, a `task_type`
    of `MOVE` (relocate the vehicle to a target zone) or `SWAP` (replace the battery
    in place), a `target_zone_id` that is required for a move and null for a swap,
    and a scheduled on-site window bounded by `window_start` and `window_end`, where
    `window_end` must be strictly after `window_start` (a non-positive window is
    rejected with `ERR_INVALID_WINDOW`)."

    Filtering tasks by vehicle_id returns the one OPEN MOVE task for that vehicle.

    Design: Corner/endpoints/list_rebalancing_tasks_by_vehicle_reverse_reachability
    """
    zone = fx.create_zone(zone_type="RIDE_OK", priority=5)
    vehicle = fx.create_vehicle(zone["id"], battery_pct=50)
    task, _ = fx.create_move_task(vehicle, zone["id"], "2026-07-15T10:00:00Z", "2026-07-15T11:00:00Z")
    data, meta = validate_paginated(
        api.list_rebalancing_tasks(_ADMIN, params={"vehicle_id": vehicle["id"]}))
    assert meta["total_count"] == 1, f"expected 1 task, got {meta['total_count']}"
    assert data[0]["id"] == task["id"]


def test_list_trips_filtered_by_end_zone(api):
    """PRD §4 lists `GET /api/trips` "List trips; filter by rider, vehicle, or
    zone".
    PRD §3.5: "A valid end closes the trip's open segment (a ride segment when
    ending from `ACTIVE`, a pause segment when ending from `PAUSED`), stamps
    `ended_at` with the current clock, records the resolved zone into `end_zone_id`,
    and transitions the trip `ACTIVE → COMPLETED` or `PAUSED → COMPLETED`
    accordingly."

    Filtering trips by end_zone_id (alongside vehicle_id and start_zone_id) returns
    the COMPLETED trip ended in that zone.

    Design: Corner/endpoints/list_trips_by_end_zone_reverse_reachability
    """
    plan, zone, vehicle, rider, trip = fx.setup_completed_trip(
        "2026-07-16T00:00:00Z", "2026-07-16T00:02:00Z")
    params = {"end_zone_id": zone["id"], "vehicle_id": vehicle["id"], "start_zone_id": zone["id"]}
    data, meta = validate_paginated(api.list_trips(_ADMIN, params=params))
    assert meta["total_count"] == 1, f"expected 1 trip, got {meta['total_count']}"
    assert data[0]["id"] == trip["id"]


# ---------------------------------------------------------------------------
# calculations — MDS half-open trip count
# ---------------------------------------------------------------------------
def test_mds_trip_count_half_open_window(api):
    """PRD §3.8: "The `trip_count` is the number of `COMPLETED` trips whose
    `started_at` falls in the half-open window — that is, at or after `window_start`
    and strictly before `window_end`."
    PRD §3.8: "The `total_billable_minutes` is the sum of `billable_minutes` over
    exactly those counted trips."

    Window [12:00,13:00). A trip started at 12:00 (== window_start) is included; a
    trip started at 13:00 (== window_end) is excluded. trip_count == 1, and
    total_billable_minutes == 2 (the included trip's 120s ride).

    Design: Corner/calculations/mds_trip_count_half_open_window_boundary
    """
    plan = fx.create_standard_plan()
    zone = fx.create_zone(zone_type="RIDE_OK", priority=5)
    veh1 = fx.create_vehicle(zone["id"], qr_code="QR-W1")
    veh2 = fx.create_vehicle(zone["id"], qr_code="QR-W2")
    rider1 = fx.create_funded_rider(plan["id"])
    rider2 = fx.create_funded_rider(plan["id"])
    # Trip 1 started exactly at window_start, 2-minute ride.
    t1 = fx.start_trip(rider1, veh1, "2026-07-07T12:00:00Z")
    fx.end_trip(rider1, t1, zone["id"], "2026-07-07T12:02:00Z")
    # Trip 2 started exactly at window_end (excluded by half-open boundary).
    t2 = fx.start_trip(rider2, veh2, "2026-07-07T13:00:00Z")
    fx.end_trip(rider2, t2, zone["id"], "2026-07-07T13:02:00Z")
    resp = api.create_mds_report(
        {"window_start": "2026-07-07T12:00:00Z", "window_end": "2026-07-07T13:00:00Z"}, _REGULATOR)
    report = validate_success(resp, 201)
    assert report["trip_count"] == 1, f"expected trip_count 1, got {report['trip_count']}"
    assert report["total_billable_minutes"] == 2, (
        f"expected total_billable_minutes 2, got {report['total_billable_minutes']}")
