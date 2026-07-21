"""Order-line referential constraints: discontinued product, duplicate line,
and unstocked product."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, new_store, new_product,
    new_inventory, new_order, add_line, api_client, TEST_USERS,
)

MERCH = TEST_USERS["merch_headers"]
ASSOCIATE = TEST_USERS["associate_headers"]


# ─── add_line_requires_product_active (queue A) ───

def _discontinued_product_setup():
    store = new_store(name="Store CE2")
    product = new_product(sku="SKU-CE2", name="Planter", category="DECOR",
                          base_price_cents=1500, clearance_floor_cents=200,
                          first_received_at="2026-06-25T00:00:00Z")
    new_inventory(store["id"], product["id"], 5)
    validate_success(api_client.discontinue_product(product["id"], MERCH))
    order = new_order(store["id"], "CARRYOUT")
    return store, product, order


def test_add_line_for_discontinued_product_rejected():
    """PRD §3.1: "Any operation that references a `DISCONTINUED` product where an
    active one is required — such as adding an order line — is rejected with
    `ERR_PRODUCT_DISCONTINUED`."

    Design: Difficulty/cross_entity_state_dependency/add_line_requires_product_active
    """
    _, product, order = _discontinued_product_setup()
    resp = api_client.add_order_line(order["id"], {"product_id": product["id"], "qty": 1}, ASSOCIATE)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_DISCONTINUED.value)


def test_discontinue_moves_product_terminal_and_blocks_line():
    """PRD §3.1: "When a `MerchandisingManager` discontinues a product, the product
    moves from `ACTIVE` to `DISCONTINUED` (permitted only from `ACTIVE`), and the
    CASCADE-A propagation of §2.8 fires down through store inventory and registries.
    A discontinued product is terminal."

    Design: Difficulty/cross_entity_state_dependency/add_line_requires_product_active
    """
    _, product, order = _discontinued_product_setup()
    read = validate_success(api_client.get_product(product["id"], MERCH))
    assert read["status"] == "DISCONTINUED", f"expected DISCONTINUED, got {read['status']}"
    resp = api_client.add_order_line(order["id"], {"product_id": product["id"], "qty": 1}, ASSOCIATE)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_DISCONTINUED.value)


# ─── duplicate_line_for_same_product_rejected (queue B) ───

def test_second_line_for_same_product_rejected():
    """PRD §3.4: "At most one line may exist per product per order; a second line
    for the same product is rejected with `ERR_DUPLICATE_LINE`."

    Design: Corner/validations/duplicate_line_for_same_product_rejected
    """
    store = new_store(name="Store V4")
    product = new_product(sku="SKU-V4", name="Jar", category="KITCHEN",
                          base_price_cents=700, clearance_floor_cents=100,
                          first_received_at="2026-06-25T00:00:00Z")
    new_inventory(store["id"], product["id"], 10)
    order = new_order(store["id"], "CARRYOUT")
    add_line(order["id"], product["id"], 1)
    resp = api_client.add_order_line(order["id"], {"product_id": product["id"], "qty": 1}, ASSOCIATE)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_LINE.value)


# ─── add_line_product_not_stocked_rejected (queue B) ───

def test_add_line_for_unstocked_product_rejected():
    """PRD §3.4: "The referenced product must be stocked at the order's store —
    that is, a store-inventory row must exist for that store-and-product pair —
    otherwise the line is rejected with `ERR_PRODUCT_NOT_STOCKED`".

    Design: Corner/validations/add_line_product_not_stocked_rejected
    """
    store = new_store(name="Store V5")
    product = new_product(sku="SKU-V5", name="Runner", category="TEXTILE",
                          base_price_cents=1800, clearance_floor_cents=200,
                          first_received_at="2026-06-25T00:00:00Z")
    # No allocation for this product at this store.
    order = new_order(store["id"], "CARRYOUT")
    resp = api_client.add_order_line(order["id"], {"product_id": product["id"], "qty": 1}, ASSOCIATE)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_STOCKED.value)
