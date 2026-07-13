"""Dispatch: the compliance gates, the budget gate, and the completion precondition."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    fixtures,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]

SINGLE_STOP = [{"sequence": 1, "address": "A", "stop_kind": "PICKUP", "planned_leg_miles": 2.5}]
FROZEN_SPECIMEN = [{
    "pickup_index": 0, "dropoff_index": 1, "specimen_type": "TISSUE",
    "temp_requirement": "FROZEN", "required_temp_min_c": -30, "required_temp_max_c": -15,
}]


# ---------------------------------------------------------------------------
# A route must carry at least one stop
# ---------------------------------------------------------------------------
def test_dispatching_a_route_with_no_stops_is_rejected(api):
    """PRD §3.4: "It must carry at least one stop, else `ERR_ROUTE_HAS_NO_STOPS`."

    Design: Difficulty/boundary_precision_check/dispatch_zero_stops_empty_set
    """
    ctx = fixtures.setup_scenario(stops=[], specimens=[], assign=True)
    resp = api.dispatch_route(ctx["route"]["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_ROUTE_HAS_NO_STOPS.value)


def test_dispatching_a_route_with_exactly_one_stop_succeeds(api):
    """PRD §3.4: "It must carry at least one stop, else `ERR_ROUTE_HAS_NO_STOPS`."
    PRD §3.4: "Dispatching advances a route from `ASSIGNED` to `DISPATCHED` and is where
    the platform's compliance gates concentrate."

    One stop is the smallest manifest that clears the gate.

    Design: Difficulty/boundary_precision_check/dispatch_zero_stops_empty_set
    """
    ctx = fixtures.setup_scenario(stops=SINGLE_STOP, specimens=[], assign=True)
    dispatched = validate_success(api.dispatch_route(ctx["route"]["id"], DISPATCHER))
    assert dispatched["status"] == "DISPATCHED"


# ---------------------------------------------------------------------------
# The route's state outranks the laboratory's budget
# ---------------------------------------------------------------------------
def test_dispatching_a_planned_route_over_budget_reports_the_state_failure(api):
    """PRD §2.8: "When several conditions could reject a request, the server evaluates
    them in a fixed precedence and returns the first that fails, so that an earlier
    concern is never masked by a later one."
    PRD §3.4: "The route must be `ASSIGNED`, else `ERR_ROUTE_INVALID_STATE`."

    The laboratory's budget of 1 cent could never cover this run, yet the route was never
    assigned — the target-state check (5) precedes the fiscal check (7).

    Design: Difficulty/priority_pair_validation_conflict/dispatch_state_beats_budget
    """
    ctx = fixtures.setup_scenario(lab={"budget_cents": 1}, stops=SINGLE_STOP, specimens=[])
    resp = api.dispatch_route(ctx["route"]["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_ROUTE_INVALID_STATE.value)


def test_dispatching_an_assigned_route_over_budget_reports_the_budget_failure(api):
    """PRD §3.4: "The budget gate then requires that the owning laboratory's
    `billed_balance_cents` plus this provisional charge not exceed its `budget_cents`,
    else `ERR_BUDGET_EXCEEDED`."
    PRD §3.4: "The route must be `ASSIGNED`, else `ERR_ROUTE_INVALID_STATE`."

    The identical over-budget route, once its state check passes, is stopped by the
    fiscal gate instead — confirming the fiscal check sits behind the state check.

    Design: Difficulty/priority_pair_validation_conflict/dispatch_state_beats_budget
    """
    ctx = fixtures.setup_scenario(
        lab={"budget_cents": 1}, stops=SINGLE_STOP, specimens=[], assign=True
    )
    resp = api.dispatch_route(ctx["route"]["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED.value)


# ---------------------------------------------------------------------------
# Credential-type and refrigeration gates
# ---------------------------------------------------------------------------
def test_dispatching_a_frozen_specimen_with_a_standard_driver_is_rejected(api):
    """PRD §3.4: "The driver's `credential_type` must be sufficient for every specimen
    aboard: a `CULTURE` specimen requires `BLOODBORNE` or `HAZMAT`, and any specimen
    whose `temp_requirement` is `FROZEN` requires `HAZMAT`; a shortfall is rejected with
    `ERR_CREDENTIAL_TYPE_INSUFFICIENT`."

    Design: Corner/validations/dispatch_frozen_specimen_standard_driver_returns_422
    """
    ctx = fixtures.setup_scenario(
        driver={"credential_type": "STANDARD"},
        vehicle={"has_refrigeration": True},
        specimens=FROZEN_SPECIMEN,
        assign=True,
    )
    resp = api.dispatch_route(ctx["route"]["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_CREDENTIAL_TYPE_INSUFFICIENT.value)


def test_dispatching_a_refrigerated_specimen_without_refrigeration_is_rejected(api):
    """PRD §3.4: "If any specimen requires `REFRIGERATED` or `FROZEN` handling, the
    assigned vehicle's `has_refrigeration` must be true, else
    `ERR_VEHICLE_REFRIGERATION_REQUIRED`."

    The driver holds a HAZMAT credential, so only the vehicle can be the blocker.

    Design: Corner/validations/dispatch_refrigerated_specimen_plain_vehicle_returns_422
    """
    ctx = fixtures.setup_scenario(
        driver={"credential_type": "HAZMAT"},
        vehicle={"has_refrigeration": False},
        assign=True,
    )
    resp = api.dispatch_route(ctx["route"]["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_VEHICLE_REFRIGERATION_REQUIRED.value)


# ---------------------------------------------------------------------------
# Completion requires every stop to have settled
# ---------------------------------------------------------------------------
def test_completing_a_route_with_an_unresolved_stop_is_rejected(api):
    """PRD §3.7: "The route must be `DISPATCHED`, else `ERR_ROUTE_INVALID_STATE`, and
    every stop on the route must have settled into either `COMPLETED` or `MISSED`; if any
    stop is still unresolved the completion is rejected with `ERR_STOPS_NOT_RESOLVED`."

    Design: Corner/state_machines/complete_before_stops_resolved_returns_409
    """
    ctx = fixtures.setup_dispatched_route()
    resp = api.complete_route(ctx["route"]["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_STOPS_NOT_RESOLVED.value)
