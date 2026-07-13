"""Fee reconciliation (quote vs final), route payout settlement rounding, crew
liability (estimated vs settled), and the settle/void money conservation."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_order_payload,
    make_customer, make_depot, make_team, make_order, make_route,
    reserve_order_window, add_route_stop, book_appointment, dispatch, record_lead_attempt,
    setup_out_for_delivery, setup_delivered_order, setup_settled_order, setup_network,
    TEST_USERS,
)

PLANNER = TEST_USERS["dispatch_planner_headers"]

WG_ASSEMBLY_TEAM = {"white_glove_certified": True, "assembly_certified": True}
WG_ORDER = {
    "item_description": "Sofa", "weight_lbs": 200, "volume_cuft": 30,
    "declared_value_cents": 250000, "service_level": "WHITE_GLOVE",
    "assembly_required": True, "haul_away_required": True, "stair_flights": 6,
}


# --- Corner state-machine guards on settlement lifecycle ---

def test_cancel_delivered_order_rejected(api):
    """PRD §3.2: "Cancellation is permitted only while the order is in CREATED,
    SCHEDULED, or REFUSED_RETRY; from any other state the request is rejected with
    ERR_INVALID_STATE."

    Design: Corner/state_machines/cancel_delivered_order_returns_invalid_state
    """
    ns = setup_delivered_order(api)
    validate_error(api.cancel_order(ns["order"]["id"], PLANNER), ApiErrorId.ERR_INVALID_STATE.value)


def test_settle_non_delivered_order_rejected(api):
    """PRD §3.6: "Settling a delivered order is a DispatchPlanner action that
    moves the order DELIVERED → SETTLED (rejected with ERR_INVALID_STATE unless
    the order is DELIVERED)."

    Design: Corner/state_machines/settle_non_delivered_order_returns_invalid_state
    """
    cust = make_customer(api)
    order = make_order(api, cust["id"])  # CREATED
    validate_error(api.settle_order(order["id"], PLANNER), ApiErrorId.ERR_INVALID_STATE.value)


# --- Difficulty: quote vs final diverge on one order ---

def test_order_quote_computed_at_creation(api):
    """PRD §3.2: "Take the sum of the service base and the weight surcharge and
    multiply it by the white-glove multiplier — 1.15 when the ordered
    service_level is WHITE_GLOVE, and 1.00 otherwise — then round that product
    half up to a whole cent."
    PRD §3.2: "To the core charge, add the stair charge ... Then add a flat 2500
    cents when assembly_required is true, and a flat 3000 cents when
    haul_away_required is true. The resulting sum is quoted_fee_cents."

    Design: Difficulty/dual_variant_calc/order_quote_vs_final_diverges
    """
    cust = make_customer(api)
    order = validate_success(api.create_order(create_order_payload(cust["id"], **WG_ORDER), PLANNER),
                             expected_status=201)
    # round((12000+3500)*1.15)=17825 +4000 stair +2500 assembly +3000 haul = 27325
    assert order["quoted_fee_cents"] == 27325, f"expected 27325, got {order['quoted_fee_cents']}"


def test_order_final_fee_uses_actual_placement_and_disposal(api):
    """PRD §3.6: "Determine the placement level from the delivering attempt's
    placement, falling back to the order's service_level when placement was
    omitted. Take the service base for that actual level ... Add 2500 cents for
    assembly only when the delivering attempt's assembly_completed is true. Add
    the disposal charge: when debris_weight_lbs is greater than 0, divide the
    debris weight by the 50-pound disposal unit, round that quotient up to the
    next whole unit, and multiply by 1000 cents per unit."

    Design: Difficulty/dual_variant_calc/order_quote_vs_final_diverges
    """
    ns = setup_out_for_delivery(api, order_overrides=WG_ORDER, team_overrides=WG_ASSEMBLY_TEAM)
    record_lead_attempt(
        api, ns["order"]["id"], ns["team"]["id"], "DELIVERED",
        placement="ROOM_OF_CHOICE", signature_captured=True, photo_count=2,
        assembly_completed=False, debris_weight_lbs=120,
    )
    order = validate_success(api.get_order(ns["order"]["id"], PLANNER))
    # ROOM_OF_CHOICE 7000 + 3500 weight = 10500 core, +4000 stair, +0 assembly,
    # +ceil(120/50)*1000 = 3000 disposal, +0 reattempt = 17500
    assert order["final_fee_cents"] == 17500, f"expected 17500, got {order['final_fee_cents']}"
    assert order["status"] == "DELIVERED"


# --- Difficulty: team estimated vs settled liability ---

def test_estimated_liability_from_open_white_glove_window(api):
    """PRD §3.7: "estimated_liability_points ... is the sum, over each of the
    crew's windows whose status is RESERVED or CONFIRMED and whose order's
    service_level is WHITE_GLOVE, of the order's declared_value_cents divided by
    100000 and rounded up to the next whole point."

    Design: Difficulty/dual_variant_calc/team_estimated_vs_settled_liability
    """
    depot = make_depot(api)
    team = make_team(api, depot["id"], white_glove_certified=True)
    cust = make_customer(api)
    order = make_order(api, cust["id"], item_description="Wardrobe", weight_lbs=50, volume_cuft=10,
                       declared_value_cents=250000, service_level="WHITE_GLOVE")
    reserve_order_window(api, order, team["id"])
    refreshed = validate_success(api.get_team(team["id"], PLANNER))
    # ceil(250000 / 100000) = 3
    assert refreshed["estimated_liability_points"] == 3, f"expected 3, got {refreshed['estimated_liability_points']}"


def test_settled_liability_from_damaged_attempt(api):
    """PRD §3.7: "settled_liability_points, is realized damage: it is the sum,
    over every DAMAGED attempt on the crew's orders, of a fixed penalty — 50
    points for MAJOR severity and 20 points for MINOR severity."

    Design: Difficulty/dual_variant_calc/team_estimated_vs_settled_liability
    """
    ns = setup_out_for_delivery(api)
    record_lead_attempt(api, ns["order"]["id"], ns["team"]["id"], "DAMAGED",
                        damage_severity="MINOR", refusal_reason="corner chipped")
    team = validate_success(api.get_team(ns["team"]["id"], PLANNER))
    assert team["settled_liability_points"] == 20, f"expected 20, got {team['settled_liability_points']}"


# --- Difficulty: route settlement per-stop rounding ---

def _two_white_glove_delivered_route(api):
    net = setup_network(api, team_overrides=WG_ASSEMBLY_TEAM)
    o1 = make_order(api, net["customer"]["id"], item_description="Sofa 1", weight_lbs=200, volume_cuft=30,
                    declared_value_cents=100000, service_level="WHITE_GLOVE")
    w1 = reserve_order_window(api, o1, net["team"]["id"], window_start_min=480, window_end_min=600)
    o2 = make_order(api, net["customer"]["id"], item_description="Sofa 2", weight_lbs=200, volume_cuft=30,
                    declared_value_cents=100000, service_level="WHITE_GLOVE")
    w2 = reserve_order_window(api, o2, net["team"]["id"], window_start_min=660, window_end_min=780)
    route = make_route(api, net["depot"]["id"], net["team"]["id"])
    add_route_stop(api, route["id"], o1["id"], w1["id"])
    add_route_stop(api, route["id"], o2["id"], w2["id"])
    book_appointment(api, route["id"], net["dock"]["id"])
    dispatch(api, route["id"])
    record_lead_attempt(api, o1["id"], net["team"]["id"], "DELIVERED",
                        placement="WHITE_GLOVE", signature_captured=True, photo_count=2)
    record_lead_attempt(api, o2["id"], net["team"]["id"], "DELIVERED",
                        placement="WHITE_GLOVE", signature_captured=True, photo_count=2)
    return route


def test_route_settlement_rounds_per_stop_then_sums(api):
    """PRD §3.6: "On close, the crew payout route_settlement_cents is computed:
    for each COMPLETED stop, multiply that stop's order's final_fee_cents by the
    payout rate of 0.375 and round the result half up to a whole cent; then sum
    those per-stop rounded amounts. Rounding is applied to each completed stop's
    payout before summing, not to the aggregate."

    Design: Difficulty/combinatorial_formula/route_settlement_per_stop_rounding_mode_b
    """
    route = _two_white_glove_delivered_route(api)
    closed = validate_success(api.close_route(route["id"], PLANNER))
    # final_fee 17825 each; round(17825*0.375)=round(6684.375)=6684 per stop; 6684*2 = 13368
    assert closed["route_settlement_cents"] == 13368, f"expected 13368, got {closed['route_settlement_cents']}"


def test_route_close_marks_route_closed(api):
    """PRD §3.6: "A route is closed by the DispatchPlanner after dispatch. Closing
    moves the route DISPATCHED → CLOSED."

    Design: Difficulty/combinatorial_formula/route_settlement_per_stop_rounding_mode_b
    """
    route = _two_white_glove_delivered_route(api)
    closed = validate_success(api.close_route(route["id"], PLANNER))
    assert closed["status"] == "CLOSED"
    assert closed["route_settlement_cents"] is not None


# --- Difficulty: customer balance conservation on settle + void ---

def test_settle_credits_customer_ledger_by_final_fee(api):
    """PRD §3.6: "Settling a delivered order ... posts the forward money leg: the
    customer's outstanding_balance_cents increases by the order's final_fee_cents.
    A customer's outstanding_balance_cents is, by construction, the sum of
    final_fee_cents over that customer's settled orders."

    Design: Difficulty/compensating_invariant/customer_balance_conservation_on_settle_void
    """
    ns = setup_settled_order(api)  # THRESHOLD weight 100 -> final_fee 5500
    order = validate_success(api.get_order(ns["order"]["id"], PLANNER))
    assert order["final_fee_cents"] == 5500
    customer = validate_success(api.get_customer(ns["customer"]["id"], PLANNER))
    assert customer["outstanding_balance_cents"] == 5500


def test_void_debits_customer_ledger_back_to_zero(api):
    """PRD §3.6: "A settled delivery may be reversed: voiding it moves the order
    SETTLED → RETURNED (only from SETTLED) and posts the compensating money leg,
    decreasing the customer's outstanding_balance_cents by the same
    final_fee_cents so the pair nets to zero."

    Design: Difficulty/compensating_invariant/customer_balance_conservation_on_settle_void
    """
    ns = setup_settled_order(api)
    voided = validate_success(api.void_delivery(ns["order"]["id"], PLANNER))
    assert voided["status"] == "RETURNED"
    customer = validate_success(api.get_customer(ns["customer"]["id"], PLANNER))
    assert customer["outstanding_balance_cents"] == 0
