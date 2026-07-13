"""Motor-pool reservation confirmation: vehicle selection, overlap, budget holds."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_policy, create_department, create_pool_vehicle, create_shop_bay,
    create_confirmed_reservation, drive_reservation_to_returned,
    create_started_work_order, get_department,
    create_reservation_payload, create_fuel_log_payload,
    TEST_USERS,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
CLERK = TEST_USERS["motor_pool_clerk_headers"]
TECH = TEST_USERS["shop_tech_headers"]


# ─── resource_temporal_overlap / vehicle_reservation_half_open_adjacency_ok ───

def test_adjacent_reservation_confirms_on_same_vehicle(api):
    """PRD §3.2: "two windows that merely touch (one ends exactly when the other
    begins) do not overlap and the vehicle remains selectable."

    Design: Difficulty/resource_temporal_overlap/vehicle_reservation_half_open_adjacency_ok
    """
    create_policy()
    dep = create_department()
    vehicle = create_pool_vehicle(vin="VIN-8A")
    create_confirmed_reservation(dep["id"], requested_start="2026-06-05T09:00:00Z",
                                 requested_end="2026-06-05T11:00:00Z")
    res_b = validate_success(api.create_reservation(
        create_reservation_payload(dep["id"], requested_start="2026-06-05T11:00:00Z",
                                   requested_end="2026-06-05T13:00:00Z"), CLERK), 201)
    confirmed = validate_success(api.confirm_reservation(res_b["id"], CLERK), 200)
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["assigned_vehicle_id"] == vehicle["id"]


def test_overlapping_reservation_rejected_no_vehicle(api):
    """PRD §3.2: "it excludes any vehicle that already holds a CONFIRMED or CHECKED_OUT
    reservation whose window overlaps the requested one."
    PRD §3.2: "If no candidate qualifies, confirmation is rejected with
    ERR_NO_VEHICLE_AVAILABLE."

    Design: Difficulty/resource_temporal_overlap/vehicle_reservation_half_open_adjacency_ok
    """
    create_policy()
    dep = create_department()
    create_pool_vehicle(vin="VIN-8A2")
    create_confirmed_reservation(dep["id"], requested_start="2026-06-05T09:00:00Z",
                                 requested_end="2026-06-05T11:00:00Z")
    res_c = validate_success(api.create_reservation(
        create_reservation_payload(dep["id"], requested_start="2026-06-05T10:00:00Z",
                                   requested_end="2026-06-05T12:00:00Z"), CLERK), 201)
    validate_error(api.confirm_reservation(res_c["id"], CLERK), "ERR_NO_VEHICLE_AVAILABLE")


# ─── cross_entity_state_dependency / reservation_confirm_depends_on_vehicle_operational ───

def test_confirm_fails_when_only_vehicle_in_shop(api):
    """PRD §3.2: "The selector considers only POOL vehicles whose operational_status is
    IN_SERVICE and whose lifecycle_status is ACTIVE, and it excludes any vehicle that
    already holds a CONFIRMED or CHECKED_OUT reservation whose window overlaps the
    requested one."
    PRD §3.2: "If no candidate qualifies, confirmation is rejected with
    ERR_NO_VEHICLE_AVAILABLE."

    Design: Difficulty/cross_entity_state_dependency/reservation_confirm_depends_on_vehicle_operational
    """
    create_policy()
    dep = create_department()
    vehicle = create_pool_vehicle(vin="VIN-7A")
    bay = create_shop_bay(name="Bay-7A")
    create_started_work_order(vehicle["id"], bay["id"])  # vehicle -> IN_SHOP
    res = validate_success(api.create_reservation(
        create_reservation_payload(dep["id"]), CLERK), 201)
    validate_error(api.confirm_reservation(res["id"], CLERK), "ERR_NO_VEHICLE_AVAILABLE")


def test_confirm_succeeds_after_vehicle_returns_to_service(api):
    """PRD §3.3: "starting drives SCHEDULED → IN_PROGRESS and moves the vehicle's
    operational_status to IN_SHOP." PRD §3.3: "the vehicle's operational_status returns
    to IN_SERVICE" on completion, restoring selectability per PRD §3.2.

    Design: Difficulty/cross_entity_state_dependency/reservation_confirm_depends_on_vehicle_operational
    """
    create_policy()
    dep = create_department()
    vehicle = create_pool_vehicle(vin="VIN-7A-OK")
    bay = create_shop_bay(name="Bay-7A-OK")
    wo = create_started_work_order(vehicle["id"], bay["id"])
    validate_success(api.complete_work_order(wo["id"], {"labor_hours": 1, "parts_cost_cents": 0}, TECH), 200)
    res = validate_success(api.create_reservation(
        create_reservation_payload(dep["id"]), CLERK), 201)
    confirmed = validate_success(api.confirm_reservation(res["id"], CLERK), 200)
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["assigned_vehicle_id"] == vehicle["id"]


# ─── boundary_precision_check / empty_pool_no_vehicle_available ───

def test_confirm_with_zero_vehicles_returns_no_vehicle(api):
    """PRD §3.2: "If no candidate qualifies, confirmation is rejected with
    ERR_NO_VEHICLE_AVAILABLE."

    Design: Difficulty/boundary_precision_check/empty_pool_no_vehicle_available
    """
    create_policy()
    dep = create_department()
    res = validate_success(api.create_reservation(
        create_reservation_payload(dep["id"]), CLERK), 201)
    validate_error(api.confirm_reservation(res["id"], CLERK), "ERR_NO_VEHICLE_AVAILABLE")


def test_confirm_with_only_department_assigned_vehicle_returns_no_vehicle(api):
    """PRD §3.2: "The selector considers only POOL vehicles". PRD §3.1: "A POOL vehicle
    is the only kind the motor pool can reserve; a DEPARTMENT_ASSIGNED vehicle is
    dedicated to its department".

    Design: Difficulty/boundary_precision_check/empty_pool_no_vehicle_available
    """
    create_policy()
    dep = create_department()
    vehicle = create_pool_vehicle(vin="VIN-DA-ONLY")
    validate_success(api.assign_vehicle(
        vehicle["id"],
        {"assignment_type": "DEPARTMENT_ASSIGNED", "assigned_department_id": dep["id"]},
        ADMIN), 200)
    res = validate_success(api.create_reservation(
        create_reservation_payload(dep["id"]), CLERK), 201)
    validate_error(api.confirm_reservation(res["id"], CLERK), "ERR_NO_VEHICLE_AVAILABLE")


# ─── compensating_invariant / reservation_confirm_cancel_conserves_committed_budget ───

def test_confirm_places_budget_hold(api):
    """PRD §3.2: "multiply that whole number of billable hours by the pool rate of 1500
    cents per hour."
    PRD §3.2: "On success the selected vehicle's id is written to assigned_vehicle_id and
    the estimate is added to the department's committed_budget_cents."

    Design: Difficulty/compensating_invariant/reservation_confirm_cancel_conserves_committed_budget
    """
    create_policy()
    dep = create_department()
    create_pool_vehicle(vin="VIN-9A")
    create_confirmed_reservation(dep["id"], requested_start="2026-06-05T09:00:00Z",
                                 requested_end="2026-06-05T13:00:00Z")
    assert get_department(dep["id"])["committed_budget_cents"] == 6000


def test_cancel_releases_hold_net_zero(api):
    """PRD §3.2: "Cancelling from CONFIRMED releases the hold, subtracting
    estimated_cost_cents from the department's committed_budget_cents so that the
    confirm-hold and the cancel-release net to zero."

    Design: Difficulty/compensating_invariant/reservation_confirm_cancel_conserves_committed_budget
    """
    create_policy()
    dep = create_department()
    create_pool_vehicle(vin="VIN-9A2")
    confirmed = create_confirmed_reservation(dep["id"], requested_start="2026-06-05T09:00:00Z",
                                             requested_end="2026-06-05T13:00:00Z")
    assert get_department(dep["id"])["committed_budget_cents"] == 6000
    validate_success(api.cancel_reservation(confirmed["id"], CLERK), 200)
    assert get_department(dep["id"])["committed_budget_cents"] == 0


# ─── priority_pair_validation_conflict / state_beats_fiscal_on_reconfirm ───

def test_reconfirm_confirmed_reservation_returns_invalid_state(api):
    """PRD §3.2: "If the target reservation is not in REQUESTED, the transition is
    rejected with ERR_INVALID_STATE".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_reconfirm
    """
    create_policy()
    dep = create_department(budget=6000)
    create_pool_vehicle(vin="VIN-PC-1")
    confirmed = create_confirmed_reservation(dep["id"], requested_start="2026-06-05T09:00:00Z",
                                             requested_end="2026-06-05T13:00:00Z")
    validate_error(api.confirm_reservation(confirmed["id"], CLERK), "ERR_INVALID_STATE")


def test_reconfirm_at_budget_ceiling_reports_state_not_fiscal(api):
    """PRD §2.8: "a lower-numbered failure always masks a higher-numbered one on the
    same request." State legality is tier (6) "state legality — the target is in a state
    from which the requested transition is defined (ERR_INVALID_STATE, HTTP 409)", ahead
    of tier (11) "the fiscal budget ceiling on confirm (ERR_BUDGET_EXCEEDED, HTTP 409)".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_reconfirm
    """
    create_policy()
    dep = create_department(budget=6000)
    create_pool_vehicle(vin="VIN-PC-2")
    confirmed = create_confirmed_reservation(dep["id"], requested_start="2026-06-05T09:00:00Z",
                                             requested_end="2026-06-05T13:00:00Z")
    # Department is now exactly at its ceiling (committed == budget), so a fiscal check
    # would fail; the state check must still win.
    assert get_department(dep["id"])["committed_budget_cents"] == 6000
    validate_error(api.confirm_reservation(confirmed["id"], CLERK), "ERR_INVALID_STATE")


# ─── validations / checkout_below_vehicle_odometer_returns_rollback ───

def test_checkout_below_vehicle_odometer_returns_rollback(api):
    """PRD §3.2: "records a checkout_odometer that must be at least the assigned
    vehicle's current odometer_miles; a reading below that is an odometer rollback
    rejected with ERR_ODOMETER_ROLLBACK."

    Design: Corner/validations/checkout_below_vehicle_odometer_returns_rollback
    """
    create_policy()
    dep = create_department()
    vehicle = create_pool_vehicle(vin="VIN-ORB-1")
    validate_success(api.create_fuel_log(
        vehicle["id"],
        create_fuel_log_payload(reading_at="2026-03-02T00:00:00Z", gallons=10,
                                fuel_cost_cents=0, odometer_miles=1000), TECH), 201)
    confirmed = create_confirmed_reservation(dep["id"], requested_start="2026-06-05T09:00:00Z",
                                             requested_end="2026-06-05T11:00:00Z")
    validate_error(api.checkout_reservation(confirmed["id"], {"checkout_odometer": 500}, CLERK),
                   "ERR_ODOMETER_ROLLBACK")


# ─── validations / confirm_over_budget_returns_budget_exceeded ───

def test_confirm_over_budget_returns_budget_exceeded(api):
    """PRD §3.2: "the sum of the department's current committed_budget_cents and this
    new estimated_cost_cents must not exceed its monthly_budget_cents, otherwise the
    confirmation is rejected with ERR_BUDGET_EXCEEDED."

    Design: Corner/validations/confirm_over_budget_returns_budget_exceeded
    """
    create_policy()
    dep = create_department(budget=5000)
    create_pool_vehicle(vin="VIN-BUD-1")
    res = validate_success(api.create_reservation(
        create_reservation_payload(dep["id"], requested_start="2026-06-05T09:00:00Z",
                                   requested_end="2026-06-05T13:00:00Z"), CLERK), 201)
    validate_error(api.confirm_reservation(res["id"], CLERK), "ERR_BUDGET_EXCEEDED")


# ─── state_machines / cancel_returned_reservation_returns_invalid_state ───

def test_cancel_returned_reservation_returns_invalid_state(api):
    """PRD §3.2: "A cancel attempted from CHECKED_OUT or RETURNED is not a defined
    transition and is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/cancel_returned_reservation_returns_invalid_state
    """
    create_policy()
    dep = create_department()
    create_pool_vehicle(vin="VIN-RET-1")
    returned = drive_reservation_to_returned(
        dep["id"], checkout_odometer=0, return_odometer=100,
        requested_start="2026-06-05T09:00:00Z", requested_end="2026-06-05T11:00:00Z")
    validate_error(api.cancel_reservation(returned["id"], CLERK), "ERR_INVALID_STATE")


# ─── endpoints / list_reservations_returns_envelope_pagination ───

def test_list_reservations_returns_envelope_and_filter(api):
    """PRD §2.3: "The meta object of a list response carries limit, offset, total_count,
    and has_more." PRD §3.2: "Reservations can be listed with department_id,
    assigned_vehicle_id, and status filters."

    Design: Corner/endpoints/list_reservations_returns_envelope_pagination
    """
    dep = create_department(cost_center_code="CC-L1")
    res = validate_success(api.create_reservation(
        create_reservation_payload(dep["id"]), CLERK), 201)
    data, meta = validate_paginated(api.list_reservations(CLERK, params={"department_id": dep["id"]}))
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert len(data) == 1
    assert data[0]["id"] == res["id"]
