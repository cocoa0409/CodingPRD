"""Money: gross revenue snapshot, forward-looking commission, chronological FIFO food
cost, ledger settlement, and brand-performance read.

Difficulty (A): dual_variant_calc (food cost FIFO vs cheapest lot; commission forward-
looking vs food cost chronological).
Corner (B): gross-revenue snapshot, commission round-half-up boundary, fulfill side
effects, brand performance read, immediate consistency of the route response.
"""
from test_helpers import validate_success, get_success_data
from test_helpers import fixtures as fx
from test_helpers import (
    create_order_payload,
    make_stall_operator_headers,
    make_brand_owner_headers,
)

OPS = fx.OPS
GATEWAY = fx.GATEWAY


# ── Dual-variant calculation: chronological FIFO food cost ────────────────────

def test_food_cost_uses_chronological_fifo_lots_not_cheapest(api):
    """PRD §3.7: "It is computed not against current inventory but against the exact
    consumption slices the order recorded at routing: for each recorded slice, the
    grams taken from that lot are multiplied by *that lot's* `unit_cost_cents_per_gram`,
    and these products are summed to give `food_cost_cents`."
    PRD §3.6: "orders them by `received_at` ascending with `created_at` ascending as the
    tie-break, and draws from each lot in turn"

    400g chicken drawn FIFO = lot1 300g@8c + lot2 100g@3c = 2400 + 300 = 2700,
    which differs from a cheapest-lot estimate of 400g@3c = 1200.

    Design: Difficulty/dual_variant_calc/food_cost_fifo_chronological_vs_cheapest_lot
    """
    stall, brand, _ = fx.create_active_listed_brand_on_stall(commission_rate_bps=1500)
    item = fx.create_menu_item(brand["id"], name="Wings", price_cents=1000,
                               prep_minutes=8, required_equipment_type="FRYER")
    fx.add_recipe_component(brand["id"], item["id"], ingredient_name="chicken", quantity_grams=200)
    fx.create_equipment(stall["id"], equipment_type="FRYER", turnaround_buffer_minutes=0)
    fx.create_ingredient_lot(stall["id"], ingredient_name="chicken",
                             received_at="2026-01-01T00:00:00Z", unit_cost_cents_per_gram=8,
                             grams_received=300)
    fx.create_ingredient_lot(stall["id"], ingredient_name="chicken",
                             received_at="2026-01-02T00:00:00Z", unit_cost_cents_per_gram=3,
                             grams_received=300)
    fx.set_clock()
    order = get_success_data(api.create_order(
        create_order_payload(brand["id"], [{"menu_item_id": item["id"], "qty": 2}],
                             external_ref="DD-1"), GATEWAY))
    fx.route_order(order["id"])
    fx.start_prep(stall["id"], order["id"])
    fulfilled = validate_success(
        api.fulfill_order(order["id"], make_stall_operator_headers(stall["id"])), 200)
    assert fulfilled["food_cost_cents"] == 2700, \
        f"FIFO food cost must be 2700, got {fulfilled['food_cost_cents']}"
    assert fulfilled["food_cost_cents"] != 1200, "must not use cheapest-lot estimate"
    assert fulfilled["status"] == "FULFILLED"


