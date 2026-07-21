"""Catalog authoring and inventory reconciliation.

Covers product creation + computed stock_available, restock recomputation, the
reserve-time sufficiency and discontinued-component checks, the reserved-inventory
conservation invariant, and the completion consume-without-drift rule.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_product_payload, create_member_payload, create_board_build_payload,
    TEST_USERS, assert_product,
    create_active_product, create_member, create_build_in_state,
    get_success_data,
)

SM = TEST_USERS["shop_manager_headers"]
ASSOC = TEST_USERS["associate_headers"]


def test_create_product_computes_available(api):
    """PRD §2.7: "A product created with a given `stock_on_hand` starts with
    `stock_reserved` at 0, so its initial `stock_available` equals its `stock_on_hand`."

    Design: Corner/entities/create_product_returns_201_with_computed_available
    """
    resp = api.create_product(create_product_payload(
        name="Deck", category="DECK", unit_price_cents=6000, stock_on_hand=5), SM)
    data = validate_success(resp, 201)
    assert_product(data)
    assert data["stock_reserved"] == 0
    assert data["stock_available"] == 5


def test_create_product_default_buildable_false(api):
    """PRD §3.1: "Optionally the manager may set `buildable_component` (whether the
    product may appear as a component in a board build; defaults to false), an
    initial `stock_on_hand` (defaults to 0), and a `reorder_threshold` (a low-stock
    reporting level, defaults to 0)."

    Design: Corner/entities/create_product_default_buildable_false
    """
    resp = api.create_product(create_product_payload(
        name="Wax", category="WAX", unit_price_cents=500), SM)
    data = validate_success(resp, 201)
    assert data["buildable_component"] is False


def test_create_product_missing_category_returns_validation(api):
    """PRD §3.1: "Creating a product requires a unique `sku`, a display `name`, a
    `category` — one of `DECK`, `TRUCK`, `WHEELS`, `BEARINGS`, `GRIP`, `WAX`,
    `SURFBOARD`, or `ACCESSORY` — and a `unit_price_cents` that must be zero or greater."

    Design: Corner/entities/create_product_missing_category_returns_validation
    """
    payload = {"sku": "P3-nocat", "name": "NoCat", "unit_price_cents": 100}
    resp = api.create_product(payload, SM)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_restock_recomputes_available(api):
    """PRD §3.1: "may restock it by supplying a `quantity` that is added to
    `stock_on_hand`, with `stock_available` recomputed."

    Design: Corner/entities/restock_recomputes_stock_available
    """
    prod = create_active_product(api, unit_price_cents=2000, stock_on_hand=2,
                                 buildable_component=False, category="BEARINGS")
    resp = api.restock_product(prod["id"], {"quantity": 3}, SM)
    data = validate_success(resp, 200)
    assert data["stock_on_hand"] == 5
    assert data["stock_available"] == 5


def test_reserve_insufficient_stock(api):
    """PRD §3.3: "must have `stock_available` at least the line quantity (else
    `ERR_INSUFFICIENT_STOCK`)."

    Design: Corner/errors/reserve_insufficient_stock_returns_error
    """
    prod = create_active_product(api, unit_price_cents=6000, stock_on_hand=1)
    member = create_member(api)
    build = get_success_data(api.create_board_build(create_board_build_payload(
        member["id"], [{"product_id": prod["id"], "qty": 2}]), ASSOC))
    resp = api.reserve_board_build(build["id"], ASSOC)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK.value)
    # No reservation is taken on a rejected reserve.
    prod_after = get_success_data(api.get_product(prod["id"], SM))
    assert prod_after["stock_reserved"] == 0


def test_reserve_discontinued_component(api):
    """PRD §3.1: "Only `ACTIVE` products may be reserved as build components; naming
    a `DISCONTINUED` product as a component is rejected with `ERR_PRODUCT_DISCONTINUED`."

    Design: Corner/errors/reserve_discontinued_component_returns_error
    """
    prod = create_active_product(api, unit_price_cents=6000, stock_on_hand=5)
    member = create_member(api)
    build = get_success_data(api.create_board_build(create_board_build_payload(
        member["id"], [{"product_id": prod["id"], "qty": 1}]), ASSOC))
    api.update_product(prod["id"], {"status": "DISCONTINUED"}, SM)
    resp = api.reserve_board_build(build["id"], ASSOC)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_DISCONTINUED.value)


def test_reserve_then_cancel_restores_stock_reserved(api):
    """PRD §3.3: "when cancelled from a state that held reservations
    (`COMPONENTS_RESERVED`, `ASSEMBLED`, or `SETUP_COMPLETE`), each component
    product's `stock_reserved` is released, and any linked service orders in
    `SCHEDULED` or `IN_PROGRESS` are cancelled."

    Design: Difficulty/compensating_invariant/inventory_reserved_conserved_reserve_then_cancel
    """
    build, member, products = create_build_in_state(
        api, target_state="COMPONENTS_RESERVED",
        lines_spec=[{"price": 3000, "qty": 2, "stock": 5}])
    prod = products[0]
    reserved = get_success_data(api.get_product(prod["id"], SM))
    assert reserved["stock_reserved"] == 2
    api.cancel_board_build(build["id"], ASSOC)
    after = get_success_data(api.get_product(prod["id"], SM))
    assert after["stock_reserved"] == 0


def test_reserve_then_cancel_conserves_on_hand_and_available(api):
    """PRD §2.7: "releasing a reservation (a build revision or any cancellation that
    held stock) lowers `stock_reserved` back; and consuming inventory at completion
    lowers both `stock_on_hand` and `stock_reserved` by the same amount, so
    `stock_available` is unchanged by the consumption step itself."

    Design: Difficulty/compensating_invariant/inventory_reserved_conserved_reserve_then_cancel
    """
    build, member, products = create_build_in_state(
        api, target_state="COMPONENTS_RESERVED",
        lines_spec=[{"price": 3000, "qty": 2, "stock": 5}])
    prod = products[0]
    api.cancel_board_build(build["id"], ASSOC)
    after = get_success_data(api.get_product(prod["id"], SM))
    assert after["stock_on_hand"] == 5
    assert after["stock_reserved"] == 0
    assert after["stock_available"] == 5


def test_build_complete_consumes_reservation_no_drift(api):
    """PRD §3.3: "Completion converts reservation to consumption: each component
    product's `stock_on_hand` and `stock_reserved` are both lowered by the line
    quantity (leaving `stock_available` unchanged by that step), loyalty is awarded
    to the member on the `final_total_cents` net amount per §2.9, and `completed_at`
    is stamped."

    Design: Corner/cross_cutting_complexity_layers/build_complete_consumes_reservation_no_available_drift
    """
    build, member, products = create_build_in_state(
        api, target_state="SETUP_COMPLETE",
        lines_spec=[{"price": 6000, "qty": 1, "stock": 5}])
    api.complete_board_build(build["id"], ASSOC)
    prod = get_success_data(api.get_product(products[0]["id"], SM))
    assert prod["stock_on_hand"] == 4
    assert prod["stock_reserved"] == 0
    assert prod["stock_available"] == 4
