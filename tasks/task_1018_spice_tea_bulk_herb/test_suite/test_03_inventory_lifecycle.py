"""Inventory lot lifecycle: depletion/restore cycles, produce & cancel cascades,
grams conservation, FEFO allocation, and insufficient-stock rejection."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_confirmed_order, setup_packed_order, setup_blend_ready_to_produce,
    clock_set, new_product, new_lot, new_account, new_order, new_line, do_price, do_confirm,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
PROD = TEST_USERS["production_headers"]
SALES = TEST_USERS["sales_headers"]


# ---- non_linear_state_machine / inventory_lot_available_depleted_cycle ----

def test_lot_cycles_available_depleted_available(api):
    """PRD §2.9: "When a release — from cancelling a packed order — restores grams to a
    lot, a lot that was `DEPLETED` transitions `DEPLETED → AVAILABLE`, and if the product
    now has a lot with positive grams it cascades back to `IN_STOCK`."

    Design: Difficulty/non_linear_state_machine/inventory_lot_available_depleted_cycle
    """
    ctx = setup_packed_order(api, lot_grams=111, requested_grams=100,
                             gross_grams=121, tare_grams=10)  # draws all 111 -> DEPLETED
    depleted = validate_success(api.get_inventory_lot(ctx["lot"]["id"], ADMIN))
    assert depleted["status"] == "DEPLETED", depleted["status"]
    validate_success(api.cancel_order(ctx["order"]["id"], SALES))
    restored = validate_success(api.get_inventory_lot(ctx["lot"]["id"], ADMIN))
    assert restored["status"] == "AVAILABLE", restored["status"]


def test_lot_grams_restored_on_cancel_after_full_draw(api):
    """PRD §3.8: "for each line, the line's `net_grams` are restored to its
    `allocated_lot_id`, and any lot that was `DEPLETED` transitions `DEPLETED → AVAILABLE`,
    cascading its product's `stock_state` back toward `IN_STOCK`."

    Design: Difficulty/non_linear_state_machine/inventory_lot_available_depleted_cycle
    """
    ctx = setup_packed_order(api, lot_grams=111, requested_grams=100,
                             gross_grams=121, tare_grams=10)
    validate_success(api.cancel_order(ctx["order"]["id"], SALES))
    restored = validate_success(api.get_inventory_lot(ctx["lot"]["id"], ADMIN))
    assert restored["grams_on_hand"] == 111, restored["grams_on_hand"]


# ---- transitive_cascade / batch_produce_depletes_lot_then_stock_state ----

def test_produce_depletes_drawn_component_lot(api):
    """PRD §3.3: "Each lot drawn down has its `grams_on_hand` decremented; a lot that
    reaches zero transitions `AVAILABLE → DEPLETED`, and a depleted lot that was its
    product's last positive lot cascades that product to `OUT_OF_STOCK`."

    Design: Difficulty/transitive_cascade/batch_produce_depletes_lot_then_stock_state
    """
    ctx = setup_blend_ready_to_produce(api, bt_ratio=7000, sa_ratio=3000,
                                       bt_lot_grams=200, sa_lot_grams=30,
                                       target_output_grams=100)
    validate_success(api.produce_batch(ctx["batch"]["id"], PROD))
    # ceil(100 * 3000/10000) = 30 drawn from the 30g Sweet Almond lot -> 0, DEPLETED.
    sa_lot = validate_success(api.get_inventory_lot(ctx["sa_lot"]["id"], ADMIN))
    assert sa_lot["grams_on_hand"] == 0, sa_lot["grams_on_hand"]
    assert sa_lot["status"] == "DEPLETED", sa_lot["status"]


def test_produce_cascades_stock_state_out_of_stock(api):
    """PRD §3.3: "For each component of the blend, the quantity to draw is the target
    output multiplied by that component's share in basis points, divided by ten thousand,
    then rounded **up** to the next whole gram."
    PRD §2.9: "if it was the product's last lot carrying positive grams, the product
    cascades to `OUT_OF_STOCK`."

    Design: Difficulty/transitive_cascade/batch_produce_depletes_lot_then_stock_state
    """
    ctx = setup_blend_ready_to_produce(api, bt_ratio=7000, sa_ratio=3000,
                                       bt_lot_grams=200, sa_lot_grams=30,
                                       target_output_grams=100)
    validate_success(api.produce_batch(ctx["batch"]["id"], PROD))
    sa = validate_success(api.get_product(ctx["sa"]["id"], ADMIN))
    assert sa["stock_state"] == "OUT_OF_STOCK", sa["stock_state"]
    # Black Tea drew ceil(100*7000/10000)=70 from 200 -> 130 remaining; still IN_STOCK.
    bt_lot = validate_success(api.get_inventory_lot(ctx["bt_lot"]["id"], ADMIN))
    assert bt_lot["grams_on_hand"] == 130, bt_lot["grams_on_hand"]
    bt = validate_success(api.get_product(ctx["bt"]["id"], ADMIN))
    assert bt["stock_state"] == "IN_STOCK", bt["stock_state"]


# ---- transitive_cascade / order_cancel_restores_lot_then_stock_state ----

def test_cancel_packed_restores_depleted_lot(api):
    """PRD §3.8: "for each line, the line's `net_grams` are restored to its
    `allocated_lot_id`, and any lot that was `DEPLETED` transitions `DEPLETED → AVAILABLE`."

    Design: Difficulty/transitive_cascade/order_cancel_restores_lot_then_stock_state
    """
    ctx = setup_packed_order(api, lot_grams=111, requested_grams=100,
                             gross_grams=121, tare_grams=10)
    validate_success(api.cancel_order(ctx["order"]["id"], SALES))
    lot = validate_success(api.get_inventory_lot(ctx["lot"]["id"], ADMIN))
    assert lot["grams_on_hand"] == 111 and lot["status"] == "AVAILABLE", lot


def test_cancel_packed_cascades_product_back_in_stock(api):
    """PRD §2.9: "if the product now has a lot with positive grams it cascades back to
    `IN_STOCK`."

    Design: Difficulty/transitive_cascade/order_cancel_restores_lot_then_stock_state
    """
    ctx = setup_packed_order(api, lot_grams=111, requested_grams=100,
                             gross_grams=121, tare_grams=10)
    out = validate_success(api.get_product(ctx["product"]["id"], ADMIN))
    assert out["stock_state"] == "OUT_OF_STOCK", out["stock_state"]
    validate_success(api.cancel_order(ctx["order"]["id"], SALES))
    back = validate_success(api.get_product(ctx["product"]["id"], ADMIN))
    assert back["stock_state"] == "IN_STOCK", back["stock_state"]


# ---- compensating_invariant / grams_conservation_pack_cancel ----

def test_grams_conserved_after_pack_and_cancel(api):
    """PRD §3.8: "it also releases the inventory: for each line, the line's `net_grams`
    are restored to its `allocated_lot_id`."

    Design: Difficulty/compensating_invariant/grams_conservation_pack_cancel
    """
    ctx = setup_packed_order(api, lot_grams=500, requested_grams=100,
                             gross_grams=121, tare_grams=10)  # draws net 111
    validate_success(api.cancel_order(ctx["order"]["id"], SALES))
    lot = validate_success(api.get_inventory_lot(ctx["lot"]["id"], ADMIN))
    assert lot["grams_on_hand"] == 500, lot["grams_on_hand"]


def test_grams_decremented_by_net_then_fully_restored(api):
    """PRD §3.7: "that lot's `grams_on_hand` is decremented by the line's net grams."
    PRD §3.8: "the line's `net_grams` are restored to its `allocated_lot_id`."

    Design: Difficulty/compensating_invariant/grams_conservation_pack_cancel
    """
    ctx = setup_confirmed_order(api, lot_grams=500, requested_grams=100)
    measurements = [{"line_id": ctx["line"]["id"], "gross_grams": 121, "tare_grams": 10}]
    validate_success(api.pack_order(ctx["order"]["id"], {"line_measurements": measurements}, PROD))
    packed = validate_success(api.get_inventory_lot(ctx["lot"]["id"], ADMIN))
    assert packed["grams_on_hand"] == 389, packed["grams_on_hand"]  # 500 - 111
    validate_success(api.cancel_order(ctx["order"]["id"], SALES))
    restored = validate_success(api.get_inventory_lot(ctx["lot"]["id"], ADMIN))
    assert restored["grams_on_hand"] == 500, restored["grams_on_hand"]


# ---- Corner / calculations / fefo_selects_earliest_best_by ----

def test_fefo_allocates_from_earliest_best_by_lot(api):
    """PRD §3.7: "Among the candidates the system selects the one with the earliest
    `best_by`, breaking ties by earliest `received_at` and then by earliest `created_at`;
    the random `id` is never used as a tiebreaker."

    Design: Corner/calculations/corner_fefo_selects_earliest_best_by
    """
    clock_set(api, "2026-06-15T00:00:00Z")
    cham = new_product(api, name="Chamomile", category="HERB", unit_price_cents_per_gram=2.5)
    lot_a = new_lot(api, cham["id"], lot_code="LATE", grams_received=500,
                    best_by="2026-09-01T00:00:00Z")
    lot_b = new_lot(api, cham["id"], lot_code="EARLY", grams_received=500,
                    best_by="2026-08-01T00:00:00Z")
    account = new_account(api, credit_limit_cents=100000)
    order = new_order(api, account["id"], allergen_ack=True)
    line = new_line(api, order["id"], cham["id"], 100)
    do_price(api, order["id"])
    do_confirm(api, order["id"], account["id"])
    measurements = [{"line_id": line["id"], "gross_grams": 108, "tare_grams": 8}]  # net 100
    validate_success(api.pack_order(order["id"], {"line_measurements": measurements}, PROD))
    packed_line = validate_success(api.get_order_line(line["id"], ADMIN))
    assert packed_line["allocated_lot_id"] == lot_b["id"], "must draw from earliest best_by"
    assert validate_success(api.get_inventory_lot(lot_b["id"], ADMIN))["grams_on_hand"] == 400
    assert validate_success(api.get_inventory_lot(lot_a["id"], ADMIN))["grams_on_hand"] == 500


# ---- Corner / validations / pack_insufficient_stock ----

def test_pack_with_no_available_lot_rejected(api):
    """PRD §3.7: "If no single candidate lot can cover the line, packing is rejected with
    `ERR_INSUFFICIENT_STOCK`."

    Design: Corner/validations/corner_pack_insufficient_stock
    """
    ctx = setup_confirmed_order(api, with_lot=False, requested_grams=50, allergen_ack=True)
    measurements = [{"line_id": ctx["line"]["id"], "gross_grams": 58, "tare_grams": 8}]
    resp = api.pack_order(ctx["order"]["id"], {"line_measurements": measurements}, PROD)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK.value)
