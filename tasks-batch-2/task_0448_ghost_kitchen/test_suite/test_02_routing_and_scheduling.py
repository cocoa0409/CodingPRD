"""Order routing: eligibility filter, deterministic stall selection, prep-window math,
and the cross-entity preconditions that block routing.

Difficulty (A): combinatorial_formula (non-linear 4-input eligibility; prep-window sum
without intermediate rounding), cross_entity_state_dependency (route requires stall OPEN).
Corner (B): order initial state, no-eligible-stall, insufficient-inventory.
"""
from test_helpers import validate_success, validate_error, get_success_data
from test_helpers import fixtures as fx
from test_helpers import create_order_payload

OPS = fx.OPS
GATEWAY = fx.GATEWAY


# ── Combinatorial eligibility: non-linear 4-input AND + priority ranking ──────

def test_routing_excludes_stall_failing_one_of_four_eligibility_inputs(api):
    """PRD §3.5: "A stall is **routing-eligible** for an order only when all of the
    following hold: an `ACTIVE` `KitchenLease` exists binding the order's brand to that
    stall; the stall's `status` is `OPEN`; for every distinct `required_equipment_type`
    among the order's line items, the stall owns at least one `AVAILABLE` `Equipment` unit
    of that type that can host the contiguous prep window for that type without violating
    the overlap and turnaround rules of §2.8; and the stall holds enough FIFO inventory to
    satisfy every recipe component of every line item."
    PRD §3.5: "the candidate whose binding lease has the lowest `priority_rank` wins"

    Stall SA (rank 1) fails ONLY inventory (100g < 200g need) -> excluded despite passing
    the other 3 inputs; stall SB (rank 2) passes all 4 and wins.

    Design: Difficulty/combinatorial_formula/routing_min_max_eligibility_nonlinear
    """
    sa = fx.create_stall(name="SA")
    sb = fx.create_stall(name="SB")
    brand = fx.create_brand(name="B3", commission_rate_bps=1000)
    la = fx.create_lease(sa["id"], brand["id"], priority_rank=1)
    lb = fx.create_lease(sb["id"], brand["id"], priority_rank=2)
    fx.activate_lease(sa["id"], la["id"])
    fx.activate_lease(sb["id"], lb["id"])
    fx.list_brand(brand["id"])
    wings = fx.create_menu_item(brand["id"], name="Wings", price_cents=1000,
                                prep_minutes=8, required_equipment_type="FRYER")
    fx.add_recipe_component(brand["id"], wings["id"], ingredient_name="chicken", quantity_grams=200)
    fx.create_equipment(sa["id"], equipment_type="FRYER")
    fx.create_equipment(sb["id"], equipment_type="FRYER")
    fx.create_ingredient_lot(sa["id"], ingredient_name="chicken", grams_received=100)
    fx.create_ingredient_lot(sb["id"], ingredient_name="chicken", grams_received=500)
    fx.set_clock()
    order = get_success_data(api.create_order(
        create_order_payload(brand["id"], [{"menu_item_id": wings["id"], "qty": 1}],
                             external_ref="DD-3"), GATEWAY))
    routed = validate_success(api.route_order(order["id"], OPS), 200)
    assert routed["routed_stall_id"] == sb["id"], "must route to the only fully-eligible stall"
    assert routed["routed_stall_id"] != sa["id"]
    assert routed["status"] == "ROUTED"


