"""Inventory drawdown, sold-out flips, restock revival, and cancellation compensation.

Difficulty (A): transitive_cascade (route -> deduct -> SOLD_OUT depth 3), boundary_precision
(sold-out threshold at exact grams), compensating_invariant (cancel restores grams; cancel
leaves ledger unchanged).
Corner (B): restock flips SOLD_OUT back to AVAILABLE.
"""
from test_helpers import validate_success, get_success_data
from test_helpers import fixtures as fx
from test_helpers import create_order_payload, make_stall_operator_headers

OPS = fx.OPS
GATEWAY = fx.GATEWAY


# ── Transitive cascade: route -> consume inventory -> SOLD_OUT (depth 3) ──────

def test_route_consumes_inventory_and_flips_item_sold_out(api):
    """PRD §3.5: "the platform deducts ingredient inventory FIFO (see §3.6), recording for
    the order exactly which lot gave up how many grams. Third, any menu item left short by
    that deduction flips from `AVAILABLE` to `SOLD_OUT`."
    PRD §3.6: "After routing consumes inventory, any item that can no longer make one unit
    and is currently `AVAILABLE` flips to `SOLD_OUT`"

    250g lot, 200g consumed -> 50g remaining (< 200g need) so Wings flips SOLD_OUT.

    Design: Difficulty/transitive_cascade/route_consume_soldout_depth3
    """
    stall, brand, _ = fx.create_active_listed_brand_on_stall(commission_rate_bps=1000)
    wings = fx.create_menu_item(brand["id"], name="Wings", price_cents=1000,
                                prep_minutes=8, required_equipment_type="FRYER")
    fx.add_recipe_component(brand["id"], wings["id"], ingredient_name="chicken", quantity_grams=200)
    fx.create_equipment(stall["id"], equipment_type="FRYER")
    lot = fx.create_ingredient_lot(stall["id"], ingredient_name="chicken", grams_received=250)
    fx.set_clock()
    order = get_success_data(api.create_order(
        create_order_payload(brand["id"], [{"menu_item_id": wings["id"], "qty": 1}],
                             external_ref="DD-7"), GATEWAY))
    routed = validate_success(api.route_order(order["id"], OPS), 200)
    assert routed["status"] == "ROUTED"
    lot_after = validate_success(api.get_ingredient_lot(lot["id"], OPS), 200)
    assert lot_after["grams_remaining"] == 50
    item_after = validate_success(api.get_menu_item(wings["id"], OPS), 200)
    assert item_after["availability"] == "SOLD_OUT"


def test_route_three_hop_cascade_end_to_end(api):
    """PRD §3.6: "from each lot it takes the smaller of that lot's `grams_remaining` and
    the grams still outstanding, subtracts that take from the lot's `grams_remaining`"
    PRD §3.6: "any item that can no longer make one unit and is currently `AVAILABLE` flips
    to `SOLD_OUT`."

    Route (hop A) deducts the lot (hop B) leaving it short, which flips the item SOLD_OUT
    (hop C) — verified together on a 100g item with a 150g lot (50g left < 100g).

    Design: Difficulty/transitive_cascade/route_consume_soldout_depth3
    """
    stall, brand, _ = fx.create_active_listed_brand_on_stall(commission_rate_bps=1000)
    wings = fx.create_menu_item(brand["id"], name="Wings", price_cents=1000,
                                prep_minutes=8, required_equipment_type="FRYER")
    fx.add_recipe_component(brand["id"], wings["id"], ingredient_name="chicken", quantity_grams=100)
    fx.create_equipment(stall["id"], equipment_type="FRYER")
    lot = fx.create_ingredient_lot(stall["id"], ingredient_name="chicken", grams_received=150)
    fx.set_clock()
    order = get_success_data(api.create_order(
        create_order_payload(brand["id"], [{"menu_item_id": wings["id"], "qty": 1}],
                             external_ref="DD-CAS"), GATEWAY))
    routed = validate_success(api.route_order(order["id"], OPS), 200)
    assert routed["status"] == "ROUTED"
    lot_after = validate_success(api.get_ingredient_lot(lot["id"], OPS), 200)
    assert lot_after["grams_remaining"] == 50
    item_after = validate_success(api.get_menu_item(wings["id"], OPS), 200)
    assert item_after["availability"] == "SOLD_OUT"


# ── Boundary precision: sold-out threshold at exact grams ─────────────────────

