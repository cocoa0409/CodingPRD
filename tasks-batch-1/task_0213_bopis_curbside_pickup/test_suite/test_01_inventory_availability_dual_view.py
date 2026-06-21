"""Inventory availability: the reserve-view vs pick-view distinction and conservation.

Difficulty queue A (dual_variant_calc, compensating_invariant) plus the corner
availability claims that build on the same reservation model.
"""
from test_helpers import (
    api_client as _ac,
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    assert_inventory_invariants,
    make_customer_headers, make_manager_headers,
    factories as f, fixtures as fx,
)


def test_reserve_lowers_available_but_not_on_hand_then_pick_reads_on_hand(api):
    """PRD §2.6: "Reserving increments `reserved` and recomputes `available`, but it
    leaves `on_hand` untouched — the physical units are not removed from the shelf
    until a picker actually pulls them. By contrast, the physical pick step reads
    `on_hand` directly: a pick of some quantity requires `on_hand` to be at least that
    picked quantity."

    Design: Difficulty/dual_variant_calc/availability_reserve_view_vs_pick_view
    """
    base = fx.seed_base_scenario(products=[{"price": 1000, "on_hand": 3}])
    inv = base["inventories"][0]
    customer = base["customer"]
    order, lines = fx.create_order_with_lines(
        customer["id"], base["store"]["id"], base["slot"]["id"], base["slot_version"],
        [(base["products"][0]["id"], 2)])
    fx.start_picking(order["id"])

    # reserve_view: available dropped to on_hand - reserved = 3 - 2 = 1; on_hand still 3
    inv_after_reserve = validate_success(api.get_store_inventory(inv["id"], make_manager_headers()))
    assert inv_after_reserve["available"] == 1, inv_after_reserve
    assert inv_after_reserve["on_hand"] == 3, inv_after_reserve
    assert inv_after_reserve["reserved"] == 2, inv_after_reserve

    # pick_view: pick reads on_hand (3 >= 2) and succeeds even though available is 1
    picked = validate_success(api.pick_line(lines[0]["id"], {"qty_picked": 2}, fx.make_picker_headers()))
    assert picked["line_status"] == "PICKED", picked

    inv_after_pick = validate_success(api.get_store_inventory(inv["id"], make_manager_headers()))
    assert inv_after_pick["on_hand"] == 1, inv_after_pick
    assert inv_after_pick["reserved"] == 0, inv_after_pick
    assert inv_after_pick["available"] == 1, inv_after_pick


def test_pick_succeeds_against_on_hand_when_available_below_picked_qty(api):
    """PRD §2.6: "Because the units being picked are already counted in `reserved`, the
    pick step does not re-check `available`."

    Design: Difficulty/dual_variant_calc/availability_reserve_view_vs_pick_view
    """
    # on_hand 3, reserve 2 -> available 1 (< the 2 being picked), yet pick must pass.
    base = fx.seed_base_scenario(products=[{"price": 1000, "on_hand": 3}])
    inv = base["inventories"][0]
    customer = base["customer"]
    order, lines = fx.create_order_with_lines(
        customer["id"], base["store"]["id"], base["slot"]["id"], base["slot_version"],
        [(base["products"][0]["id"], 2)])
    fx.start_picking(order["id"])

    before = validate_success(api.get_store_inventory(inv["id"], make_manager_headers()))
    assert before["available"] == 1 and before["on_hand"] == 3

    picked = validate_success(api.pick_line(lines[0]["id"], {"qty_picked": 2}, fx.make_picker_headers()))
    assert picked["line_status"] == "PICKED"
    assert picked["qty_picked"] == 2