def test_routing_picks_lower_priority_rank_among_eligible(api):
    """PRD §3.5: "Among the eligible stalls, the platform picks deterministically: the
    candidate whose binding lease has the lowest `priority_rank` wins, and if two leases
    tie on rank, the lease created earlier (by `created_at` ascending) wins — never by `id`."

    Two fully-eligible stalls; the rank-1 lease's stall wins over the rank-2 lease's stall.

    Design: Difficulty/combinatorial_formula/routing_min_max_eligibility_nonlinear
    """
    s_low = fx.create_stall(name="LOW")
    s_high = fx.create_stall(name="HIGH")
    brand = fx.create_brand(name="BR", commission_rate_bps=1000)
    # High-rank lease created first; low-rank lease created second. Rank must beat order.
    l_high = fx.create_lease(s_high["id"], brand["id"], priority_rank=5)
    l_low = fx.create_lease(s_low["id"], brand["id"], priority_rank=1)
    fx.activate_lease(s_high["id"], l_high["id"])
    fx.activate_lease(s_low["id"], l_low["id"])
    fx.list_brand(brand["id"])
    wings = fx.create_menu_item(brand["id"], name="Wings", price_cents=1000,
                                prep_minutes=8, required_equipment_type="FRYER")
    fx.add_recipe_component(brand["id"], wings["id"], ingredient_name="chicken", quantity_grams=100)
    for sid in (s_low["id"], s_high["id"]):
        fx.create_equipment(sid, equipment_type="FRYER")
        fx.create_ingredient_lot(sid, ingredient_name="chicken", grams_received=1000)
    fx.set_clock()
    order = get_success_data(api.create_order(
        create_order_payload(brand["id"], [{"menu_item_id": wings["id"], "qty": 1}],
                             external_ref="DD-RANK"), GATEWAY))
    routed = validate_success(api.route_order(order["id"], OPS), 200)
    assert routed["routed_stall_id"] == s_low["id"], "lowest priority_rank must win"


# ── Combinatorial prep-window: start at clock minute + summed occupancy ───────

def test_prep_window_end_is_start_plus_summed_occupancy(api):
    """PRD §3.5: "the platform reserves a single contiguous half-open window on one
    `AVAILABLE` unit of that type at the chosen stall: the window starts at the current
    clock minute and runs for the total occupancy of that type, where total occupancy is
    the sum, over the line items whose menu item's `required_equipment_type` equals that
    type, of the menu item's `prep_minutes` multiplied by that line item's `qty`."
    PRD §2.7: "The "current clock minute" used throughout equipment scheduling is the
    floor of the clock's epoch-second value divided by 60"

    Clock 2026-01-05T00:00:00Z -> start_minute 29459520; occupancy 8*2 + 5*1 = 21 ->
    end_minute 29459541.

    Design: Difficulty/combinatorial_formula/prep_window_interval_then_summed_no_intermediate_rounding
    """
    stall, brand, _ = fx.create_active_listed_brand_on_stall(commission_rate_bps=1000)
    wings = fx.create_menu_item(brand["id"], name="Wings", price_cents=1000,
                                prep_minutes=8, required_equipment_type="FRYER")
    fx.add_recipe_component(brand["id"], wings["id"], ingredient_name="chicken", quantity_grams=100)
    fries = fx.create_menu_item(brand["id"], name="Fries", price_cents=500,
                                prep_minutes=5, required_equipment_type="FRYER")
    fx.add_recipe_component(brand["id"], fries["id"], ingredient_name="potato", quantity_grams=100)
    fx.create_equipment(stall["id"], equipment_type="FRYER")
    fx.create_ingredient_lot(stall["id"], ingredient_name="chicken", grams_received=1000)
    fx.create_ingredient_lot(stall["id"], ingredient_name="potato",
                             unit_cost_cents_per_gram=2, grams_received=1000)
    fx.set_clock()
    order = get_success_data(api.create_order(
        create_order_payload(brand["id"],
                             [{"menu_item_id": wings["id"], "qty": 2},
                              {"menu_item_id": fries["id"], "qty": 1}],
                             external_ref="DD-4"), GATEWAY))
    routed = validate_success(api.route_order(order["id"], OPS), 200)
    booking = validate_success(api.get_booking(routed["booking_id"], OPS), 200)
    assert booking["start_minute"] == 29459520
    assert booking["end_minute"] == 29459541
    assert booking["status"] == "HELD"