def test_food_cost_chronological_actual_lot_costs(api):
    """PRD §3.7: "Because the slices reflect the actual FIFO draw at routing, this figure
    can differ from any "cheapest lot now" estimate — it is the real cost of the specific
    lots that were drawn. There is no rounding, since grams and per-gram cents are integers."

    300g chicken@3 + 100g chicken@5 across a 400g draw of two lots received in order =
    900 + 500 = 1400 for the wings; potato 150g@2 = 300. Food cost = 1700.

    Design: Difficulty/dual_variant_calc/food_cost_fifo_chronological_vs_cheapest_lot
    """
    stall, brand, _ = fx.create_active_listed_brand_on_stall(commission_rate_bps=1500)
    wings = fx.create_menu_item(brand["id"], name="Wings", price_cents=1099,
                                prep_minutes=8, required_equipment_type="FRYER")
    fx.add_recipe_component(brand["id"], wings["id"], ingredient_name="chicken", quantity_grams=200)
    fries = fx.create_menu_item(brand["id"], name="Fries", price_cents=499,
                                prep_minutes=5, required_equipment_type="FRYER")
    fx.add_recipe_component(brand["id"], fries["id"], ingredient_name="potato", quantity_grams=150)
    fx.create_equipment(stall["id"], equipment_type="FRYER", turnaround_buffer_minutes=0)
    fx.create_ingredient_lot(stall["id"], ingredient_name="chicken",
                             received_at="2026-01-01T00:00:00Z", unit_cost_cents_per_gram=3,
                             grams_received=300)
    fx.create_ingredient_lot(stall["id"], ingredient_name="chicken",
                             received_at="2026-01-02T00:00:00Z", unit_cost_cents_per_gram=5,
                             grams_received=300)
    fx.create_ingredient_lot(stall["id"], ingredient_name="potato",
                             received_at="2026-01-01T00:00:00Z", unit_cost_cents_per_gram=2,
                             grams_received=500)
    fx.set_clock()
    order = get_success_data(api.create_order(
        create_order_payload(brand["id"],
                             [{"menu_item_id": wings["id"], "qty": 2},
                              {"menu_item_id": fries["id"], "qty": 1}],
                             aggregator="UBER_EATS", external_ref="UE-1"), GATEWAY))
    fx.route_order(order["id"])
    fx.start_prep(stall["id"], order["id"])
    fulfilled = validate_success(
        api.fulfill_order(order["id"], make_stall_operator_headers(stall["id"])), 200)
    # chicken: 300g@3 + 100g@5 = 900+500 = 1400 ; potato: 150g@2 = 300 ; total 1700
    assert fulfilled["food_cost_cents"] == 1700, \
        f"chronological food cost must be 1700, got {fulfilled['food_cost_cents']}"


# ── Dual-variant: forward-looking commission vs chronological food cost ───────

def test_commission_forward_looking_at_routing_food_cost_zero(api):
    """PRD §3.7: "The first pass, **commission**, is forward-looking and is computed at
    routing time. It is the order's snapshotted `gross_revenue_cents` multiplied by the
    brand's `commission_rate_bps` as read at the moment of routing, divided by 10000,
    rounded half up to a whole number of cents"
    PRD §3.5: "food cost in particular stays 0 until the order is fulfilled."

    gross = 2*1099 + 499 = 2697 ; commission @1500bps = round_half_up(2697*1500/10000)
    = round_half_up(404.55) = 405 ; food_cost still 0 at ROUTED.

    Design: Difficulty/dual_variant_calc/commission_forward_looking_on_brand_vs_food_cost_chronological_on_order
    """
    stall, brand, _ = fx.create_active_listed_brand_on_stall(commission_rate_bps=1500)
    wings = fx.create_menu_item(brand["id"], name="Wings", price_cents=1099,
                                prep_minutes=8, required_equipment_type="FRYER")
    fx.add_recipe_component(brand["id"], wings["id"], ingredient_name="chicken", quantity_grams=200)
    fries = fx.create_menu_item(brand["id"], name="Fries", price_cents=499,
                                prep_minutes=5, required_equipment_type="FRYER")
    fx.add_recipe_component(brand["id"], fries["id"], ingredient_name="potato", quantity_grams=150)
    fx.create_equipment(stall["id"], equipment_type="FRYER", turnaround_buffer_minutes=0)
    fx.create_ingredient_lot(stall["id"], ingredient_name="chicken",
                             received_at="2026-01-01T00:00:00Z", unit_cost_cents_per_gram=3,
                             grams_received=300)
    fx.create_ingredient_lot(stall["id"], ingredient_name="chicken",
                             received_at="2026-01-02T00:00:00Z", unit_cost_cents_per_gram=5,
                             grams_received=300)
    fx.create_ingredient_lot(stall["id"], ingredient_name="potato",
                             received_at="2026-01-01T00:00:00Z", unit_cost_cents_per_gram=2,
                             grams_received=500)
    fx.set_clock()
    order = get_success_data(api.create_order(
        create_order_payload(brand["id"],
                             [{"menu_item_id": wings["id"], "qty": 2},
                              {"menu_item_id": fries["id"], "qty": 1}],
                             aggregator="UBER_EATS", external_ref="UE-1"), GATEWAY))
    routed = validate_success(api.route_order(order["id"], OPS), 200)
    assert routed["gross_revenue_cents"] == 2697
    assert routed["commission_cents"] == 405, \
        f"forward-looking commission must be 405, got {routed['commission_cents']}"
    assert routed["food_cost_cents"] == 0, "food cost is 0 until fulfilled"