def test_item_stays_available_at_exactly_quantity_grams(api):
    """PRD §3.6: "The boundary is inclusive: a sum exactly equal to `quantity_grams` still
    counts as makeable and the item stays `AVAILABLE`, whereas one gram short tips it to
    `SOLD_OUT`."

    400g lot, consume 200g -> exactly 200g remaining == quantity_grams -> stays AVAILABLE.

    Design: Difficulty/boundary_precision_check/soldout_threshold_at_exact_grams
    """
    stall, brand, _ = fx.create_active_listed_brand_on_stall(commission_rate_bps=1000)
    wings = fx.create_menu_item(brand["id"], name="Wings", price_cents=1000,
                                prep_minutes=8, required_equipment_type="FRYER")
    fx.add_recipe_component(brand["id"], wings["id"], ingredient_name="chicken", quantity_grams=200)
    fx.create_equipment(stall["id"], equipment_type="FRYER")
    lot = fx.create_ingredient_lot(stall["id"], ingredient_name="chicken", grams_received=400)
    fx.set_clock()
    order = get_success_data(api.create_order(
        create_order_payload(brand["id"], [{"menu_item_id": wings["id"], "qty": 1}],
                             external_ref="DD-11"), GATEWAY))
    routed = validate_success(api.route_order(order["id"], OPS), 200)
    assert routed["status"] == "ROUTED"
    lot_after = validate_success(api.get_ingredient_lot(lot["id"], OPS), 200)
    assert lot_after["grams_remaining"] == 200
    item_after = validate_success(api.get_menu_item(wings["id"], OPS), 200)
    assert item_after["availability"] == "AVAILABLE", "exactly quantity_grams stays AVAILABLE"


def test_item_flips_sold_out_one_gram_short(api):
    """PRD §3.6: "The boundary is inclusive: a sum exactly equal to `quantity_grams` still
    counts as makeable and the item stays `AVAILABLE`, whereas one gram short tips it to
    `SOLD_OUT`."

    399g lot, consume 200g -> 199g remaining (== quantity_grams - 1) -> flips SOLD_OUT.

    Design: Difficulty/boundary_precision_check/soldout_threshold_at_exact_grams
    """
    stall, brand, _ = fx.create_active_listed_brand_on_stall(commission_rate_bps=1000)
    wings = fx.create_menu_item(brand["id"], name="Wings", price_cents=1000,
                                prep_minutes=8, required_equipment_type="FRYER")
    fx.add_recipe_component(brand["id"], wings["id"], ingredient_name="chicken", quantity_grams=200)
    fx.create_equipment(stall["id"], equipment_type="FRYER")
    lot = fx.create_ingredient_lot(stall["id"], ingredient_name="chicken", grams_received=399)
    fx.set_clock()
    order = get_success_data(api.create_order(
        create_order_payload(brand["id"], [{"menu_item_id": wings["id"], "qty": 1}],
                             external_ref="DD-199"), GATEWAY))
    routed = validate_success(api.route_order(order["id"], OPS), 200)
    assert routed["status"] == "ROUTED"
    lot_after = validate_success(api.get_ingredient_lot(lot["id"], OPS), 200)
    assert lot_after["grams_remaining"] == 199
    item_after = validate_success(api.get_menu_item(wings["id"], OPS), 200)
    assert item_after["availability"] == "SOLD_OUT", "one gram short flips SOLD_OUT"


# ── Compensating invariant: cancel restores grams (conserved quantity) ────────