def test_prep_window_start_equals_current_clock_minute(api):
    """PRD §3.5: "the window starts at the current clock minute and runs for the total
    occupancy of that type"
    PRD §2.7: "The "current clock minute" used throughout equipment scheduling is the
    floor of the clock's epoch-second value divided by 60"

    Single item prep 8 minutes, qty 1, at clock 2026-01-05T00:00:00Z -> [29459520, 29459528).

    Design: Difficulty/combinatorial_formula/prep_window_interval_then_summed_no_intermediate_rounding
    """
    s = fx.setup_routable_scenario(
        menu_item_overrides={"name": "Wings", "price_cents": 1000, "prep_minutes": 8,
                             "required_equipment_type": "FRYER"},
        recipe_overrides={"ingredient_name": "chicken", "quantity_grams": 100},
        lot_overrides={"ingredient_name": "chicken", "grams_received": 1000},
    )
    routed = validate_success(api.route_order(s["order"]["id"], OPS), 200)
    booking = validate_success(api.get_booking(routed["booking_id"], OPS), 200)
    assert booking["start_minute"] == 29459520
    assert booking["end_minute"] == 29459528


# ── Cross-entity state dependency: route requires stall OPEN ──────────────────

def test_route_blocked_when_only_stall_is_closed(api):
    """PRD §3.5: "There must be at least one routing-eligible stall (defined below); if
    none qualifies, routing fails with `ERR_NO_ELIGIBLE_STALL` and the order is left
    untouched."
    PRD §3.5: "A stall is **routing-eligible** for an order only when all of the following
    hold: ... the stall's `status` is `OPEN`"

    The only leased stall is manually CLOSED, so no stall is eligible.

    Design: Difficulty/cross_entity_state_dependency/route_requires_stall_open
    """
    stall, brand, _ = fx.create_active_listed_brand_on_stall(commission_rate_bps=1000)
    wings = fx.create_menu_item(brand["id"], name="Wings", price_cents=1000,
                                prep_minutes=8, required_equipment_type="FRYER")
    fx.add_recipe_component(brand["id"], wings["id"], ingredient_name="chicken", quantity_grams=100)
    fx.create_equipment(stall["id"], equipment_type="FRYER")
    fx.create_ingredient_lot(stall["id"], ingredient_name="chicken", grams_received=1000)
    get_success_data(api.close_stall(stall["id"], fx.make_stall_operator_headers(stall["id"])))
    fx.set_clock()
    order = get_success_data(api.create_order(
        create_order_payload(brand["id"], [{"menu_item_id": wings["id"], "qty": 1}],
                             external_ref="DD-13"), GATEWAY))
    res = api.route_order(order["id"], OPS)
    validate_error(res, "ERR_NO_ELIGIBLE_STALL", expected_status=409)
    after = validate_success(api.get_order(order["id"], OPS), 200)
    assert after["status"] == "INGESTED", "blocked route leaves the order untouched"


def test_route_succeeds_when_stall_open(api):
    """PRD §3.5: "A stall is **routing-eligible** for an order only when all of the
    following hold: ... the stall's `status` is `OPEN`"

    Positive companion: a freshly created OPEN stall (all other inputs satisfied) is
    eligible and the order routes to it.

    Design: Difficulty/cross_entity_state_dependency/route_requires_stall_open
    """
    s = fx.setup_routable_scenario(
        menu_item_overrides={"name": "Wings", "price_cents": 1000, "prep_minutes": 8,
                             "required_equipment_type": "FRYER"},
        recipe_overrides={"ingredient_name": "chicken", "quantity_grams": 100},
        lot_overrides={"ingredient_name": "chicken", "grams_received": 1000},
    )
    routed = validate_success(api.route_order(s["order"]["id"], OPS), 200)
    assert routed["status"] == "ROUTED"
    assert routed["routed_stall_id"] == s["stall"]["id"]


# ── Corner: order initial state ──────────────────────────────────────────────

