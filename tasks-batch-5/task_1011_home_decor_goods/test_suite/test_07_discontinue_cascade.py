"""CASCADE-A: discontinuing a product ripples through store inventory, registry
items, and their parent registries."""
from test_helpers import (
    validate_success, new_store, new_product, new_inventory, new_member,
    new_registry, new_registry_item, get_inventory, api_client, TEST_USERS,
)

MERCH = TEST_USERS["merch_headers"]


def _discontinue_with_registry_ref():
    store = new_store(name="Store D1")
    product = new_product(sku="SKU-D1", name="Table Lamp", category="DECOR",
                          base_price_cents=3000, clearance_floor_cents=300,
                          first_received_at="2026-06-25T00:00:00Z")
    inv = new_inventory(store["id"], product["id"], 5)
    member = new_member(email="d1@x.com", full_name="D One")
    registry = new_registry(member["id"], title="Housewarming", event_date="2026-12-01")
    item = new_registry_item(registry["id"], member["id"], product["id"], 2)
    validate_success(api_client.discontinue_product(product["id"], MERCH))
    return product, inv, item


def test_discontinue_kills_stocked_inventory():
    """PRD §2.8: "When a `MerchandisingManager` discontinues a product, a
    three-level cascade fires (CASCADE-A): every `ACTIVE` store-inventory row for
    that product is set to `DEAD` (its `reserved_qty` remains reserved for open
    order lines); each row that just went `DEAD` drives every `OPEN` registry item
    for that product to `UNAVAILABLE`; and each registry item that just became
    `UNAVAILABLE` refreshes its parent registry's `updated_at`."

    Design: Difficulty/transitive_cascade/discontinue_product_cascade_depth3
    """
    product, inv, _ = _discontinue_with_registry_ref()
    read = validate_success(api_client.get_product(product["id"], MERCH))
    assert read["status"] == "DISCONTINUED", f"expected DISCONTINUED, got {read['status']}"
    inv_after = get_inventory(inv["id"])
    assert inv_after["status"] == "DEAD", f"expected DEAD inventory, got {inv_after['status']}"


def test_discontinue_makes_registry_item_unavailable():
    """PRD §3.8: "When the item's product is discontinued, CASCADE-A drives the item
    from `OPEN` to `UNAVAILABLE`."

    Design: Difficulty/transitive_cascade/discontinue_product_cascade_depth3
    """
    _, _, item = _discontinue_with_registry_ref()
    read = validate_success(api_client.get_registry_item(item["id"], MERCH))
    assert read["status"] == "UNAVAILABLE", f"expected UNAVAILABLE, got {read['status']}"
