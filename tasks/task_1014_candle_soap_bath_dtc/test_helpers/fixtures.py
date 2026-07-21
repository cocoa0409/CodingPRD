"""
Composite setup helpers for multi-step test prerequisites (PRD §3).

Uses get_success_data() (lenient 2xx validator) so setup failures surface as clear
"Setup failed" errors rather than confusing assertion failures.

Identity threading: every Customer-owned, ownership-gated call uses
make_customer_headers(customer["id"]) — never the shared TEST_USERS constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_product_payload, create_sku_payload, create_batch_payload,
    create_drop_payload, create_bundle_payload, create_customer_payload,
    create_order_payload, create_line_payload, create_subscription_payload,
    create_return_payload,
)
from .test_users import TEST_USERS, make_customer_headers
from .constants import DEFAULT_CLOCK

MERCHOPS = TEST_USERS["merchops_headers"]
ADMIN = TEST_USERS["admin_headers"]


# ─── Primitive builders ────────────────────────────────────────────────

def set_clock(to_iso8601: str):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def new_product(product_type: str = "SOAP", **overrides) -> dict:
    return get_success_data(api_client.create_product(
        create_product_payload(product_type=product_type, **overrides), MERCHOPS))


def new_sku(product_id: str, list_price_cents: int = 1000, **overrides) -> dict:
    return get_success_data(api_client.create_sku(
        product_id, create_sku_payload(list_price_cents=list_price_cents, **overrides), MERCHOPS))


def new_batch(sku_id: str, quantity_produced: int = 100, **overrides) -> dict:
    return get_success_data(api_client.create_batch(
        sku_id, create_batch_payload(quantity_produced=quantity_produced, **overrides), MERCHOPS))


def label_batch(batch_id: str) -> dict:
    return get_success_data(api_client.label_batch(batch_id, MERCHOPS))


def release_batch(batch_id: str) -> dict:
    return get_success_data(api_client.release_batch(batch_id, MERCHOPS))


def new_customer(**overrides) -> dict:
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), ADMIN))


def grant_loyalty(customer_id: str, points: int) -> dict:
    return get_success_data(api_client.grant_loyalty(customer_id, points, ADMIN))


def suspend_customer(customer_id: str) -> dict:
    return get_success_data(api_client.suspend_customer(customer_id, ADMIN))


def new_order(customer_id: str, order_type: str = "RETAIL", **overrides) -> dict:
    return get_success_data(api_client.create_order(
        customer_id, create_order_payload(order_type=order_type, **overrides),
        make_customer_headers(customer_id)))


def add_line(order_id: str, customer_id: str, sku_id: str, batch_id: str, quantity: int = 1) -> dict:
    return get_success_data(api_client.add_line(
        order_id, create_line_payload(sku_id, batch_id, quantity),
        make_customer_headers(customer_id)))


def get_order_version(order_id: str, customer_id: str) -> int:
    order = get_success_data(api_client.get_order(order_id, make_customer_headers(customer_id)))
    return order["version"]


def checkout(order_id: str, customer_id: str, version=None) -> dict:
    if version is None:
        version = get_order_version(order_id, customer_id)
    return get_success_data(api_client.checkout_order(
        order_id, version, make_customer_headers(customer_id)))


def fulfill(order_id: str) -> dict:
    return get_success_data(api_client.fulfill_order(order_id, MERCHOPS))


def cancel_order(order_id: str, customer_id: str) -> dict:
    return get_success_data(api_client.cancel_order(order_id, make_customer_headers(customer_id)))


# ─── Fresh reads (server resets DB per test; always re-fetch after mutations) ───

def fetch_batch(batch_id: str) -> dict:
    return get_success_data(api_client.get_batch(batch_id, MERCHOPS))


def fetch_customer(customer_id: str) -> dict:
    return get_success_data(api_client.get_customer(customer_id, ADMIN))


def fetch_order(order_id: str) -> dict:
    return get_success_data(api_client.get_order(order_id, MERCHOPS))


def fetch_order_line(order_line_id: str) -> dict:
    return get_success_data(api_client.get_order_line(order_line_id, MERCHOPS))


def fetch_subscription(subscription_id: str) -> dict:
    return get_success_data(api_client.get_subscription(subscription_id, MERCHOPS))


def fetch_return(return_id: str) -> dict:
    return get_success_data(api_client.get_return(return_id, MERCHOPS))


# ─── Tier 1/2: released sku + batch ────────────────────────────────────

def released_catalog(product_type: str = "SOAP", list_price_cents: int = 1000,
                     quantity: int = 100, labeled: bool = False,
                     sku_overrides=None) -> dict:
    """Product + sku + RELEASED batch (optionally LABELED first).

    Returns {product, sku, batch}. `labeled=True` stamps the safety label before
    releasing (needed for safety-required CANDLE/WAX_MELT skus).
    """
    product = new_product(product_type=product_type)
    sku = new_sku(product["id"], list_price_cents=list_price_cents, **(sku_overrides or {}))
    batch = new_batch(sku["id"], quantity_produced=quantity)
    if labeled:
        label_batch(batch["id"])
    batch = release_batch(batch["id"])
    return {"product": product, "sku": sku, "batch": batch}


# ─── Tier 3: order lifecycle shortcuts ─────────────────────────────────

def reserved_order(product_type: str = "SOAP", list_price_cents: int = 1000,
                   quantity: int = 1, batch_quantity: int = 100,
                   order_type: str = "RETAIL", grant_points: int = 0,
                   labeled: bool = False) -> dict:
    """Active customer + PENDING order carrying one RESERVED line.

    Returns {product, sku, batch, customer, order, line}.
    """
    cat = released_catalog(product_type=product_type, list_price_cents=list_price_cents,
                           quantity=batch_quantity, labeled=labeled)
    customer = new_customer()
    if grant_points:
        grant_loyalty(customer["id"], grant_points)
    order = new_order(customer["id"], order_type=order_type)
    line = add_line(order["id"], customer["id"], cat["sku"]["id"], cat["batch"]["id"], quantity)
    return {**cat, "customer": customer, "order": order, "line": line}


def checked_out_order(product_type: str = "SOAP", list_price_cents: int = 1000,
                      quantity: int = 1, batch_quantity: int = 100,
                      order_type: str = "RETAIL", grant_points: int = 0) -> dict:
    """PAID/ALLOCATED order (one line). Returns {..., order} with order post-checkout."""
    ctx = reserved_order(product_type=product_type, list_price_cents=list_price_cents,
                         quantity=quantity, batch_quantity=batch_quantity,
                         order_type=order_type, grant_points=grant_points)
    ctx["order"] = checkout(ctx["order"]["id"], ctx["customer"]["id"])
    return ctx


def delivered_order(product_type: str = "SOAP", list_price_cents: int = 1000,
                    quantity: int = 1, batch_quantity: int = 100,
                    grant_points: int = 0) -> dict:
    """DELIVERED order (checked out then fulfilled). Returns {..., order}."""
    ctx = checked_out_order(product_type=product_type, list_price_cents=list_price_cents,
                            quantity=quantity, batch_quantity=batch_quantity,
                            grant_points=grant_points)
    ctx["order"] = fulfill(ctx["order"]["id"])
    return ctx


# ─── Tier 4/5: subscriptions, bundles, drops ───────────────────────────

def subscription_ctx(list_price_cents: int = 1000, batch_quantity: int = 100,
                     quantity: int = 5, cadence_days: int = 30,
                     num_released_batches: int = 1) -> dict:
    """Clock at default. Soap sku + `num_released_batches` released batches +
    ACTIVE customer + ACTIVE subscription (not yet due).

    Returns {product, sku, batches, customer, subscription}.
    """
    set_clock(DEFAULT_CLOCK)
    product = new_product(product_type="SOAP")
    sku = new_sku(product["id"], list_price_cents=list_price_cents)
    batches = []
    for _ in range(num_released_batches):
        b = new_batch(sku["id"], quantity_produced=batch_quantity)
        batches.append(release_batch(b["id"]))
    customer = new_customer()
    subscription = get_success_data(api_client.create_subscription(
        customer["id"], create_subscription_payload(sku["id"], quantity=quantity, cadence_days=cadence_days),
        make_customer_headers(customer["id"])))
    return {"product": product, "sku": sku, "batches": batches,
            "customer": customer, "subscription": subscription}


def new_bundle(items, bundle_price_cents: int = 5000, title: str = "Test Bundle") -> dict:
    return get_success_data(api_client.create_bundle(
        create_bundle_payload(title=title, items=items, bundle_price_cents=bundle_price_cents), MERCHOPS))


def new_drop(listings, starts_at: str, ends_at: str, **overrides) -> dict:
    return get_success_data(api_client.create_drop(
        create_drop_payload(listings=listings, starts_at=starts_at, ends_at=ends_at, **overrides), MERCHOPS))


def approved_return(product_type: str = "SOAP", list_price_cents: int = 3000,
                    quantity: int = 1, grant_points: int = 0) -> dict:
    """Delivered order with a REQUESTED->APPROVED return.

    Returns {product, sku, batch, customer, order, ret}.
    """
    ctx = delivered_order(product_type=product_type, list_price_cents=list_price_cents,
                          quantity=quantity, grant_points=grant_points)
    ret = get_success_data(api_client.request_return(
        ctx["order"]["id"], create_return_payload(), make_customer_headers(ctx["customer"]["id"])))
    ret = get_success_data(api_client.approve_return(ret["id"], MERCHOPS))
    ctx["ret"] = ret
    return ctx
