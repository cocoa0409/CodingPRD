"""Routing-mode selection at the hot-handoff span boundary, buffered hub-slot
collisions, and hub consolidation over an empty eligible set.

Every rule under test here reads the parent production window's handoff interval
rather than anything in the request body. The harness restarts the API server
before every test, so each test below builds its whole world from scratch
through the endpoints of PRD 4.
"""

from test_helpers import fixtures as fx
from test_helpers import (
    ADMIN_HEADERS,
    DINER_ONE_HEADERS,
    DINER_THREE_HEADERS,
    DINER_TWO_HEADERS,
    FINANCE_ONE_HEADERS,
    ApiErrorId,
    assert_charge_breakdown,
    assert_fields,
    assert_order,
    assert_pickup_hub,
    consolidate_payload,
    validate_error,
    validate_success,
)

# --------------------------------------------------------------------------
# Shared world builders. Every helper is a plain function called from inside a
# test, so nothing leaks between tests.
# --------------------------------------------------------------------------

#: A 1000-cent dish, quantity 1: a 1000-cent subtotal, a 90-cent diner service
#: fee and no cold-chain surcharge, so the total charge is 1090 cents.
_UNIT_PRICE_CENTS = 1000
_TOTAL_CHARGE_CENTS = 1090

_HOT_ITEM = {
    "name": "Hot Focaccia",
    "food_category": "NON_TCS",
    "allergens": ["WHEAT"],
    "shelf_life_days": 2,
    "requires_refrigeration": False,
    "handoff_mode": "SAME_DAY_HOT",
    "unit_price_cents": _UNIT_PRICE_CENTS,
}

_CHILL_ITEM = {
    "name": "Sesame Buns",
    "food_category": "BAKED_NON_TCS",
    "allergens": ["SESAME", "WHEAT"],
    "shelf_life_days": 3,
    "requires_refrigeration": False,
    "handoff_mode": "BATCH_COOK_AND_CHILL",
    "unit_price_cents": _UNIT_PRICE_CENTS,
}


def _two_spans_scenario(api):
    """One SAME_DAY_HOT dish, one DOOR_DELIVERY zone and two windows.

    Window `window_120` spans 16:00 to 18:00 on 2026-08-08, exactly 120 minutes.
    Window `window_121` spans 16:00 to 18:01 on 2026-08-09, one minute wider.
    The two sit on different days, so they never overlap for the cook, and the
    order placed on each carries an identical payload.
    """
    setup = fx.selling_cook(
        api,
        cook_overrides={"legal_name": "Milo Rossi", "weekly_capacity_meals": 10},
        item_overrides=dict(_HOT_ITEM),
        window_overrides={
            "handoff_start_at": "2026-08-08T16:00:00Z",
            "handoff_end_at": "2026-08-08T18:00:00Z",
            "capacity_meals": 5,
        },
        zone_overrides={"service_mode": "DOOR_DELIVERY", "max_cold_chain_minutes": 180},
    )
    setup["window_120"] = setup.window
    setup["window_121"] = fx.open_production_window(
        api,
        setup.cook,
        week_start_date="2026-08-03",
        order_cutoff_at="2026-08-05T00:00:00Z",
        handoff_start_at="2026-08-09T16:00:00Z",
        handoff_end_at="2026-08-09T18:01:00Z",
        capacity_meals=5,
    )
    return setup


def _order_on(api, setup, window, diner_headers):
    return fx.place_order(
        api,
        setup.menu_item["id"],
        window["id"],
        setup.zone["id"],
        quantity=1,
        diner_headers=diner_headers,
    )