def test_cancel_restores_exact_grams_to_each_lot(api):
    """PRD §3.8: "Every consumption slice the order recorded is undone: each
    `IngredientLot` is credited back the exact grams this order took from it, restoring its
    `grams_remaining`."

    Two lots 300g + 300g (sum 600); route a 400g draw (lot1->0, lot2->200); cancel
    restores both lots to 300g each (sum back to 600).

    Design: Difficulty/compensating_invariant/cancel_restores_inventory_grams_conserved
    """
    stall, brand, _ = fx.create_active_listed_brand_on_stall(commission_rate_bps=1000)
    wings = fx.create_menu_item(brand["id"], name="Wings", price_cents=1000,
                                prep_minutes=8, required_equipment_type="FRYER")
    fx.add_recipe_component(brand["id"], wings["id"], ingredient_name="chicken", quantity_grams=200)
    fx.create_equipment(stall["id"], equipment_type="FRYER")
    lot_a = fx.create_ingredient_lot(stall["id"], ingredient_name="chicken",
                                     received_at="2026-01-01T00:00:00Z",
                                     unit_cost_cents_per_gram=8, grams_received=300)
    lot_b = fx.create_ingredient_lot(stall["id"], ingredient_name="chicken",
                                     received_at="2026-01-02T00:00:00Z",
                                     unit_cost_cents_per_gram=5, grams_received=300)
    fx.set_clock()
    order = get_success_data(api.create_order(
        create_order_payload(brand["id"], [{"menu_item_id": wings["id"], "qty": 2}],
                             external_ref="DD-17"), GATEWAY))
    routed = fx.route_order(order["id"])
    cancelled = validate_success(
        api.cancel_order(order["id"], {"expected_order_version": routed["version"]}, OPS), 200)
    assert cancelled["status"] == "CANCELLED"
    a_after = validate_success(api.get_ingredient_lot(lot_a["id"], OPS), 200)
    b_after = validate_success(api.get_ingredient_lot(lot_b["id"], OPS), 200)
    assert a_after["grams_remaining"] == 300
    assert b_after["grams_remaining"] == 300


def test_cancel_from_preparing_leaves_ledger_unchanged(api):
    """PRD §3.8: "Critically, cancellation never credits the brand ledger — ledger credit
    happens only at fulfillment. A cancelled order therefore leaves the brand's
    `ledger_balance_cents` exactly where it stood before the order ever existed"

    Route then start-prep then cancel from PREPARING; ledger stays at its pre-order 0.

    Design: Difficulty/compensating_invariant/cancel_leaves_brand_ledger_unchanged
    """
    s = fx.setup_routable_scenario(
        commission_rate_bps=1000,
        menu_item_overrides={"name": "Wings", "price_cents": 1000, "prep_minutes": 8,
                             "required_equipment_type": "FRYER"},
        recipe_overrides={"ingredient_name": "chicken", "quantity_grams": 100},
        lot_overrides={"ingredient_name": "chicken", "grams_received": 1000},
    )
    fx.route_order(s["order"]["id"])
    fx.start_prep(s["stall"]["id"], s["order"]["id"])
    preparing = validate_success(api.get_order(s["order"]["id"], OPS), 200)
    cancelled = validate_success(
        api.cancel_order(s["order"]["id"], {"expected_order_version": preparing["version"]}, OPS), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["food_cost_cents"] == 0
    brand_after = validate_success(api.get_brand(s["brand"]["id"], OPS), 200)
    assert brand_after["ledger_balance_cents"] == 0, "cancel must never credit the ledger"


# ── Corner: restock flips SOLD_OUT back to AVAILABLE ─────────────────────────

def test_restock_flips_sold_out_back_to_available(api):
    """PRD §3.6: "after inventory is restored — whether by a new lot being received or by an
    order being cancelled — any item that is currently `SOLD_OUT` and can once again make
    one unit of every component flips back to `AVAILABLE`."
    PRD §3.4: "any such item currently `SOLD_OUT` that now has enough grams on hand for one
    unit of every one of its recipe components flips back to `AVAILABLE`"

    Route consumes 200g of a 250g lot (50g left) -> SOLD_OUT; a new 200g lot revives it.

    Design: Corner/state_machines/restock_flips_soldout_back_available
    """
    stall, brand, _ = fx.create_active_listed_brand_on_stall(commission_rate_bps=1000)
    wings = fx.create_menu_item(brand["id"], name="Wings", price_cents=1000,
                                prep_minutes=8, required_equipment_type="FRYER")
    fx.add_recipe_component(brand["id"], wings["id"], ingredient_name="chicken", quantity_grams=200)
    fx.create_equipment(stall["id"], equipment_type="FRYER")
    fx.create_ingredient_lot(stall["id"], ingredient_name="chicken", grams_received=250)
    fx.set_clock()
    order = get_success_data(api.create_order(
        create_order_payload(brand["id"], [{"menu_item_id": wings["id"], "qty": 1}],
                             external_ref="DD-V"), GATEWAY))
    fx.route_order(order["id"])
    sold_out = validate_success(api.get_menu_item(wings["id"], OPS), 200)
    assert sold_out["availability"] == "SOLD_OUT"
    fx.create_ingredient_lot(stall["id"], ingredient_name="chicken",
                             received_at="2026-01-03T00:00:00Z", grams_received=200)
    revived = validate_success(api.get_menu_item(wings["id"], OPS), 200)
    assert revived["availability"] == "AVAILABLE"
