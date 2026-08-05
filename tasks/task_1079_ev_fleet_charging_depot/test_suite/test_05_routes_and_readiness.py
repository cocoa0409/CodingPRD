"""Route assignment gates: the safety/readiness/SOC cascade and its precedence.

Difficulty (queue A): SOC-at-threshold boundary, RouteAssignment->Vehicle
readiness dependency, state-beats-safety precedence pair.
Corner (queue B): unassigning a PLANNED route, SOC one-below-requirement.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    fm_headers, op_headers,
)
import test_helpers.fixtures as fx


# ---------------------------------------------------------------------------
# Difficulty: SOC exactly at the inclusive required threshold
# ---------------------------------------------------------------------------

def _route_ready(api, soc, required):
    depot = fx.new_depot(api)
    vehicle = fx.new_vehicle(api, depot["id"], current_soc_pct=soc)
    driver = fx.new_driver(api, depot["id"])
    route = fx.new_route(api, depot["id"], vehicle["id"], driver["id"], required_soc_pct=required)
    return depot, vehicle, driver, route


def test_assign_soc_exactly_at_requirement_succeeds(api):
    """PRD §3.6: "the vehicle's `current_soc_pct` must be at least the route's
    `required_soc_pct`, or the request is rejected with
    `ERR_SOC_BELOW_ROUTE_REQUIREMENT`; this boundary is inclusive, so a vehicle
    whose charge exactly equals the requirement passes."

    Design: Difficulty/boundary_precision_check/assign_soc_at_required_threshold
    """
    _, _, _, route = _route_ready(api, soc=90, required=90)
    data = validate_success(api.assign_route(route["id"], op_headers()), 200)
    assert data["status"] == "ASSIGNED"


def test_assign_soc_at_lower_inclusive_threshold_succeeds(api):
    """PRD §3.6: "the vehicle's `current_soc_pct` must be at least the route's
    `required_soc_pct`, or the request is rejected with
    `ERR_SOC_BELOW_ROUTE_REQUIREMENT`; this boundary is inclusive, so a vehicle
    whose charge exactly equals the requirement passes."

    Design: Difficulty/boundary_precision_check/assign_soc_at_required_threshold
    """
    # SOC 80 == required 80, and 80 >= MIN_READY_SOC_PCT so readiness also passes.
    _, _, _, route = _route_ready(api, soc=80, required=80)
    data = validate_success(api.assign_route(route["id"], op_headers()), 200)
    assert data["status"] == "ASSIGNED"


# ---------------------------------------------------------------------------
# Difficulty: assign gated on vehicle readiness (cross-entity)
# ---------------------------------------------------------------------------

def test_assign_not_ready_vehicle_returns_not_ready(api):
    """PRD §3.6: "Next the **readiness** gate: the vehicle's `readiness_status`
    must be `READY`, or the request is rejected with `ERR_VEHICLE_NOT_READY`."

    Design: Difficulty/cross_entity_state_dependency/assign_requires_vehicle_ready
    """
    # SOC 50 < MIN_READY 80 => NOT_READY, even though required_soc 40 would pass.
    _, _, _, route = _route_ready(api, soc=50, required=40)
    resp = api.assign_route(route["id"], op_headers())
    validate_error(resp, ApiErrorId.ERR_VEHICLE_NOT_READY.value)


def test_assign_not_ready_vehicle_leaves_route_planned(api):
    """PRD §3.6: "the vehicle's `readiness_status` must be `READY`, or the
    request is rejected with `ERR_VEHICLE_NOT_READY`."

    Design: Difficulty/cross_entity_state_dependency/assign_requires_vehicle_ready
    """
    _, _, _, route = _route_ready(api, soc=50, required=40)
    api.assign_route(route["id"], op_headers())
    r_after = get_success_data(api.get_route(route["id"], fm_headers()))
    assert r_after["status"] == "PLANNED", "a rejected assign must not advance the route"


# ---------------------------------------------------------------------------
# Difficulty: state check outranks the safety (grounded) check
# ---------------------------------------------------------------------------

def _completed_route_grounded_vehicle(api):
    depot, vehicle, driver, route = fx.assigned_route(api, vehicle_soc=90, required_soc=80)
    completed = get_success_data(api.complete_route(route["id"], op_headers()))
    # Ground the vehicle after completion (no ASSIGNED route remains to revert).
    fx.open_work_order(api, "VEHICLE", vehicle_id=vehicle["id"], issue="tires", severity="HIGH")
    return depot, vehicle, route, completed


def test_assign_completed_route_state_beats_safety(api):
    """PRD §3.6: "First the route must actually be in `PLANNED`, or the request
    is rejected with `ERR_ROUTE_NOT_PLANNED`. Then comes the **safety** gate,
    which outranks every readiness and fiscal consideration: the vehicle must not
    be `GROUNDED`, or the request is rejected with `ERR_VEHICLE_GROUNDED`."

    Design: Difficulty/priority_pair_validation_conflict/assign_state_beats_safety
    """
    _, _, route, _ = _completed_route_grounded_vehicle(api)
    resp = api.assign_route(route["id"], op_headers())
    validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_PLANNED.value)


def test_assign_completed_route_leaves_it_completed(api):
    """PRD §3.6: "`COMPLETED` and `CANCELLED` are terminal."
    PRD §3.6: "First the route must actually be in `PLANNED`, or the request is
    rejected with `ERR_ROUTE_NOT_PLANNED`."

    Design: Difficulty/priority_pair_validation_conflict/assign_state_beats_safety
    """
    _, _, route, _ = _completed_route_grounded_vehicle(api)
    api.assign_route(route["id"], op_headers())
    r_after = get_success_data(api.get_route(route["id"], fm_headers()))
    assert r_after["status"] == "COMPLETED", "terminal route must remain COMPLETED"


# ---------------------------------------------------------------------------
# Corner: invalid transition and SOC-below-requirement
# ---------------------------------------------------------------------------

def test_unassign_planned_route_returns_not_assigned(api):
    """PRD §3.6: "A `DepotOperator` may explicitly unassign it, which requires
    the route to be `ASSIGNED` or it is rejected with `ERR_ROUTE_NOT_ASSIGNED`."

    Design: Corner/state_machines/unassign_planned_route_returns_not_assigned
    """
    _, _, _, route = _route_ready(api, soc=90, required=80)  # never assigned
    resp = api.unassign_route(route["id"], op_headers())
    validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_ASSIGNED.value)


def test_assign_soc_one_below_requirement_returns_below(api):
    """PRD §3.6: "the vehicle's `current_soc_pct` must be at least the route's
    `required_soc_pct`, or the request is rejected with
    `ERR_SOC_BELOW_ROUTE_REQUIREMENT`".

    Design: Corner/validations/assign_soc_one_below_required_returns_below_requirement
    """
    # SOC 89 >= MIN_READY 80 (READY) but < required 90 => SOC gate fails.
    _, _, _, route = _route_ready(api, soc=89, required=90)
    resp = api.assign_route(route["id"], op_headers())
    validate_error(resp, ApiErrorId.ERR_SOC_BELOW_ROUTE_REQUIREMENT.value)
