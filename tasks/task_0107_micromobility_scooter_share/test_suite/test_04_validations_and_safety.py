"""Trip-start/end safety gates, fiscal and window validations, cross-entity
state dependencies, validation precedence, and reference/availability errors.
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


# ---------------------------------------------------------------------------
# Boundary: battery >= 20 at trip start
# ---------------------------------------------------------------------------
def test_start_battery_exactly_at_minimum_succeeds(api):
    """PRD §3.3: "The vehicle's `battery_pct` must be at least 20; starting on a
    vehicle below that minimum is rejected with `ERR_BATTERY_TOO_LOW`."

    Battery == 20 (== minimum) is accepted at the >= boundary: the trip starts
    201 ACTIVE.

    Design: Difficulty/boundary_precision_check/start_battery_exactly_at_min_threshold_succeeds
    """
    plan = fx.create_standard_plan()
    zone = fx.create_zone(zone_type="RIDE_OK", priority=5)
    vehicle = fx.create_vehicle(zone["id"], battery_pct=20)
    rider = fx.create_funded_rider(plan["id"])
    fx.set_clock("2026-06-09T00:00:00Z")
    headers = make_rider_headers(rider["id"])
    resp = api.create_trip({"rider_id": rider["id"], "vehicle_id": vehicle["id"]}, headers)
    trip = validate_success(resp, 201)
    assert trip["status"] == "ACTIVE", f"expected ACTIVE, got {trip['status']}"


def test_start_battery_exactly_at_minimum_moves_vehicle_in_use(api):
    """PRD §3.3: "The vehicle's `battery_pct` must be at least 20; starting on a
    vehicle below that minimum is rejected with `ERR_BATTERY_TOO_LOW`."
    PRD §3.3: "When these checks pass, the vehicle momentarily moves
    `AVAILABLE → RESERVED` and then, once the trip row exists, `RESERVED → IN_USE`
    within the same unlock call."

    Battery == 20 passes the >= gate, so the unlock proceeds and the vehicle lands
    in IN_USE — the side effect that only fires when the boundary is satisfied.

    Design: Difficulty/boundary_precision_check/start_battery_exactly_at_min_threshold_succeeds
    """
    plan = fx.create_standard_plan()
    zone = fx.create_zone(zone_type="RIDE_OK", priority=5)
    vehicle = fx.create_vehicle(zone["id"], battery_pct=20)
    rider = fx.create_funded_rider(plan["id"])
    fx.set_clock("2026-06-09T00:00:00Z")
    headers = make_rider_headers(rider["id"])
    validate_success(api.create_trip(
        {"rider_id": rider["id"], "vehicle_id": vehicle["id"]}, headers), 201)
    veh_after = validate_success(api.get_vehicle(vehicle["id"], _ADMIN))
    assert veh_after["status"] == "IN_USE", f"expected IN_USE, got {veh_after['status']}"


def test_start_battery_below_minimum_rejected(api):
    """PRD §3.3: "The vehicle's `battery_pct` must be at least 20; starting on a
    vehicle below that minimum is rejected with `ERR_BATTERY_TOO_LOW`."

    Battery == 19 (< 20) is rejected with ERR_BATTERY_TOO_LOW (422) — the <
    complement of the >= boundary.

    Design: Corner/validations/start_trip_battery_below_threshold_returns_422
    """
    plan = fx.create_standard_plan()
    zone = fx.create_zone(zone_type="RIDE_OK", priority=5)
    vehicle = fx.create_vehicle(zone["id"], battery_pct=19)
    rider = fx.create_funded_rider(plan["id"])
    headers = make_rider_headers(rider["id"])
    resp = api.create_trip({"rider_id": rider["id"], "vehicle_id": vehicle["id"]}, headers)
    validate_error(resp, ApiErrorId.ERR_BATTERY_TOO_LOW.value)


# ---------------------------------------------------------------------------
# Safety: start in a NO_RIDE zone
# ---------------------------------------------------------------------------
def test_start_in_no_ride_zone_rejected(api):
    """PRD §3.3: "The vehicle's resolved current zone must not be a `NO_RIDE` zone;
    starting on a vehicle parked in a no-ride zone is rejected with
    `ERR_START_IN_NO_RIDE_ZONE`."

    Unlocking an AVAILABLE vehicle parked in a NO_RIDE zone returns
    ERR_START_IN_NO_RIDE_ZONE (422).

    Design: Corner/validations/start_trip_in_no_ride_zone_returns_422
    """
    plan = fx.create_standard_plan()
    no_ride = fx.create_zone(zone_type="NO_RIDE", priority=2)
    vehicle = fx.create_vehicle(no_ride["id"])
    rider = fx.create_funded_rider(plan["id"])
    headers = make_rider_headers(rider["id"])
    resp = api.create_trip({"rider_id": rider["id"], "vehicle_id": vehicle["id"]}, headers)
    validate_error(resp, ApiErrorId.ERR_START_IN_NO_RIDE_ZONE.value)


# ---------------------------------------------------------------------------
# Validation precedence: state before safety on end
# ---------------------------------------------------------------------------
def test_end_completed_trip_in_no_ride_state_beats_safety(api):
    """PRD §2.8: "Only after these gates does the system evaluate state-machine
    legality (`ERR_INVALID_STATE`), then the domain-specific business rules
    described in §3, and finally field-level shape validation (`ERR_INVALID_REQUEST`)
    for missing required fields, invalid enum members, or out-of-range numeric
    values on any create or action body."
    PRD §3.5: "ending in a no-ride zone is rejected with `ERR_END_IN_NO_RIDE_ZONE`,
    and the rider must walk the vehicle out of such a zone before ending."

    A second end on an already-COMPLETED trip, supplying a NO_RIDE end zone, hits
    the state-machine check first: ERR_INVALID_STATE (409) precedes the §3 safety
    rule ERR_END_IN_NO_RIDE_ZONE (422).

    Design: Difficulty/priority_pair_validation_conflict/end_completed_trip_in_no_ride_state_beats_safety
    """
    plan, zone, vehicle, rider, trip = fx.setup_completed_trip(
        "2026-06-07T00:00:00Z", "2026-06-07T00:02:00Z")
    no_ride = fx.create_zone(zone_type="NO_RIDE", priority=2)
    headers = make_rider_headers(rider["id"])
    resp = api.end_trip(trip["id"], {"end_zone_id": no_ride["id"]}, headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_end_completed_trip_in_no_ride_leaves_trip_completed(api):
    """PRD §2.8: "Only after these gates does the system evaluate state-machine
    legality (`ERR_INVALID_STATE`), then the domain-specific business rules
    described in §3, and finally field-level shape validation (`ERR_INVALID_REQUEST`)
    for missing required fields, invalid enum members, or out-of-range numeric
    values on any create or action body."
    PRD §3.5: "stamps `ended_at` with the current clock, records the resolved zone
    into `end_zone_id`, and transitions the trip `ACTIVE → COMPLETED` or
    `PAUSED → COMPLETED` accordingly."

    Because the state check pre-empts the NO_RIDE safety rule, the rejected second
    end leaves the trip COMPLETED with its original (legal) end_zone unchanged — the
    NO_RIDE zone is never recorded.

    Design: Difficulty/priority_pair_validation_conflict/end_completed_trip_in_no_ride_state_beats_safety
    """
    plan, zone, vehicle, rider, trip = fx.setup_completed_trip(
        "2026-06-07T00:00:00Z", "2026-06-07T00:02:00Z")
    no_ride = fx.create_zone(zone_type="NO_RIDE", priority=2)
    headers = make_rider_headers(rider["id"])
    resp = api.end_trip(trip["id"], {"end_zone_id": no_ride["id"]}, headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_trip(trip["id"], headers))
    assert after["status"] == "COMPLETED", f"expected COMPLETED, got {after['status']}"
    assert after["end_zone_id"] == zone["id"], (
        f"end_zone should stay the original legal zone, got {after['end_zone_id']}")


# ---------------------------------------------------------------------------
# Cross-entity state dependency
# ---------------------------------------------------------------------------
def test_end_trip_blocked_when_rider_suspended(api):
    """PRD §3.5: "The end is permitted only when the trip is `ACTIVE` or `PAUSED`,
    when the resolved end zone is not a `NO_RIDE` zone, and when the rider's account
    is `ACTIVE`; ending in a no-ride zone is rejected with `ERR_END_IN_NO_RIDE_ZONE`,
    and the rider must walk the vehicle out of such a zone before ending."

    A rider suspended mid-trip cannot end the trip; the end is rejected with
    ERR_INVALID_STATE (409) because the rider's account is no longer ACTIVE.

    Design: Difficulty/cross_entity_state_dependency/trip_start_blocked_when_rider_suspended
    """
    plan, zone, vehicle, rider, trip = fx.setup_active_trip("2026-06-11T00:00:00Z")
    validate_success(api.suspend_rider(rider["id"], _ADMIN))
    headers = make_rider_headers(rider["id"])
    fx.set_clock("2026-06-11T00:03:00Z")
    resp = api.end_trip(trip["id"], {"end_zone_id": zone["id"]}, headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_end_trip_leaves_trip_active_when_rider_suspended(api):
    """PRD §3.5: "The end is permitted only when the trip is `ACTIVE` or `PAUSED`,
    when the resolved end zone is not a `NO_RIDE` zone, and when the rider's account
    is `ACTIVE`; ending in a no-ride zone is rejected with `ERR_END_IN_NO_RIDE_ZONE`,
    and the rider must walk the vehicle out of such a zone before ending."

    The rider-state dependency is observable as the absence of the end transition:
    after the suspended rider's end is rejected, the trip remains ACTIVE (no
    completion, no charge fired).

    Design: Difficulty/cross_entity_state_dependency/trip_start_blocked_when_rider_suspended
    """
    plan, zone, vehicle, rider, trip = fx.setup_active_trip("2026-06-11T00:00:00Z")
    validate_success(api.suspend_rider(rider["id"], _ADMIN))
    headers = make_rider_headers(rider["id"])
    fx.set_clock("2026-06-11T00:03:00Z")
    resp = api.end_trip(trip["id"], {"end_zone_id": zone["id"]}, headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_trip(trip["id"], headers))
    assert after["status"] == "ACTIVE", f"expected trip to stay ACTIVE, got {after['status']}"


def test_change_plan_to_low_income_succeeds_after_approval(api):
    """PRD §3.2: "A rider may switch freely to a `STANDARD` plan, but may switch to
    a `LOW_INCOME` plan only if they hold at least one `LowIncomeApplication` in
    `APPROVED` status; an attempt to move to a low-income plan without an approved
    application is rejected with `ERR_NO_APPROVED_APPLICATION`."
    PRD §3.2: "A successful switch sets the rider's `plan_id` and increments the
    rider's `version`."

    The dependency pins the gate to APPROVED specifically: once the application is
    approved, the same switch that previously failed now succeeds and sets the
    rider's plan to the LOW_INCOME plan.

    Design: Difficulty/cross_entity_state_dependency/rider_change_plan_to_low_income_requires_approved_application
    """
    std = fx.create_standard_plan()
    li = fx.create_low_income_plan()
    rider = fx.create_rider(std["id"])
    headers = make_rider_headers(rider["id"])
    app = validate_success(api.create_low_income_application(
        {"rider_id": rider["id"], "household_size": 2, "annual_income_cents": 4000000}, headers), 201)
    validate_success(api.approve_low_income_application(app["id"], _ADMIN))
    switched = validate_success(api.change_plan(
        rider["id"], {"plan_id": li["id"], "expected_rider_version": rider["version"]}, headers))
    assert switched["plan_id"] == li["id"], (
        f"expected plan switched to LOW_INCOME, got {switched['plan_id']}")


def test_change_plan_to_low_income_requires_approved_application(api):
    """PRD §3.2: "A rider may switch freely to a `STANDARD` plan, but may switch to
    a `LOW_INCOME` plan only if they hold at least one `LowIncomeApplication` in
    `APPROVED` status; an attempt to move to a low-income plan without an approved
    application is rejected with `ERR_NO_APPROVED_APPLICATION`."

    A rider with only a SUBMITTED application is rejected with
    ERR_NO_APPROVED_APPLICATION (422) and stays on the STANDARD plan.

    Design: Difficulty/cross_entity_state_dependency/rider_change_plan_to_low_income_requires_approved_application
    """
    std = fx.create_standard_plan()
    li = fx.create_low_income_plan()
    rider = fx.create_rider(std["id"])
    headers = make_rider_headers(rider["id"])
    validate_success(api.create_low_income_application(
        {"rider_id": rider["id"], "household_size": 2, "annual_income_cents": 4000000}, headers), 201)
    resp = api.change_plan(
        rider["id"], {"plan_id": li["id"], "expected_rider_version": rider["version"]}, headers)
    validate_error(resp, ApiErrorId.ERR_NO_APPROVED_APPLICATION.value)
    after = validate_success(api.get_rider(rider["id"], headers))
    assert after["plan_id"] == std["id"], f"expected plan unchanged, got {after['plan_id']}"


# ---------------------------------------------------------------------------
# Fiscal: settle with insufficient wallet
# ---------------------------------------------------------------------------
def test_settle_fine_insufficient_wallet_rejected(api):
    """PRD §3.6: "A rider may settle a `PENDING` fine, transitioning it
    `PENDING → SETTLED`, but only when their `wallet_balance_cents` is at least the
    fine's `amount_cents`; an attempt to settle with insufficient balance is
    rejected with `ERR_INSUFFICIENT_WALLET`."

    Wallet topped 2600, then a trip (160) and a NO_PARK fine charge (2500) drive it
    to -60. Settling the PENDING 2500 fine is rejected with ERR_INSUFFICIENT_WALLET
    (422).

    Design: Corner/validations/settle_fine_insufficient_wallet_returns_422
    """
    plan, ok_zone, np_zone, vehicle, rider, trip, fine = fx.setup_trip_ended_in_no_park(
        "2026-07-08T00:00:00Z", "2026-07-08T00:01:30Z", amount_cents=2600)
    headers = make_rider_headers(rider["id"])
    resp = api.settle_fine(fine["id"], headers)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_WALLET.value)


# ---------------------------------------------------------------------------
# Temporal: invalid task window
# ---------------------------------------------------------------------------
def test_create_task_invalid_window_rejected(api):
    """PRD §3.7: "a scheduled on-site window bounded by `window_start` and
    `window_end`, where `window_end` must be strictly after `window_start` (a
    non-positive window is rejected with `ERR_INVALID_WINDOW`)."

    A rebalancing task whose window_end precedes window_start returns
    ERR_INVALID_WINDOW (422).

    Design: Corner/validations/create_task_invalid_window_returns_422
    """
    zone = fx.create_zone(zone_type="RIDE_OK", priority=5)
    vehicle = fx.create_vehicle(zone["id"], battery_pct=50)
    resp = api.create_rebalancing_task({
        "vehicle_id": vehicle["id"], "task_type": "MOVE", "target_zone_id": zone["id"],
        "window_start": "2026-07-09T11:00:00Z", "window_end": "2026-07-09T10:00:00Z",
        "expected_vehicle_version": vehicle["version"],
    }, _ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW.value)


# ---------------------------------------------------------------------------
# Availability and reference errors
# ---------------------------------------------------------------------------
def test_unlock_vehicle_already_in_use_rejected(api):
    """PRD §3.3: "The vehicle must currently be `AVAILABLE`; a vehicle that is
    already reserved or in use cannot be unlocked again, and such an attempt is
    rejected with `ERR_VEHICLE_NOT_AVAILABLE`."

    Rider B unlocking a vehicle already IN_USE on rider A's trip is rejected with
    ERR_VEHICLE_NOT_AVAILABLE (409).

    Design: Corner/errors/error_vehicle_not_available_on_unlock
    """
    plan = fx.create_standard_plan()
    zone = fx.create_zone(zone_type="RIDE_OK", priority=5)
    vehicle = fx.create_vehicle(zone["id"])
    rider_a = fx.create_funded_rider(plan["id"])
    rider_b = fx.create_funded_rider(plan["id"])
    fx.start_trip(rider_a, vehicle, "2026-07-20T00:00:00Z")
    headers_b = make_rider_headers(rider_b["id"])
    resp = api.create_trip({"rider_id": rider_b["id"], "vehicle_id": vehicle["id"]}, headers_b)
    validate_error(resp, ApiErrorId.ERR_VEHICLE_NOT_AVAILABLE.value)


def test_create_task_unknown_vehicle_reference_not_found(api):
    """PRD §2.8: "After path existence, any foreign-key id supplied in the request
    body is checked against its referenced resource, and a dangling reference yields
    `ERR_REFERENCE_NOT_FOUND`; this body-reference check applies to creating a trip,
    creating a rebalancing task, registering a rider, submitting a low-income
    application, and changing a rider's plan."

    A rebalancing task naming a vehicle_id that resolves to no Vehicle returns
    ERR_REFERENCE_NOT_FOUND (404) — the reference check precedes the OCC version
    check.

    Design: Corner/errors/error_reference_not_found_on_create_task_unknown_vehicle
    """
    zone = fx.create_zone(zone_type="RIDE_OK", priority=5)
    resp = api.create_rebalancing_task({
        "vehicle_id": "00000000-0000-4000-8000-0000000000ff", "task_type": "MOVE",
        "target_zone_id": zone["id"], "window_start": "2026-07-19T10:00:00Z",
        "window_end": "2026-07-19T11:00:00Z", "expected_vehicle_version": zone["version"],
    }, _ADMIN)
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)