def test_ingested_order_initial_state(api):
    """PRD §3.5: "A newly ingested order is `INGESTED` and immediately snapshots its
    `gross_revenue_cents`" ... "At ingestion the order's `routed_stall_id`, `booking_id`,
    `commission_cents`, and `food_cost_cents` are all still unset or zero"

    2x@300 soda -> gross 600; routed_stall_id and booking_id null.

    Design: Corner/state_machines/order_initial_state_ingested
    """
    brand = fx.create_brand(commission_rate_bps=1000)
    soda = fx.create_menu_item(brand["id"], name="Soda", price_cents=300, prep_minutes=1,
                               required_equipment_type="PREP_STATION")
    order = validate_success(api.create_order(
        create_order_payload(brand["id"], [{"menu_item_id": soda["id"], "qty": 2}],
                             external_ref="DD-I"), GATEWAY), 201)
    assert order["status"] == "INGESTED"
    assert order["routed_stall_id"] is None
    assert order["gross_revenue_cents"] == 600


# ── Corner: no eligible stall (missing equipment type) ───────────────────────

def test_route_no_eligible_stall_when_required_equipment_missing(api):
    """PRD §3.5: "for every distinct `required_equipment_type` among the order's line
    items, the stall owns at least one `AVAILABLE` `Equipment` unit of that type"
    PRD §3.5: "if none qualifies, routing fails with `ERR_NO_ELIGIBLE_STALL`"

    The leased OPEN stall has only an OVEN; the FRYER item cannot be cooked.

    Design: Corner/validations/no_eligible_stall_when_no_equipment
    """
    stall, brand, _ = fx.create_active_listed_brand_on_stall(commission_rate_bps=1000)
    wings = fx.create_menu_item(brand["id"], name="Wings", price_cents=1000,
                                prep_minutes=8, required_equipment_type="FRYER")
    fx.add_recipe_component(brand["id"], wings["id"], ingredient_name="chicken", quantity_grams=100)
    fx.create_equipment(stall["id"], equipment_type="OVEN")
    fx.create_ingredient_lot(stall["id"], ingredient_name="chicken", grams_received=1000)
    fx.set_clock()
    order = get_success_data(api.create_order(
        create_order_payload(brand["id"], [{"menu_item_id": wings["id"], "qty": 1}],
                             external_ref="DD-M"), GATEWAY))
    res = api.route_order(order["id"], OPS)
    validate_error(res, "ERR_NO_ELIGIBLE_STALL", expected_status=409)


# ── Corner: insufficient inventory (no partial deduction) ────────────────────

def test_route_insufficient_inventory_deducts_nothing(api):
    """PRD §3.5: "Every recipe component of every line item must be fully satisfiable from
    FIFO inventory at the chosen stall; if any component cannot be covered, routing fails
    with `ERR_INSUFFICIENT_INVENTORY` and no grams are deducted."

    Wings need 200g chicken but only 50g is on hand; routing fails and the lot keeps 50g.

    Design: Corner/validations/insufficient_inventory_when_brand_listed
    """
    stall, brand, _ = fx.create_active_listed_brand_on_stall(commission_rate_bps=1000)
    wings = fx.create_menu_item(brand["id"], name="Wings", price_cents=1000,
                                prep_minutes=8, required_equipment_type="FRYER")
    fx.add_recipe_component(brand["id"], wings["id"], ingredient_name="chicken", quantity_grams=200)
    fx.create_equipment(stall["id"], equipment_type="FRYER")
    lot = fx.create_ingredient_lot(stall["id"], ingredient_name="chicken", grams_received=50)
    fx.set_clock()
    order = get_success_data(api.create_order(
        create_order_payload(brand["id"], [{"menu_item_id": wings["id"], "qty": 1}],
                             external_ref="DD-N"), GATEWAY))
    res = api.route_order(order["id"], OPS)
    validate_error(res, "ERR_INSUFFICIENT_INVENTORY", expected_status=409)
    lot_after = validate_success(api.get_ingredient_lot(lot["id"], OPS), 200)
    assert lot_after["grams_remaining"] == 50, "no partial deduction on failed routing"
    order_after = validate_success(api.get_order(order["id"], OPS), 200)
    assert order_after["status"] == "INGESTED"