def _consolidation_scenario(api):
    """One DOOR_DELIVERY window and one HUB_PICKUP window, both past their cutoff.

    The door window's only order is routed inside a DOOR_DELIVERY zone, so it can
    never be hub-routed; the hub window's only order is routed into the hub zone
    and therefore already holds a slot on CENTRAL.
    """
    setup = fx.selling_cook(
        api,
        cook_overrides={"legal_name": "Nia Abara", "weekly_capacity_meals": 10},
        item_overrides={
            "name": "Jollof Tray",
            "food_category": "NON_TCS",
            "allergens": ["WHEAT"],
            "shelf_life_days": 4,
            "unit_price_cents": _UNIT_PRICE_CENTS,
        },
        window_overrides={
            "handoff_start_at": "2026-08-08T16:00:00Z",
            "handoff_end_at": "2026-08-08T18:00:00Z",
            "capacity_meals": 5,
        },
        zone_overrides={"service_mode": "DOOR_DELIVERY", "max_cold_chain_minutes": 180},
    )
    hub_zone = fx.create_delivery_zone(
        api,
        setup.policy["id"],
        state_code="CA",
        service_mode="HUB_PICKUP",
        postal_codes=["94111"],
        max_cold_chain_minutes=240,
    )
    hub = fx.create_pickup_hub(
        api,
        hub_zone["id"],
        name="Central Hub",
        address="1 Market St",
        slot_capacity_orders=5,
        hub_window_start_at="2026-08-09T15:00:00Z",
        hub_window_end_at="2026-08-09T21:00:00Z",
    )
    hub_window = fx.open_production_window(
        api,
        setup.cook,
        week_start_date="2026-08-03",
        order_cutoff_at="2026-08-05T00:00:00Z",
        handoff_start_at="2026-08-09T16:00:00Z",
        handoff_end_at="2026-08-09T18:00:00Z",
        capacity_meals=5,
    )
    door_order = _order_on(api, setup, setup.window, DINER_ONE_HEADERS)
    hub_order = fx.place_order(
        api,
        setup.menu_item["id"],
        hub_window["id"],
        hub_zone["id"],
        quantity=1,
        diner_headers=DINER_TWO_HEADERS,
    )
    door_order = fx.route_order(api, door_order["id"])
    hub_order = fx.route_order(api, hub_order["id"])
    fx.set_clock(api, "2026-08-06T00:00:00Z")
    fx.advance_window(api, setup.window, "CUTOFF_PASSED")
    fx.advance_window(api, hub_window, "CUTOFF_PASSED")
    setup.update(
        hub=hub,
        hub_zone=hub_zone,
        hub_window=hub_window,
        door_window=setup.window,
        door_order=door_order,
        hub_order=hub_order,
    )
    return setup


def _hub_buffer_scenario(api, extra_hub_slots=None):
    """Three windows of one cook, pairwise non-overlapping, all feeding one hub zone.

    P runs 16:00 to 18:00, Q runs 18:30 to 20:00 and R runs 20:00 to 21:00, all on
    2026-08-09, so no pair overlaps for the cook. Widened by 45 minutes on each
    side, P covers 15:15 to 18:45, Q covers 17:45 to 20:45 and R covers 19:15 to
    21:45, so P and Q collide on a shared hub while P and R do not. Each window
    holds one quantity-1 order still sitting in PLACED.
    """
    setup = fx.selling_cook(
        api,
        cook_overrides={"legal_name": "Sana Qureshi", "weekly_capacity_meals": 5},
        item_overrides=dict(_CHILL_ITEM),
        window_overrides={
            "handoff_start_at": "2026-08-09T16:00:00Z",
            "handoff_end_at": "2026-08-09T18:00:00Z",
            "capacity_meals": 2,
        },
        zone_overrides={
            "service_mode": "HUB_PICKUP",
            "postal_codes": ["94111"],
            "max_cold_chain_minutes": 240,
        },
    )
    setup["window_p"] = setup.window
    setup["hub"] = fx.create_pickup_hub(
        api,
        setup.zone["id"],
        name="Central Hub",
        address="9 Pier Rd",
        slot_capacity_orders=5 if extra_hub_slots is None else extra_hub_slots,
        hub_window_start_at="2026-08-09T15:00:00Z",
        hub_window_end_at="2026-08-09T22:00:00Z",
    )
    setup["window_q"] = fx.open_production_window(
        api,
        setup.cook,
        week_start_date="2026-08-03",
        order_cutoff_at="2026-08-05T00:00:00Z",
        handoff_start_at="2026-08-09T18:30:00Z",
        handoff_end_at="2026-08-09T20:00:00Z",
        capacity_meals=2,
    )
    setup["window_r"] = fx.open_production_window(
        api,
        setup.cook,
        week_start_date="2026-08-03",
        order_cutoff_at="2026-08-05T00:00:00Z",
        handoff_start_at="2026-08-09T20:00:00Z",
        handoff_end_at="2026-08-09T21:00:00Z",
        capacity_meals=2,
    )
    setup["order_p"] = _order_on(api, setup, setup.window_p, DINER_ONE_HEADERS)
    setup["order_q"] = _order_on(api, setup, setup.window_q, DINER_TWO_HEADERS)
    setup["order_r"] = _order_on(api, setup, setup.window_r, DINER_THREE_HEADERS)
    return setup


def _two_hub_scenario(api):
    """The same colliding pair of windows, but the zone owns two hubs.

    CENTRAL_WIDE declares ten slots and CENTRAL_NARROW five, so once P's order
    holds one slot on CENTRAL_WIDE that hub still ranks first on free slots
    (9 against 5) even though it is the hub P's buffered interval blocks.
    """
    setup = _hub_buffer_scenario(api, extra_hub_slots=10)
    setup["wide_hub"] = setup.hub
    setup["narrow_hub"] = fx.create_pickup_hub(
        api,
        setup.zone["id"],
        name="Narrow Hub",
        address="4 Wharf Rd",
        slot_capacity_orders=5,
        hub_window_start_at="2026-08-09T15:00:00Z",
        hub_window_end_at="2026-08-09T22:00:00Z",
    )
    return setup


