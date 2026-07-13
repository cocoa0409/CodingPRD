"""Dispatch preconditions, field proof-of-delivery, and the multi-hop cascades
that fire on refusal, on dock closure, and on the route-stop fork."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    record_attempt_payload, reserve_window_payload,
    make_team, make_dock,
    make_delivery_lead_headers,
    reserve_order_window, add_route_stop, book_appointment, dispatch, record_lead_attempt,
    setup_scheduled_order, setup_routed_order, setup_out_for_delivery, setup_refused_once,
    setup_network, make_order, make_route,
    TEST_USERS,
)

PLANNER = TEST_USERS["dispatch_planner_headers"]
DOCK = TEST_USERS["dock_coordinator_headers"]


# --- Corner state-machine / validation checks ---

def test_dispatch_already_dispatched_route_rejected(api):
    """PRD §3.5: "Dispatch moves the route PLANNING → DISPATCHED and is refused
    unless the route is in PLANNING, has committed_stops of at least 1, and has
    dock_ready true."

    Design: Corner/state_machines/dispatch_already_dispatched_route_rejected
    """
    ns = setup_out_for_delivery(api)
    validate_error(api.dispatch_route(ns["route"]["id"], PLANNER), ApiErrorId.ERR_INVALID_STATE.value)


def test_close_route_with_planned_stop_not_ready(api):
    """PRD §3.6: "Closing moves the route DISPATCHED → CLOSED and is refused
    unless the route is DISPATCHED (ERR_INVALID_STATE) and every one of its stops
    has reached a terminal state — that is, each RouteStop is COMPLETED or
    SKIPPED; a lingering PLANNED stop is rejected with ERR_ROUTE_NOT_READY_TO_CLOSE."

    Design: Corner/state_machines/close_route_with_planned_stop_not_ready
    """
    ns = setup_out_for_delivery(api)
    validate_error(api.close_route(ns["route"]["id"], PLANNER), ApiErrorId.ERR_ROUTE_NOT_READY_TO_CLOSE.value)


def test_attempt_on_scheduled_order_rejected(api):
    """PRD §3.5: "the DeliveryLead records a delivery attempt against an order
    that is OUT_FOR_DELIVERY."
    PRD §2.9: "State legality — the target resource is in a state that permits the
    requested transition; a general failure yields ERR_INVALID_STATE."

    Design: Corner/state_machines/attempt_on_scheduled_order_returns_invalid_state
    """
    ns = setup_scheduled_order(api)
    headers = make_delivery_lead_headers(ns["team"]["id"])
    payload = record_attempt_payload("DELIVERED", placement="THRESHOLD", signature_captured=True, photo_count=1)
    validate_error(api.record_attempt(ns["order"]["id"], payload, headers), ApiErrorId.ERR_INVALID_STATE.value)


def test_delivered_attempt_missing_pod_rejected(api):
    """PRD §3.5: "Proof of delivery is mandatory: signature_captured must be true
    and photo_count must be at least 1, otherwise the attempt is rejected with
    ERR_POD_REQUIRED."

    Design: Corner/validations/delivered_attempt_missing_pod_rejected
    """
    ns = setup_out_for_delivery(api)
    headers = make_delivery_lead_headers(ns["team"]["id"])
    payload = record_attempt_payload("DELIVERED", placement="THRESHOLD", signature_captured=False, photo_count=0)
    validate_error(api.record_attempt(ns["order"]["id"], payload, headers), ApiErrorId.ERR_POD_REQUIRED.value)


# --- Difficulty: dispatch depends on a booked dock appointment ---

def test_dispatch_without_dock_appointment_rejected(api):
    """PRD §3.5: "a dispatch attempt without a booked dock appointment is rejected
    with ERR_DOCK_APPOINTMENT_MISSING."

    Design: Difficulty/cross_entity_state_dependency/dispatch_requires_dock_appointment
    """
    ns = setup_routed_order(api)  # PLANNED stop, dock_ready false
    validate_error(api.dispatch_route(ns["route"]["id"], PLANNER), ApiErrorId.ERR_DOCK_APPOINTMENT_MISSING.value)


def test_dispatch_with_dock_appointment_succeeds(api):
    """PRD §3.5: "Dispatch moves the route PLANNING → DISPATCHED ... Dispatch
    cascades to the freight: each PLANNED stop's order advances
    ROUTED → OUT_FOR_DELIVERY."

    Design: Difficulty/cross_entity_state_dependency/dispatch_requires_dock_appointment
    """
    ns = setup_routed_order(api)
    book_appointment(api, ns["route"]["id"], ns["dock"]["id"])
    route = validate_success(api.dispatch_route(ns["route"]["id"], PLANNER))
    assert route["status"] == "DISPATCHED"
    order = validate_success(api.get_order(ns["order"]["id"], PLANNER))
    assert order["status"] == "OUT_FOR_DELIVERY"


# --- Difficulty: refusal depth-3 cascade ---

def test_refusal_sets_order_refused_retry_and_bumps_count(api):
    """PRD §3.5: "A failed attempt (outcome of REFUSED, CUSTOMER_UNAVAILABLE, or
    DAMAGED) drives the order OUT_FOR_DELIVERY → REFUSED_RETRY and triggers a
    three-hop cascade. First, the attempt is created and the order's
    reattempt_count increases by one."

    Design: Difficulty/transitive_cascade/refusal_depth3_cascade
    """
    ns = setup_out_for_delivery(api, order_overrides={"item_description": "Cabinet", "weight_lbs": 150, "volume_cuft": 25})
    record_lead_attempt(api, ns["order"]["id"], ns["team"]["id"], "REFUSED", refusal_reason="damaged box")
    order = validate_success(api.get_order(ns["order"]["id"], PLANNER))
    assert order["status"] == "REFUSED_RETRY"
    assert order["reattempt_count"] == 1


def test_refusal_skips_stop_and_releases_route_capacity(api):
    """PRD §3.5: "Second, the order's active RouteStop moves PLANNED → SKIPPED.
    Third, because a skipped stop no longer occupies capacity, the route's
    committed_stops, committed_weight_lbs, and committed_volume_cuft are
    recomputed so the freed capacity returns to the route."

    Design: Difficulty/transitive_cascade/refusal_depth3_cascade
    """
    ns = setup_out_for_delivery(api, order_overrides={"item_description": "Cabinet", "weight_lbs": 150, "volume_cuft": 25})
    stop_id = ns["stop"]["id"]
    record_lead_attempt(api, ns["order"]["id"], ns["team"]["id"], "REFUSED", refusal_reason="damaged box")
    stop = validate_success(api.get_route_stop(stop_id, PLANNER))
    assert stop["status"] == "SKIPPED"
    route = validate_success(api.get_route(ns["route"]["id"], PLANNER))
    assert route["committed_weight_lbs"] == 0
    assert route["committed_stops"] == 0


# --- Difficulty: dock-close depth-2 cascade ---

def _dock_ready_route(api):
    net = setup_network(api)
    route = make_route(api, net["depot"]["id"], net["team"]["id"])
    appt = book_appointment(api, route["id"], net["dock"]["id"])
    return {"dock": net["dock"], "route": route, "appointment": appt}


def test_dock_close_releases_booked_appointment(api):
    """PRD §3.4: "When a DockCoordinator closes a dock, its status moves
    OPEN → CLOSED (only from OPEN, else ERR_INVALID_STATE), and the closure
    cascades: every BOOKED appointment on that dock is moved to RELEASED."

    Design: Difficulty/transitive_cascade/dock_close_depth2_cascade
    """
    ctx = _dock_ready_route(api)
    validate_success(api.close_dock(ctx["dock"]["id"], DOCK))
    appt = validate_success(api.get_dock_appointment(ctx["appointment"]["id"], PLANNER))
    assert appt["status"] == "RELEASED"


def test_dock_close_clears_route_dock_link(api):
    """PRD §3.4: "for each such appointment the owning route's dock_appointment_id
    is cleared and its dock_ready set back to false."

    Design: Difficulty/transitive_cascade/dock_close_depth2_cascade
    """
    ctx = _dock_ready_route(api)
    validate_success(api.close_dock(ctx["dock"]["id"], DOCK))
    route = validate_success(api.get_route(ctx["route"]["id"], PLANNER))
    assert route["dock_ready"] is False
    assert route["dock_appointment_id"] is None


# --- Difficulty: route-stop fork COMPLETED vs SKIPPED ---

def _two_stop_dispatched_route(api):
    net = setup_network(api)
    o1 = make_order(api, net["customer"]["id"], item_description="Chair", weight_lbs=100, volume_cuft=20)
    w1 = reserve_order_window(api, o1, net["team"]["id"], window_start_min=480, window_end_min=600)
    o2 = make_order(api, net["customer"]["id"], item_description="Desk", weight_lbs=150, volume_cuft=25)
    w2 = reserve_order_window(api, o2, net["team"]["id"], window_start_min=660, window_end_min=780)
    route = make_route(api, net["depot"]["id"], net["team"]["id"])
    s1 = add_route_stop(api, route["id"], o1["id"], w1["id"])
    s2 = add_route_stop(api, route["id"], o2["id"], w2["id"])
    book_appointment(api, route["id"], net["dock"]["id"])
    dispatch(api, route["id"])
    return {"team": net["team"], "route": route, "o1": o1, "o2": o2, "s1": s1, "s2": s2}


def test_stop_fork_completed_and_skipped_statuses(api):
    """PRD §3.5: "moves the order's active RouteStop PLANNED → COMPLETED (a
    completed stop keeps occupying route capacity)."
    PRD §3.5: "Second, the order's active RouteStop moves PLANNED → SKIPPED."

    Design: Difficulty/non_linear_state_machine/routestop_fork_completed_vs_skipped
    """
    ctx = _two_stop_dispatched_route(api)
    record_lead_attempt(api, ctx["o1"]["id"], ctx["team"]["id"], "DELIVERED",
                        placement="THRESHOLD", signature_captured=True, photo_count=1)
    record_lead_attempt(api, ctx["o2"]["id"], ctx["team"]["id"], "REFUSED", refusal_reason="not home")
    s1 = validate_success(api.get_route_stop(ctx["s1"]["id"], PLANNER))
    s2 = validate_success(api.get_route_stop(ctx["s2"]["id"], PLANNER))
    assert s1["status"] == "COMPLETED"
    assert s2["status"] == "SKIPPED"


def test_stop_fork_route_retains_only_completed_capacity(api):
    """PRD §3.4: "The route's committed aggregates are always the sum over the
    route's stops whose status is PLANNED or COMPLETED (stops that are SKIPPED are
    excluded): committed_stops is the count of those stops, committed_weight_lbs
    is the sum of their orders' weight_lbs."

    Design: Difficulty/non_linear_state_machine/routestop_fork_completed_vs_skipped
    """
    ctx = _two_stop_dispatched_route(api)
    record_lead_attempt(api, ctx["o1"]["id"], ctx["team"]["id"], "DELIVERED",
                        placement="THRESHOLD", signature_captured=True, photo_count=1)
    record_lead_attempt(api, ctx["o2"]["id"], ctx["team"]["id"], "REFUSED", refusal_reason="not home")
    route = validate_success(api.get_route(ctx["route"]["id"], PLANNER))
    assert route["committed_weight_lbs"] == 100  # only the COMPLETED 100-lb stop remains
    assert route["committed_stops"] == 1


# --- Difficulty: cyclic reattempt loop ---

def test_refused_order_enters_refused_retry(api):
    """PRD §3.5: "A failed attempt (outcome of REFUSED, CUSTOMER_UNAVAILABLE, or
    DAMAGED) drives the order OUT_FOR_DELIVERY → REFUSED_RETRY ... the order's
    reattempt_count increases by one."

    Design: Difficulty/non_linear_state_machine/order_reattempt_cycle
    """
    ns = setup_refused_once(api)
    order = validate_success(api.get_order(ns["order"]["id"], PLANNER))
    assert order["status"] == "REFUSED_RETRY"
    assert order["reattempt_count"] == 1


def test_refused_order_reschedules_back_to_scheduled(api):
    """PRD §3.3: "From REFUSED_RETRY, reserving a fresh window re-enters the
    scheduling loop and advances REFUSED_RETRY → SCHEDULED; this reschedule is
    allowed only while reattempt_count is strictly less than the ceiling of 2
    reattempts, otherwise ERR_MAX_REATTEMPTS."

    Design: Difficulty/non_linear_state_machine/order_reattempt_cycle
    """
    ns = setup_refused_once(api)
    order = validate_success(api.get_order(ns["order"]["id"], PLANNER))
    validate_success(
        api.reserve_window(
            order["id"],
            reserve_window_payload(ns["team"]["id"], order["version"], service_date="2026-06-02"),
            PLANNER,
        ),
        expected_status=201,
    )
    refreshed = validate_success(api.get_order(order["id"], PLANNER))
    assert refreshed["status"] == "SCHEDULED"
    assert refreshed["reattempt_count"] == 1


# --- Difficulty: referential check pre-empts safety (POD) check ---

def _wrong_team_setup(api):
    ns = setup_out_for_delivery(api)  # order OFD on team A
    team_b = make_team(api, ns["depot"]["id"], team_name="TB", lead_name="Ben", member2_name="Ola")
    return {"order": ns["order"], "team_a": ns["team"], "team_b": team_b}


def test_wrong_team_attempt_preempts_pod_check(api):
    """PRD §3.5: "The acting crew must be the route team of the order's active
    stop, else ERR_STOP_ORDER_MISMATCH."
    PRD §2.9: "8. Referential business rules — cross-entity consistency such as
    already-routed, team/route mismatch, window/route date mismatch, region
    mismatch, and stop/order crew mismatch. 9. Safety rules — crew in service,
    crew certification, and proof-of-delivery completeness."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_safety_on_attempt
    """
    ctx = _wrong_team_setup(api)
    headers = make_delivery_lead_headers(ctx["team_b"]["id"])  # wrong crew
    payload = record_attempt_payload("DELIVERED", placement="THRESHOLD", signature_captured=False, photo_count=0)
    validate_error(api.record_attempt(ctx["order"]["id"], payload, headers), ApiErrorId.ERR_STOP_ORDER_MISMATCH.value)


def test_pod_check_surfaces_when_crew_matches(api):
    """PRD §3.5: "Proof of delivery is mandatory: signature_captured must be true
    and photo_count must be at least 1, otherwise the attempt is rejected with
    ERR_POD_REQUIRED."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_safety_on_attempt
    """
    ns = setup_out_for_delivery(api)
    headers = make_delivery_lead_headers(ns["team"]["id"])  # correct crew: referential check passes
    payload = record_attempt_payload("DELIVERED", placement="THRESHOLD", signature_captured=False, photo_count=0)
    validate_error(api.record_attempt(ns["order"]["id"], payload, headers), ApiErrorId.ERR_POD_REQUIRED.value)
