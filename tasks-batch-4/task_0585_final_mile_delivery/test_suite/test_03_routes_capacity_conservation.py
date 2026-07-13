"""Route building: stop referential checks, capacity ceilings and their
boundary, capacity conservation across add/remove, and validation precedence
when a state violation and a fiscal violation coincide."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    add_stop_payload,
    make_customer, make_depot, make_team, make_order, make_route,
    reserve_order_window, add_route_stop, book_appointment, dispatch,
    setup_routed_order, setup_scheduled_order, setup_network,
    TEST_USERS,
)

PLANNER = TEST_USERS["dispatch_planner_headers"]
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"


# --- Referential checks on add-stop (corner validations) ---

def test_add_stop_route_team_mismatch_rejected(api):
    """PRD §3.4: "The referenced window_id must be the order's active_window_id,
    and that window's team_id must equal the route's team_id, else
    ERR_ROUTE_TEAM_MISMATCH."

    Design: Corner/validations/add_stop_route_team_mismatch
    """
    depot = make_depot(api)
    team_a = make_team(api, depot["id"], team_name="TA")
    team_b = make_team(api, depot["id"], team_name="TB", lead_name="Ben", member2_name="Ola")
    cust = make_customer(api)
    order = make_order(api, cust["id"])
    window = reserve_order_window(api, order, team_a["id"])
    route = make_route(api, depot["id"], team_b["id"])
    resp = api.add_stop(route["id"], add_stop_payload(order["id"], window["id"]), PLANNER)
    validate_error(resp, ApiErrorId.ERR_ROUTE_TEAM_MISMATCH.value)


def test_add_stop_window_route_date_mismatch_rejected(api):
    """PRD §3.4: "the window's service_date must equal the route's service_date,
    else ERR_WINDOW_ROUTE_DATE_MISMATCH."

    Design: Corner/validations/add_stop_window_route_date_mismatch
    """
    depot = make_depot(api)
    team = make_team(api, depot["id"])
    cust = make_customer(api)
    order = make_order(api, cust["id"])
    window = reserve_order_window(api, order, team["id"], service_date="2026-06-01")
    route = make_route(api, depot["id"], team["id"], service_date="2026-06-02")
    resp = api.add_stop(route["id"], add_stop_payload(order["id"], window["id"]), PLANNER)
    validate_error(resp, ApiErrorId.ERR_WINDOW_ROUTE_DATE_MISMATCH.value)


def test_add_duplicate_stop_for_routed_order_rejected(api):
    """PRD §3.4: "The order must be SCHEDULED and must not already have an active
    stop — a second stop for an already-routed order is rejected with
    ERR_ORDER_ALREADY_ROUTED."

    Design: Corner/validations/add_duplicate_stop_order_already_routed
    """
    ns = setup_routed_order(api)
    resp = api.add_stop(ns["route"]["id"], add_stop_payload(ns["order"]["id"], ns["window"]["id"]), PLANNER)
    validate_error(resp, ApiErrorId.ERR_ORDER_ALREADY_ROUTED.value)


def test_add_stop_exceeding_stop_count_rejected(api):
    """PRD §3.4: "Adding the stop must keep the route's committed_stops plus one
    at or below max_daily_stops (ERR_ROUTE_STOPS_EXCEEDED)."

    Design: Corner/validations/add_stop_route_stops_exceeded
    """
    depot = make_depot(api)
    team = make_team(api, depot["id"], max_daily_stops=1, max_daily_weight_lbs=5000, max_daily_volume_cuft=5000)
    cust = make_customer(api)
    o1 = make_order(api, cust["id"], item_description="A", weight_lbs=50, volume_cuft=10)
    w1 = reserve_order_window(api, o1, team["id"], window_start_min=480, window_end_min=540)
    o2 = make_order(api, cust["id"], item_description="B", weight_lbs=50, volume_cuft=10)
    w2 = reserve_order_window(api, o2, team["id"], window_start_min=600, window_end_min=660)
    route = make_route(api, depot["id"], team["id"])
    add_route_stop(api, route["id"], o1["id"], w1["id"])
    resp = api.add_stop(route["id"], add_stop_payload(o2["id"], w2["id"]), PLANNER)
    validate_error(resp, ApiErrorId.ERR_ROUTE_STOPS_EXCEEDED.value)


def test_add_stop_exceeding_volume_rejected(api):
    """PRD §3.4: "its committed_volume_cuft plus the order's volume_cuft at or
    below max_daily_volume_cuft (ERR_ROUTE_VOLUME_EXCEEDED)."

    Design: Corner/validations/add_stop_route_volume_exceeded
    """
    depot = make_depot(api)
    team = make_team(api, depot["id"], max_daily_weight_lbs=5000, max_daily_volume_cuft=50)
    cust = make_customer(api)
    order = make_order(api, cust["id"], item_description="Big", weight_lbs=100, volume_cuft=60)
    window = reserve_order_window(api, order, team["id"])
    route = make_route(api, depot["id"], team["id"])
    resp = api.add_stop(route["id"], add_stop_payload(order["id"], window["id"]), PLANNER)
    validate_error(resp, ApiErrorId.ERR_ROUTE_VOLUME_EXCEEDED.value)


def test_remove_unknown_stop_returns_not_found(api):
    """PRD §2.8: "Endpoints that nest identifiers in the URL — for example, a
    route's stops or a stop-scoped removal — resolve each identifier from left to
    right and reject on the first one that does not exist."
    PRD §2.8: "Each missing identifier maps to its own not-found error: ...
    ERR_STOP_NOT_FOUND."

    Design: Corner/state_machines/remove_unknown_stop_returns_stop_not_found
    """
    depot = make_depot(api)
    team = make_team(api, depot["id"])
    route = make_route(api, depot["id"], team["id"])
    resp = api.remove_stop(route["id"], UNKNOWN_UUID, PLANNER)
    validate_error(resp, ApiErrorId.ERR_STOP_NOT_FOUND.value)


# --- Immediate reconciliation (corner consistency) ---

def test_committed_weight_visible_immediately_after_add(api):
    """PRD §3.4: "committed_weight_lbs is the sum of their orders' weight_lbs."
    PRD §2.7: "Derived aggregates are always recomputed from their source facts
    rather than incrementally patched in isolation. A route's committed load
    (committed_stops, committed_weight_lbs, committed_volume_cuft) is recomputed
    whenever a stop is added, removed, completed, or skipped."

    Design: Corner/consistency_model/committed_weight_visible_same_request_after_add
    """
    ns = setup_scheduled_order(api, order_overrides={"item_description": "Cabinet", "weight_lbs": 150, "volume_cuft": 25})
    route = make_route(api, ns["depot"]["id"], ns["team"]["id"])
    add_route_stop(api, route["id"], ns["order"]["id"], ns["window"]["id"])
    refreshed = validate_success(api.get_route(route["id"], PLANNER))
    assert refreshed["committed_weight_lbs"] == 150
    assert refreshed["committed_stops"] == 1


# --- Difficulty: weight capacity boundary ---

def _weight_boundary_setup(api, include_third=False):
    depot = make_depot(api)
    team = make_team(api, depot["id"], max_daily_weight_lbs=500, max_daily_volume_cuft=10000)
    cust = make_customer(api)
    o1 = make_order(api, cust["id"], item_description="A", weight_lbs=300, volume_cuft=10)
    w1 = reserve_order_window(api, o1, team["id"], window_start_min=480, window_end_min=540)
    o2 = make_order(api, cust["id"], item_description="B", weight_lbs=200, volume_cuft=10)
    w2 = reserve_order_window(api, o2, team["id"], window_start_min=600, window_end_min=660)
    route = make_route(api, depot["id"], team["id"])
    ctx = {"route": route, "o1": o1, "w1": w1, "o2": o2, "w2": w2}
    if include_third:
        o3 = make_order(api, cust["id"], item_description="C", weight_lbs=1, volume_cuft=10)
        w3 = reserve_order_window(api, o3, team["id"], window_start_min=700, window_end_min=760)
        ctx["o3"] = o3
        ctx["w3"] = w3
    return ctx


def test_add_stop_at_exact_weight_capacity_succeeds(api):
    """PRD §3.4: "its committed_weight_lbs plus the order's weight_lbs at or below
    max_daily_weight_lbs (ERR_ROUTE_WEIGHT_EXCEEDED)."

    Design: Difficulty/boundary_precision_check/route_weight_capacity_boundary
    """
    ctx = _weight_boundary_setup(api)
    add_route_stop(api, ctx["route"]["id"], ctx["o1"]["id"], ctx["w1"]["id"])  # committed 300
    add_route_stop(api, ctx["route"]["id"], ctx["o2"]["id"], ctx["w2"]["id"])  # committed exactly 500
    route = validate_success(api.get_route(ctx["route"]["id"], PLANNER))
    assert route["committed_weight_lbs"] == 500, f"expected 500 at boundary, got {route['committed_weight_lbs']}"


def test_add_stop_exceeding_weight_capacity_rejected(api):
    """PRD §3.4: "its committed_weight_lbs plus the order's weight_lbs at or below
    max_daily_weight_lbs (ERR_ROUTE_WEIGHT_EXCEEDED)."

    Design: Difficulty/boundary_precision_check/route_weight_capacity_boundary
    """
    ctx = _weight_boundary_setup(api, include_third=True)
    add_route_stop(api, ctx["route"]["id"], ctx["o1"]["id"], ctx["w1"]["id"])
    add_route_stop(api, ctx["route"]["id"], ctx["o2"]["id"], ctx["w2"]["id"])  # committed 500
    resp = api.add_stop(ctx["route"]["id"], add_stop_payload(ctx["o3"]["id"], ctx["w3"]["id"]), PLANNER)  # -> 501
    validate_error(resp, ApiErrorId.ERR_ROUTE_WEIGHT_EXCEEDED.value)


# --- Difficulty: capacity conservation on add + remove ---

def test_route_weight_conserved_after_add_then_remove(api):
    """PRD §3.4: "The route's committed aggregates are always the sum over the
    route's stops whose status is PLANNED or COMPLETED (stops that are SKIPPED are
    excluded)."
    PRD §3.4: "Removing a stop is allowed only while the route is still in
    PLANNING; it drives the stop PLANNED → SKIPPED, returns the order to
    SCHEDULED, clears the order's active_stop_id, and recomputes the route's
    committed load so the released capacity becomes available again."

    Design: Difficulty/compensating_invariant/route_weight_conservation_on_add_remove
    """
    ns = setup_scheduled_order(api, order_overrides={"item_description": "Cabinet", "weight_lbs": 150, "volume_cuft": 25})
    route = make_route(api, ns["depot"]["id"], ns["team"]["id"])
    stop = add_route_stop(api, route["id"], ns["order"]["id"], ns["window"]["id"])
    validate_success(api.remove_stop(route["id"], stop["id"], PLANNER))
    refreshed = validate_success(api.get_route(route["id"], PLANNER))
    assert refreshed["committed_weight_lbs"] == 0
    assert refreshed["committed_stops"] == 0


def test_remove_stop_returns_order_to_scheduled(api):
    """PRD §3.4: "Removing a stop ... drives the stop PLANNED → SKIPPED, returns
    the order to SCHEDULED, clears the order's active_stop_id, and recomputes the
    route's committed load so the released capacity becomes available again."

    Design: Difficulty/compensating_invariant/route_weight_conservation_on_add_remove
    """
    ns = setup_scheduled_order(api, order_overrides={"item_description": "Cabinet", "weight_lbs": 150, "volume_cuft": 25})
    route = make_route(api, ns["depot"]["id"], ns["team"]["id"])
    stop = add_route_stop(api, route["id"], ns["order"]["id"], ns["window"]["id"])
    removed = validate_success(api.remove_stop(route["id"], stop["id"], PLANNER))
    assert removed["status"] == "SKIPPED"
    order = validate_success(api.get_order(ns["order"]["id"], PLANNER))
    assert order["status"] == "SCHEDULED"


# --- Difficulty: state check pre-empts the fiscal check ---

def _state_vs_fiscal_setup(api):
    depot = make_depot(api)
    team = make_team(api, depot["id"], max_daily_weight_lbs=500)
    cust = make_customer(api)
    o1 = make_order(api, cust["id"], item_description="Fridge", weight_lbs=400, volume_cuft=40)
    w1 = reserve_order_window(api, o1, team["id"], window_start_min=480, window_end_min=600)
    o2 = make_order(api, cust["id"], item_description="Dryer", weight_lbs=200, volume_cuft=30)
    w2 = reserve_order_window(api, o2, team["id"], window_start_min=660, window_end_min=780)
    route = make_route(api, depot["id"], team["id"])
    add_route_stop(api, route["id"], o1["id"], w1["id"])  # committed_weight 400
    return {"depot": depot, "team": team, "route": route, "o2": o2, "w2": w2}


def test_state_error_preempts_weight_error_on_dispatched_route(api):
    """PRD §2.9: "State legality — the target resource is in a state that permits
    the requested transition; a general failure yields ERR_INVALID_STATE."
    PRD §2.9: "Capacity (fiscal) rules — the per-route stop, weight, and volume
    ceilings."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_add_stop
    """
    from test_helpers import make_dock
    ctx = _state_vs_fiscal_setup(api)
    dock = make_dock(api, ctx["depot"]["id"])
    book_appointment(api, ctx["route"]["id"], dock["id"])
    dispatch(api, ctx["route"]["id"])  # route -> DISPATCHED
    # Adding o2 violates BOTH state (route not PLANNING) and weight (400+200 > 500).
    resp = api.add_stop(ctx["route"]["id"], add_stop_payload(ctx["o2"]["id"], ctx["w2"]["id"]), PLANNER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_weight_error_surfaces_when_route_state_legal(api):
    """PRD §2.9: "Capacity (fiscal) rules — the per-route stop, weight, and volume
    ceilings." PRD §3.4: "its committed_weight_lbs plus the order's weight_lbs at
    or below max_daily_weight_lbs (ERR_ROUTE_WEIGHT_EXCEEDED)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_add_stop
    """
    ctx = _state_vs_fiscal_setup(api)
    # Route left in PLANNING: the state check passes, so the fiscal ceiling surfaces.
    resp = api.add_stop(ctx["route"]["id"], add_stop_payload(ctx["o2"]["id"], ctx["w2"]["id"]), PLANNER)
    validate_error(resp, ApiErrorId.ERR_ROUTE_WEIGHT_EXCEEDED.value)