# --------------------------------------------------------------------------
# The 120-minute hot-handoff span boundary
# --------------------------------------------------------------------------
def test_01_a_handoff_span_of_exactly_120_minutes_routes_same_day_hot(api):
    """A window spanning exactly two hours keeps a SAME_DAY_HOT dish on the hot route.

    PRD: "An order qualifies for a same-day hot handoff only when all four of the following hold at once: the dish's `handoff_mode` is `SAME_DAY_HOT`; the zone's `service_mode` is `DOOR_DELIVERY`; the handoff span is at most 120 minutes, so a two-hour window qualifies and a window of 121 minutes does not; and either the dish's `food_category` is something other than `TCS`, or the cook's `verified_kitchen_type` is `COMMERCIAL_SHARED`."
    Design: Difficulty/boundary_precision_check/hot_handoff_span_120_admits_121_falls_back
    """
    setup = _two_spans_scenario(api)
    order = _order_on(api, setup, setup.window_120, DINER_ONE_HEADERS)

    routed = fx.route_order(api, order["id"])

    assert_order(
        routed,
        routing_mode="SAME_DAY_HOT",
        fulfillment_status="ROUTED",
        payment_status="AUTHORIZED",
        pickup_hub_id=None,
        subtotal_cents=_UNIT_PRICE_CENTS,
        cold_chain_surcharge_cents=0,
        total_charge_cents=_TOTAL_CHARGE_CENTS,
    )
    assert_charge_breakdown(routed)


def test_02_a_handoff_span_of_121_minutes_falls_back_to_batch_cook_and_chill(api):
    """One extra minute of handoff span degrades the identical order to the chilled route.

    PRD: "When all four hold, `routing_mode` is written as `SAME_DAY_HOT`; when any one fails, `routing_mode` is written as `BATCH_COOK_AND_CHILL`."
    Design: Difficulty/boundary_precision_check/hot_handoff_span_120_admits_121_falls_back
    """
    setup = _two_spans_scenario(api)
    order = _order_on(api, setup, setup.window_121, DINER_TWO_HEADERS)

    routed = fx.route_order(api, order["id"])

    assert_order(
        routed,
        routing_mode="BATCH_COOK_AND_CHILL",
        fulfillment_status="ROUTED",
        payment_status="AUTHORIZED",
        pickup_hub_id=None,
        subtotal_cents=_UNIT_PRICE_CENTS,
        cold_chain_surcharge_cents=0,
        total_charge_cents=_TOTAL_CHARGE_CENTS,
    )
    assert_charge_breakdown(routed)


# --------------------------------------------------------------------------
# Consolidation over an empty eligible set, and the idempotent re-run
# --------------------------------------------------------------------------
def test_03_consolidating_a_window_with_no_hub_routed_order_is_refused(api):
    """A window whose only order sits in a door-delivery zone yields an empty input set.

    PRD: "At least one order of that window must be hub-routed and sitting in `ROUTED` or `IN_PRODUCTION`, or the request is `ERR_NO_ELIGIBLE_ORDERS`."
    Design: Difficulty/boundary_precision_check/consolidation_empty_input_set_zero_cardinality
    """
    setup = _consolidation_scenario(api)

    resp = api.consolidate_pickup_hub(
        setup.hub["id"], consolidate_payload(setup.door_window["id"]), FINANCE_ONE_HEADERS
    )

    validate_error(resp, ApiErrorId.NO_ELIGIBLE_ORDERS, 422)
    door_order = fx.read_order(api, setup.door_order["id"])
    assert_order(
        door_order,
        pickup_hub_id=None,
        fulfillment_status="ROUTED",
        routing_mode="BATCH_COOK_AND_CHILL",
    )
    assert_pickup_hub(fx.read_hub(api, setup.hub["id"]), assigned_order_count=1, status="OPEN")


def test_04_consolidating_an_already_attached_order_counts_it_without_re_acquiring_a_slot(api):
    """Consolidation reports the one eligible order and leaves the slot count at one.

    PRD: "It sets `pickup_hub_id` on every eligible order of the window whose `pickup_hub_id` is not already this hub, and it increases the hub's `assigned_order_count` by the count of **newly attached** orders only — re-running the same consolidation therefore changes nothing."
    Design: Difficulty/boundary_precision_check/consolidation_empty_input_set_zero_cardinality
    """
    setup = _consolidation_scenario(api)

    resp = api.consolidate_pickup_hub(
        setup.hub["id"], consolidate_payload(setup.hub_window["id"]), FINANCE_ONE_HEADERS
    )

    projection = validate_success(resp, 200)
    assert_fields(
        projection,
        pickup_hub_id=setup.hub["id"],
        production_window_id=setup.hub_window["id"],
        consolidated_order_count=1,
        assigned_order_count=1,
        status="OPEN",
    )
    assert_order(fx.read_order(api, setup.hub_order["id"]), pickup_hub_id=setup.hub["id"])
    assert_pickup_hub(fx.read_hub(api, setup.hub["id"]), assigned_order_count=1, status="OPEN")


