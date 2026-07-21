"""Composite setup helpers.

Every test runs against a freshly restarted (empty) server, so each helper
builds its preconditions from scratch using only PRD-declared endpoints. Helpers
use get_success_data() (lenient) so setup problems surface as clear "Setup
failed" errors rather than confusing assertion failures.

Identity threading: Customer is entity_backed, so any ownership-gated call uses
make_customer_headers(customer["id"]) with the real Customer.id — never the
shared TEST_USERS constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_store_staff_headers,
    make_platform_admin_headers,
    make_anonymous_headers,
)
from . import factories as f


ADMIN = TEST_USERS["platform_admin_headers"]
STAFF = TEST_USERS["store_staff_headers"]
ANON = TEST_USERS["anonymous_headers"]


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
def set_clock(api, to_iso8601: str):
    """Advance the logical clock to a supplied instant (PlatformAdmin only)."""
    return get_success_data(api.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# --------------------------------------------------------------------------
# Single-entity creators
# --------------------------------------------------------------------------
def new_store(api, **overrides) -> dict:
    return get_success_data(api.create_store(f.create_store_payload(**overrides), ADMIN))


def new_customer(api, **overrides) -> dict:
    return get_success_data(api.create_customer(f.create_customer_payload(**overrides), ANON))


def new_sku(api, store_id, **overrides) -> dict:
    return get_success_data(api.create_sku(f.create_sku_payload(store_id, **overrides), STAFF))


def new_registry(api, customer_id, **overrides) -> dict:
    hdr = make_customer_headers(customer_id)
    return get_success_data(
        api.create_registry(f.create_registry_payload(customer_id, **overrides), hdr)
    )


def new_shelf(api, store_id, **overrides) -> dict:
    return get_success_data(api.create_shelf(store_id, f.create_shelf_payload(**overrides), STAFF))


def new_consignment_item(api, consignor_customer_id, store_id, **overrides) -> dict:
    hdr = make_customer_headers(consignor_customer_id)
    return get_success_data(
        api.create_consignment_item(
            f.create_consignment_item_payload(consignor_customer_id, store_id, **overrides), hdr
        )
    )


def new_trade_in(api, customer_id, sku_id, submitted_condition="GOOD", **overrides) -> dict:
    hdr = make_customer_headers(customer_id)
    return get_success_data(
        api.create_trade_in(
            f.create_trade_in_payload(customer_id, sku_id, submitted_condition, **overrides), hdr
        )
    )


def new_special_order(api, customer_id, sku_id, store_id, **overrides) -> dict:
    hdr = make_customer_headers(customer_id)
    return get_success_data(
        api.create_special_order(
            f.create_special_order_payload(customer_id, sku_id, store_id, **overrides), hdr
        )
    )


# --------------------------------------------------------------------------
# Common baseline: store + BRONZE customer + one SKU
# --------------------------------------------------------------------------
def setup_store_customer_sku(api, sku_overrides=None, customer_overrides=None,
                             store_overrides=None) -> dict:
    """Active baseline for order/pricing tests: a store, a customer, and one SKU.
    Returns {"store", "customer", "sku"}."""
    store = new_store(api, **(store_overrides or {}))
    customer = new_customer(api, **(customer_overrides or {}))
    sku = new_sku(api, store["id"], **(sku_overrides or {}))
    return {"store": store, "customer": customer, "sku": sku}


# --------------------------------------------------------------------------
# Registry helpers
# --------------------------------------------------------------------------
def activate_registry(api, registry_id, customer_id):
    hdr = make_customer_headers(customer_id)
    return get_success_data(api.activate_registry(registry_id, hdr))


def add_item(api, registry_id, customer_id, sku_id, desired_qty) -> dict:
    hdr = make_customer_headers(customer_id)
    return get_success_data(
        api.add_registry_item(
            registry_id, f.create_registry_item_payload(sku_id, desired_qty), hdr
        )
    )


def read_registry_version(api, registry_id, customer_id) -> int:
    hdr = make_customer_headers(customer_id)
    reg = get_success_data(api.get_registry(registry_id, hdr))
    return reg["version"]


def setup_active_registry_with_item(api, base_price_cents=10000, desired_qty=5,
                                    on_hand=100, event_date="2026-09-01T00:00:00Z",
                                    kind="BABY_REGISTRY", store=None, customer=None) -> dict:
    """Store + SKU + Customer + ACTIVE BABY_REGISTRY with one item added.
    Returns {"store","customer","sku","registry","item","version"} where
    version is the registry's current version after the item add (for OCC gifts).
    """
    store = store or new_store(api)
    customer = customer or new_customer(api)
    sku = new_sku(api, store["id"], base_price_cents=base_price_cents, initial_on_hand_qty=on_hand)
    registry = new_registry(api, customer["id"], event_date=event_date, kind=kind)
    activate_registry(api, registry["id"], customer["id"])
    item = add_item(api, registry["id"], customer["id"], sku["id"], desired_qty)
    version = read_registry_version(api, registry["id"], customer["id"])
    return {
        "store": store, "customer": customer, "sku": sku,
        "registry": registry, "item": item, "version": version,
    }


def setup_draft_registry_with_item(api, base_price_cents=10000, desired_qty=5,
                                   on_hand=100) -> dict:
    """Store + SKU + Customer + DRAFT registry (NOT activated) with one item.
    Returns {"store","customer","sku","registry","item","version"}."""
    store = new_store(api)
    customer = new_customer(api)
    sku = new_sku(api, store["id"], base_price_cents=base_price_cents, initial_on_hand_qty=on_hand)
    registry = new_registry(api, customer["id"])
    item = add_item(api, registry["id"], customer["id"], sku["id"], desired_qty)
    version = read_registry_version(api, registry["id"], customer["id"])
    return {
        "store": store, "customer": customer, "sku": sku,
        "registry": registry, "item": item, "version": version,
    }


def gift(api, registry_id, customer_id, registry_item_id, qty, expected_registry_version) -> dict:
    hdr = make_customer_headers(customer_id)
    return get_success_data(
        api.create_gift(
            registry_id,
            f.create_gift_payload(registry_item_id, qty, expected_registry_version),
            hdr,
        )
    )


# --------------------------------------------------------------------------
# Order helpers
# --------------------------------------------------------------------------
def create_order(api, customer_id, store_id, lines, **overrides) -> dict:
    hdr = make_customer_headers(customer_id)
    return get_success_data(
        api.create_order(f.create_order_payload(customer_id, store_id, lines, **overrides), hdr)
    )


def setup_order(api, sku_overrides=None, qty=1, order_overrides=None,
                customer_overrides=None) -> dict:
    """Store + customer + SKU + one RESERVED/UNPAID order for a single line.
    Returns {"store","customer","sku","order"}."""
    base = setup_store_customer_sku(
        api, sku_overrides=sku_overrides, customer_overrides=customer_overrides
    )
    order = create_order(
        api, base["customer"]["id"], base["store"]["id"],
        [f.order_line(base["sku"]["id"], qty)], **(order_overrides or {})
    )
    base["order"] = order
    return base


def pay_order(api, order_id, customer_id, payment_method="CARD") -> dict:
    hdr = make_customer_headers(customer_id)
    return get_success_data(api.pay_order(order_id, {"payment_method": payment_method}, hdr))


def setup_paid_order(api, sku_overrides=None, qty=1, payment_method="CARD",
                     customer_overrides=None) -> dict:
    """Store + customer + SKU + a PAID (still RESERVED) order.
    Returns {"store","customer","sku","order"}."""
    base = setup_order(api, sku_overrides=sku_overrides, qty=qty,
                       customer_overrides=customer_overrides)
    pay_order(api, base["order"]["id"], base["customer"]["id"], payment_method)
    return base


def setup_picked_up_order(api, sku_overrides=None, qty=1) -> dict:
    """Order driven all the way to fulfillment_status PICKED_UP (paid by CARD,
    marked ready, pickup completed). Returns {"store","customer","sku","order"}."""
    base = setup_paid_order(api, sku_overrides=sku_overrides, qty=qty, payment_method="CARD")
    oid = base["order"]["id"]
    get_success_data(api.mark_ready_order(oid, STAFF))
    get_success_data(api.complete_pickup_order(oid, STAFF))
    return base


# --------------------------------------------------------------------------
# Consignment helpers
# --------------------------------------------------------------------------
def display_item(api, item_id, shelf_id, display_start, display_end):
    return get_success_data(
        api.display_consignment_item(
            item_id, f.display_payload(shelf_id, display_start, display_end), STAFF
        )
    )


def setup_displayed_consignment_item(api, condition="LIKE_NEW", item_season="IN_SEASON",
                                     list_price_cents=10000, shelf_capacity=5,
                                     display_start="2026-07-01T00:00:00Z",
                                     display_end="2026-07-31T00:00:00Z") -> dict:
    """Store + OPEN shelf + consignor + one ON_DISPLAY consignment item.
    Returns {"store","customer","shelf","item"}."""
    store = new_store(api)
    shelf = new_shelf(api, store["id"], capacity=shelf_capacity)
    customer = new_customer(api)
    item = new_consignment_item(
        api, customer["id"], store["id"],
        condition=condition, season=item_season, list_price_cents=list_price_cents,
    )
    item = display_item(api, item["id"], shelf["id"], display_start, display_end)
    return {"store": store, "customer": customer, "shelf": shelf, "item": item}