def test_commission_authoritative_rate_not_recomputed(api):
    """PRD §3.7: "This routing-time figure is authoritative: commission is *not*
    recomputed at fulfillment, so whatever rate the brand carried when the order routed
    is the rate that ultimately settles, even if the brand's rate later changes."

    Commission computed at route on gross 1000 @1500bps = 150; it remains 150 after fulfill.

    Design: Difficulty/dual_variant_calc/commission_forward_looking_on_brand_vs_food_cost_chronological_on_order
    """
    s = fx.setup_routable_scenario(
        commission_rate_bps=1500,
        menu_item_overrides={"name": "Wings", "price_cents": 1000, "prep_minutes": 8,
                             "required_equipment_type": "FRYER"},
        recipe_overrides={"ingredient_name": "chicken", "quantity_grams": 100},
        lot_overrides={"ingredient_name": "chicken", "received_at": "2026-01-01T00:00:00Z",
                       "unit_cost_cents_per_gram": 4, "grams_received": 1000},
    )
    routed = validate_success(api.route_order(s["order"]["id"], OPS), 200)
    assert routed["commission_cents"] == 150
    fx.start_prep(s["stall"]["id"], s["order"]["id"])
    fulfilled = validate_success(
        api.fulfill_order(s["order"]["id"], make_stall_operator_headers(s["stall"]["id"])), 200)
    assert fulfilled["commission_cents"] == 150, "commission must not be recomputed at fulfill"


# ── Corner: gross revenue snapshot ───────────────────────────────────────────

def test_gross_revenue_snapshot_multi_line(api):
    """PRD §3.5: "A newly ingested order is `INGESTED` and immediately snapshots its
    `gross_revenue_cents`: the sum, over each line item, of the line item's menu item's
    `price_cents` multiplied by that line item's `qty`."

    3x@250 + 2x@400 = 750 + 800 = 1550.

    Design: Corner/calculations/gross_revenue_snapshot_multi_line
    """
    brand = fx.create_brand(commission_rate_bps=1000)
    a = fx.create_menu_item(brand["id"], name="A", price_cents=250, prep_minutes=1,
                            required_equipment_type="PREP_STATION")
    b = fx.create_menu_item(brand["id"], name="B", price_cents=400, prep_minutes=1,
                            required_equipment_type="PREP_STATION")
    order = validate_success(api.create_order(
        create_order_payload(brand["id"],
                             [{"menu_item_id": a["id"], "qty": 3},
                              {"menu_item_id": b["id"], "qty": 2}],
                             external_ref="DD-G"), GATEWAY), 201)
    assert order["gross_revenue_cents"] == 1550


# ── Corner: commission round-half-up boundary ────────────────────────────────

def test_commission_round_half_up_boundary(api):
    """PRD §2.9: "The forward-looking commission is the gross revenue in cents multiplied
    by the brand's commission rate in basis points, divided by 10000, with the result
    rounded half up to a whole number of cents. The rounding is applied once, to the
    single final product — never per line item."

    gross 2697 @2500bps = 2697*2500/10000 = 674.25 -> round half up = 674.

    Design: Corner/calculations/commission_round_half_up_boundary
    """
    stall, brand, _ = fx.create_active_listed_brand_on_stall(commission_rate_bps=2500)
    wings = fx.create_menu_item(brand["id"], name="Wings", price_cents=1099,
                                prep_minutes=8, required_equipment_type="FRYER")
    fx.add_recipe_component(brand["id"], wings["id"], ingredient_name="chicken", quantity_grams=100)
    fries = fx.create_menu_item(brand["id"], name="Fries", price_cents=499,
                                prep_minutes=5, required_equipment_type="FRYER")
    fx.add_recipe_component(brand["id"], fries["id"], ingredient_name="potato", quantity_grams=100)
    fx.create_equipment(stall["id"], equipment_type="FRYER", turnaround_buffer_minutes=0)
    fx.create_ingredient_lot(stall["id"], ingredient_name="chicken", grams_received=1000)
    fx.create_ingredient_lot(stall["id"], ingredient_name="potato",
                             unit_cost_cents_per_gram=2, grams_received=1000)
    fx.set_clock()
    order = get_success_data(api.create_order(
        create_order_payload(brand["id"],
                             [{"menu_item_id": wings["id"], "qty": 2},
                              {"menu_item_id": fries["id"], "qty": 1}],
                             aggregator="UBER_EATS", external_ref="UE-H"), GATEWAY))
    routed = validate_success(api.route_order(order["id"], OPS), 200)
    assert routed["gross_revenue_cents"] == 2697
    assert routed["commission_cents"] == 674


# ── Corner: fulfill side effects (food cost, ledger, booking release) ─────────