# --------------------------------------------------------------------------
# Buffered, closed hub intervals collide where half-open cook intervals do not
# --------------------------------------------------------------------------
def test_05_a_buffered_interval_collision_on_the_hub_refuses_the_route(api):
    """Q's order is refused on the hub P already occupies, though four slots are free.

    PRD: "The selected hub is examined for orders whose `pickup_hub_id` names it, whose `fulfillment_status` is `ROUTED`, `IN_PRODUCTION`, `HANDED_OFF` or `DELIVERED`, and whose `production_window_id` differs from this order's; if any such order's window has a buffered interval intersecting this order's window's buffered interval, the routing is rejected with `ERR_HUB_SLOT_CONFLICT`."
    Design: Difficulty/resource_temporal_overlap/hub_buffered_closed_interval_conflict_with_no_reselection
    """
    setup = _hub_buffer_scenario(api)
    routed_p = fx.route_order(api, setup.order_p["id"])
    assert_order(routed_p, pickup_hub_id=setup.hub["id"], fulfillment_status="ROUTED")

    resp = api.route_order(setup.order_q["id"], ADMIN_HEADERS)

    validate_error(resp, ApiErrorId.HUB_SLOT_CONFLICT, 409)
    order_q = fx.read_order(api, setup.order_q["id"])
    assert_order(
        order_q,
        fulfillment_status="PLACED",
        payment_status="AUTHORIZED",
        pickup_hub_id=None,
        routing_mode=None,
    )
    assert_pickup_hub(fx.read_hub(api, setup.hub["id"]), assigned_order_count=1, status="OPEN")


def test_06_a_window_clear_of_the_buffer_still_acquires_a_slot_on_the_same_hub(api):
    """R's order routes onto the hub that refused Q, proving the refusal was geometric.

    PRD: "On success the order's `pickup_hub_id` is set to the selected hub, the hub's `assigned_order_count` is incremented by one, and the hub's `OPEN → CLOSED` edge is re-evaluated."
    Design: Difficulty/resource_temporal_overlap/hub_buffered_closed_interval_conflict_with_no_reselection
    """
    setup = _hub_buffer_scenario(api)
    routed_p = fx.route_order(api, setup.order_p["id"])
    validate_error(
        api.route_order(setup.order_q["id"], ADMIN_HEADERS), ApiErrorId.HUB_SLOT_CONFLICT, 409
    )

    routed_r = fx.route_order(api, setup.order_r["id"])

    assert_order(
        routed_r,
        pickup_hub_id=setup.hub["id"],
        fulfillment_status="ROUTED",
        routing_mode="BATCH_COOK_AND_CHILL",
        cold_chain_surcharge_cents=0,
    )
    assert_order(routed_p, routing_mode="BATCH_COOK_AND_CHILL", cold_chain_surcharge_cents=0)
    assert_pickup_hub(fx.read_hub(api, setup.hub["id"]), assigned_order_count=2, status="OPEN")


def test_07_a_collision_on_the_selected_hub_is_not_retried_against_a_lower_ranked_hub(api):
    """The route fails on the top-ranked hub even though the zone's other hub would pass.

    PRD: "The cold-chain buffer rule is applied to the selected hub alone: if it fails, the routing is rejected even when a lower-ranked candidate would have passed."
    Design: Difficulty/resource_temporal_overlap/hub_buffered_closed_interval_conflict_with_no_reselection
    """
    setup = _two_hub_scenario(api)
    routed_p = fx.route_order(api, setup.order_p["id"])
    assert_order(routed_p, pickup_hub_id=setup.wide_hub["id"], fulfillment_status="ROUTED")

    resp = api.route_order(setup.order_q["id"], ADMIN_HEADERS)

    validate_error(resp, ApiErrorId.HUB_SLOT_CONFLICT, 409)
    order_q = fx.read_order(api, setup.order_q["id"])
    assert_order(order_q, fulfillment_status="PLACED", pickup_hub_id=None, routing_mode=None)
    assert_pickup_hub(
        fx.read_hub(api, setup.wide_hub["id"]), assigned_order_count=1, status="OPEN"
    )
    assert_pickup_hub(
        fx.read_hub(api, setup.narrow_hub["id"]), assigned_order_count=0, status="OPEN"
    )