def test_submit_then_cancel_conserves_inventory_units(api):
    """PRD §3.8: "Cancelling a `SUBMITTED` order moves it from `SUBMITTED` to
    `CANCELLED` and unwinds the submission: for each line the inventory's `reserved`
    falls by `qty_reserved`, `available` is recomputed, a `RELEASE` movement is
    appended, `qty_reserved` becomes zero, and the line becomes `NOT_FULFILLED`"
    PRD §2.6: "Reserving increments `reserved` and recomputes `available`, but it
    leaves `on_hand` untouched"

    Design: Difficulty/compensating_invariant/inventory_units_conserved_on_submit_then_cancel
    """
    base = fx.seed_base_scenario(products=[{"price": 1000, "on_hand": 5}])
    inv = base["inventories"][0]
    customer = base["customer"]

    order = fx.create_draft_order(customer["id"], base["store"]["id"])
    fx.add_line(order["id"], customer["id"], base["products"][0]["id"], 2)
    fx.submit_order(order["id"], customer["id"], base["slot"]["id"], base["slot_version"])

    mid = validate_success(api.get_store_inventory(inv["id"], make_manager_headers()))
    assert mid["reserved"] == 2 and mid["on_hand"] == 5 and mid["available"] == 3, mid

    validate_success(api.cancel_order(order["id"], make_customer_headers(customer["id"])))

    after = validate_success(api.get_store_inventory(inv["id"], make_manager_headers()))
    assert after["reserved"] == 0, after
    assert after["on_hand"] == 5, after
    assert after["available"] == 5, after
    assert_inventory_invariants(after)


def test_submit_cancel_inventory_units_no_drift_invariant(api):
    """PRD §2.6: "it equals `on_hand` minus `reserved`, floored so it never drops below
    zero — in other words, the larger of zero and the difference between on-hand and
    reserved units."

    Design: Difficulty/compensating_invariant/inventory_units_conserved_on_submit_then_cancel
    """
    base = fx.seed_base_scenario(products=[{"price": 1000, "on_hand": 5}])
    inv = base["inventories"][0]
    customer = base["customer"]
    before = validate_success(api.get_store_inventory(inv["id"], make_manager_headers()))

    order = fx.create_draft_order(customer["id"], base["store"]["id"])
    fx.add_line(order["id"], customer["id"], base["products"][0]["id"], 2)
    fx.submit_order(order["id"], customer["id"], base["slot"]["id"], base["slot_version"])
    validate_success(api.cancel_order(order["id"], make_customer_headers(customer["id"])))

    after = validate_success(api.get_store_inventory(inv["id"], make_manager_headers()))
    assert after["on_hand"] == before["on_hand"]
    assert after["reserved"] == before["reserved"]
    assert after["available"] == before["available"]


def test_inventory_available_equals_on_hand_at_create(api):
    """PRD §3.1: "On creation the row's `reserved` is zero and `available` equals
    `on_hand`, and an initial `RESTOCK` `InventoryMovement` is appended to the ledger."

    Design: Corner/entities/inventory_computed_available_equals_on_hand_at_create
    """
    store = fx.create_store()
    product = fx.create_product()
    inv = validate_success(api.create_store_inventory(
        f.create_store_inventory_payload(store["id"], product["id"], on_hand=7),
        fx.make_admin_headers()), expected_status=201)
    assert inv["reserved"] == 0, inv
    assert inv["available"] == 7, inv


def test_restock_increases_on_hand_and_available(api):
    """PRD §2.6: "Availability is recomputed on every reservation, release, pick, or
    restock that affects the row, and it equals `on_hand` minus `reserved`, floored so
    it never drops below zero — in other words, the larger of zero and the difference
    between on-hand and reserved units."
    PRD §2.4: "`version`, an integer that begins at 1 and increments by one on every
    mutation of that resource."

    Design: Corner/calculations/restock_increases_on_hand_and_available
    """
    store = fx.create_store()
    product = fx.create_product()
    inv = fx.create_inventory(store["id"], product["id"], on_hand=5)
    restocked = validate_success(api.restock_inventory(
        inv["id"], f.restock_payload(3, inv["version"]), make_manager_headers()))
    assert restocked["on_hand"] == 8, restocked
    assert restocked["available"] == 8, restocked
    assert restocked["version"] == 2, restocked


def test_duplicate_inventory_same_store_product_rejected(api):
    """PRD §3.1: "The pair is unique: a second attempt to create inventory for the same
    `store_id` and `product_id` is rejected with `ERR_DUPLICATE_INVENTORY`."

    Design: Corner/entities/duplicate_inventory_same_store_product_returns_409
    """
    store = fx.create_store()
    product = fx.create_product()
    fx.create_inventory(store["id"], product["id"], on_hand=5)
    resp = api.create_store_inventory(
        f.create_store_inventory_payload(store["id"], product["id"], on_hand=3),
        fx.make_admin_headers())
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_INVENTORY.value)