def test_fulfill_finalizes_food_cost_credits_ledger_releases_booking(api):
    """PRD §3.7: "The net payout for the order is its `gross_revenue_cents` minus its
    `commission_cents` minus its `food_cost_cents`, and that net amount is added to the
    owning brand's running `ledger_balance_cents`. Fulfillment then releases the equipment
    booking referenced by the order's `booking_id` (moving it `HELD → RELEASED` and freeing
    its window)"

    gross 1000, commission @1500bps = 150, food cost 100g@4 = 400 -> net payout 450.

    Design: Corner/state_machines/fulfill_releases_booking_and_credits_ledger
    """
    s = fx.setup_routable_scenario(
        commission_rate_bps=1500,
        menu_item_overrides={"name": "Wings", "price_cents": 1000, "prep_minutes": 8,
                             "required_equipment_type": "FRYER"},
        recipe_overrides={"ingredient_name": "chicken", "quantity_grams": 100},
        lot_overrides={"ingredient_name": "chicken", "unit_cost_cents_per_gram": 4,
                       "grams_received": 1000},
    )
    routed = fx.route_order(s["order"]["id"])
    booking_id = routed["booking_id"]
    fx.start_prep(s["stall"]["id"], s["order"]["id"])
    fulfilled = validate_success(
        api.fulfill_order(s["order"]["id"], make_stall_operator_headers(s["stall"]["id"])), 200)
    assert fulfilled["status"] == "FULFILLED"
    assert fulfilled["food_cost_cents"] == 400
    assert fulfilled["commission_cents"] == 150
    brand = validate_success(api.get_brand(s["brand"]["id"], OPS), 200)
    assert brand["ledger_balance_cents"] == 450
    booking = validate_success(api.get_booking(booking_id, OPS), 200)
    assert booking["status"] == "RELEASED"


# ── Corner: brand performance read ───────────────────────────────────────────

def test_brand_performance_reflects_ledger_after_fulfillment(api):
    """PRD §3.7: "A brand-performance summary read exposes this same balance alongside the
    brand's fulfilled-order count and gross, commission, and food-cost totals."
    PRD §3.7: "that net amount is added to the owning brand's running `ledger_balance_cents`."

    Single fulfilled order: gross 1000, commission 150, food cost 400 -> balance 450.

    Design: Corner/endpoints/brand_performance_computed_read
    """
    s = fx.setup_routable_scenario(
        commission_rate_bps=1500,
        menu_item_overrides={"name": "Wings", "price_cents": 1000, "prep_minutes": 8,
                             "required_equipment_type": "FRYER"},
        recipe_overrides={"ingredient_name": "chicken", "quantity_grams": 100},
        lot_overrides={"ingredient_name": "chicken", "unit_cost_cents_per_gram": 4,
                       "grams_received": 1000},
    )
    fx.route_order(s["order"]["id"])
    fx.start_prep(s["stall"]["id"], s["order"]["id"])
    fx.fulfill(s["stall"]["id"], s["order"]["id"])
    perf = validate_success(
        api.get_brand_performance(s["brand"]["id"], make_brand_owner_headers(s["brand"]["id"])), 200)
    assert perf["ledger_balance_cents"] == 450


# ── Corner: immediate consistency of route response ──────────────────────────

def test_route_response_shows_all_effects_immediately(api):
    """PRD §3.5: "The reserved booking is created `HELD` and the order's `booking_id` is
    set to it." ... "Routing also computes the order's forward-looking `commission_cents`
    from the snapshotted gross and the brand's current rate (see §3.7), sets `status` to
    `ROUTED`"
    PRD §3.5: "The winning stall is recorded as the order's `routed_stall_id`."

    The route response itself already carries routed_stall_id, booking_id, and commission.

    Design: Corner/consistency_model/route_all_effects_visible_same_response
    """
    s = fx.setup_routable_scenario(
        commission_rate_bps=1500,
        menu_item_overrides={"name": "Wings", "price_cents": 1000, "prep_minutes": 8,
                             "required_equipment_type": "FRYER"},
        recipe_overrides={"ingredient_name": "chicken", "quantity_grams": 100},
        lot_overrides={"ingredient_name": "chicken", "unit_cost_cents_per_gram": 4,
                       "grams_received": 1000},
    )
    routed = validate_success(api.route_order(s["order"]["id"], OPS), 200)
    assert routed["routed_stall_id"] == s["stall"]["id"]
    assert routed["commission_cents"] == 150
    assert routed["booking_id"] is not None
