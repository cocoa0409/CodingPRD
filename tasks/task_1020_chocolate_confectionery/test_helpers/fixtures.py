"""Composite setup helpers for multi-step test prerequisites (PRD Section 3).

The harness restarts the API process before every individual test, so the
database is empty at the start of every test — each fixture rebuilds its
preconditions from scratch using only PRD-declared endpoints. All setup calls
use ``get_success_data()`` (lenient 2xx validator) so setup failures surface as
clear "Setup failed" errors rather than confusing assertion failures.

Identity threading (PRD §2.1): the Customer role is entity-backed, so every
Customer-role call is issued with ``make_customer_headers(customer_id)`` once the
customer exists, matching X-User-ID to the acting customer's id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_customer_payload,
    create_product_payload,
    create_mold_payload,
    create_tempering_line_payload,
    create_batch_payload,
    create_order_payload,
    order_line_payload,
    create_custom_order_payload,
    create_subscription_payload,
    start_tempering_payload,
    wallet_adjust_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS, make_customer_headers

ADMIN = TEST_USERS["admin_headers"]
SALES = TEST_USERS["sales_manager_headers"]
PROD = TEST_USERS["production_manager_headers"]


# --- Clock primitive (PRD §4) ---
def set_clock(to_iso8601: str) -> None:
    get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), ADMIN))


# --- Primitive entity builders ---
def create_customer(**overrides) -> dict:
    return get_success_data(
        api_client.create_customer(create_customer_payload(**overrides), ADMIN)
    )


def create_product(**overrides) -> dict:
    return get_success_data(
        api_client.create_product(create_product_payload(**overrides), ADMIN)
    )


def create_mold(**overrides) -> dict:
    return get_success_data(
        api_client.create_mold(create_mold_payload(**overrides), PROD)
    )


def create_tempering_line(**overrides) -> dict:
    return get_success_data(
        api_client.create_tempering_line(create_tempering_line_payload(**overrides), PROD)
    )


def create_batch(product_id: str, initial_units: int, **overrides) -> dict:
    return get_success_data(
        api_client.create_batch(
            create_batch_payload(product_id, initial_units, **overrides), PROD
        )
    )


def adjust_wallet(customer_id: str, amount_cents: int) -> dict:
    return get_success_data(
        api_client.adjust_wallet(customer_id, wallet_adjust_payload(amount_cents), ADMIN)
    )


def create_order(customer_id: str, order_type: str = "RETAIL", **overrides) -> dict:
    return get_success_data(
        api_client.create_order(
            create_order_payload(customer_id, order_type, **overrides),
            make_customer_headers(customer_id),
        )
    )


def add_line(order_id: str, customer_id: str, product_id: str, quantity: int) -> dict:
    return get_success_data(
        api_client.add_order_line(
            order_id, order_line_payload(product_id, quantity),
            make_customer_headers(customer_id),
        )
    )


def confirm_order(order_id: str, customer_id: str, **payload) -> dict:
    return get_success_data(
        api_client.confirm_order(order_id, make_customer_headers(customer_id), payload)
    )


def allocate_order(order_id: str) -> dict:
    return get_success_data(api_client.allocate_order(order_id, SALES))


def create_custom_order(customer_id: str, product_id: str, mold_id: str, units_estimated: int) -> dict:
    return get_success_data(
        api_client.create_custom_order(
            create_custom_order_payload(customer_id, product_id, mold_id, units_estimated),
            make_customer_headers(customer_id),
        )
    )


def quote_custom_order(co_id: str) -> dict:
    return get_success_data(api_client.quote_custom_order(co_id, SALES))


def accept_custom_order(co_id: str, customer_id: str, usage_date: str) -> dict:
    return get_success_data(
        api_client.accept_custom_order(
            co_id, {"usage_date": usage_date}, make_customer_headers(customer_id)
        )
    )


def create_subscription(customer_id: str, box_product_id: str, cadence_days: int, next_ship_date: str) -> dict:
    return get_success_data(
        api_client.create_subscription(
            create_subscription_payload(customer_id, box_product_id, cadence_days, next_ship_date),
            make_customer_headers(customer_id),
        )
    )


# --- Batch state-progression helpers (PRD §3.3) ---
def create_released_batch(product_id: str, initial_units: int, **batch_overrides) -> dict:
    """Create a RAW batch of a non-tempering product and release it directly to
    RELEASED (PRD §3.3: RAW->RELEASED when no tempering). Returns the released
    batch (its ``version`` reflects the release mutation)."""
    batch = create_batch(product_id, initial_units, **batch_overrides)
    return get_success_data(api_client.release_batch(batch["id"], PROD))


def create_tempering_batch_raw(tempering_minutes: int = 60, initial_units: int = 100, **prod_overrides) -> dict:
    """A tempering product + one tempering line + one RAW batch (not yet started).
    Returns dict(product, line, batch)."""
    product = create_product(
        requires_tempering=True, tempering_minutes=tempering_minutes, **prod_overrides
    )
    line = create_tempering_line()
    batch = create_batch(product["id"], initial_units)
    return {"product": product, "line": line, "batch": batch}


# --- Order state-progression helpers (PRD §3.5, §3.6) ---
def setup_confirmed_retail_order(
    line_qty: int = 1, base_price: int = 1000, order_type: str = "RETAIL",
    loyalty_discount_pct: float = 0.0, is_gift: bool = False,
    wallet_grant: int = 0, wallet_apply_cents=None, **prod_overrides,
) -> dict:
    """Customer + product + order (one line) confirmed. Returns dict with
    customer, product, order, line."""
    cust_kwargs = {"account_type": "RETAIL"}
    if loyalty_discount_pct:
        cust_kwargs["loyalty_discount_pct"] = loyalty_discount_pct
    customer = create_customer(**cust_kwargs)
    if wallet_grant:
        adjust_wallet(customer["id"], wallet_grant)
    product = create_product(base_price_cents=base_price, **prod_overrides)
    order = create_order(customer["id"], order_type, is_gift=is_gift)
    line = add_line(order["id"], customer["id"], product["id"], line_qty)
    confirm_payload = {}
    if wallet_apply_cents is not None:
        confirm_payload["wallet_apply_cents"] = wallet_apply_cents
    order = confirm_order(order["id"], customer["id"], **confirm_payload)
    return {"customer": customer, "product": product, "order": order, "line": line}


def setup_allocated_retail_order(
    batch_units: int = 100, line_qty: int = 30, base_price: int = 1000,
    shelf_life_days: int = 60,
) -> dict:
    """Non-tempering product, one RELEASED batch, one retail order with a single
    line confirmed and allocated over that batch (FEFO). Returns dict with
    customer, product, batch, order, line."""
    customer = create_customer(account_type="RETAIL")
    product = create_product(base_price_cents=base_price, shelf_life_days=shelf_life_days)
    batch = create_released_batch(product["id"], batch_units)
    order = create_order(customer["id"], "RETAIL")
    line = add_line(order["id"], customer["id"], product["id"], line_qty)
    confirm_order(order["id"], customer["id"])
    order = allocate_order(order["id"])
    return {"customer": customer, "product": product, "batch": batch,
            "order": order, "line": line}


# --- Custom-order state-progression helpers (PRD §3.7) ---
def setup_quoted_custom_order(
    units_estimated: int = 100, base_price: int = 1500, daily_capacity: int = 500,
    account_type: str = "CORPORATE",
) -> dict:
    """Customer + product + mold + custom order advanced DRAFT->QUOTED.
    Returns dict with customer, product, mold, custom_order."""
    customer = create_customer(account_type=account_type)
    product = create_product(base_price_cents=base_price)
    mold = create_mold(daily_capacity_units=daily_capacity)
    co = create_custom_order(customer["id"], product["id"], mold["id"], units_estimated)
    co = quote_custom_order(co["id"])
    return {"customer": customer, "product": product, "mold": mold, "custom_order": co}


def setup_accepted_custom_order(
    units_estimated: int = 100, base_price: int = 1500, daily_capacity: int = 500,
    usage_date: str = "2026-07-10T00:00:00Z", account_type: str = "CORPORATE",
) -> dict:
    """Custom order advanced through to ACCEPTED (mold booked).
    Returns dict with customer, product, mold, custom_order."""
    setup = setup_quoted_custom_order(
        units_estimated=units_estimated, base_price=base_price,
        daily_capacity=daily_capacity, account_type=account_type,
    )
    co = accept_custom_order(setup["custom_order"]["id"], setup["customer"]["id"], usage_date)
    setup["custom_order"] = co
    return setup
