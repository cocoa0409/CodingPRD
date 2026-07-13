"""Composite setup helpers for multi-step test prerequisites.

Every test runs against a freshly restarted, empty server whose logical clock
starts at 2026-03-01T00:00:00Z. These helpers build the preconditions each test
needs from scratch, using only PRD-declared endpoints. They use get_success_data
(lenient) so a broken setup surfaces as a clear "setup failed" error.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_catalog_item_payload,
    create_inventory_unit_payload,
    create_customer_payload,
    create_wallet_adjustment_payload,
    create_subscription_plan_payload,
    create_subscription_payload,
    create_order_payload,
    create_buyback_quote_payload,
)
from .test_users import TEST_USERS, make_customer_headers

CLOCK_DEFAULT = "2026-03-01T00:00:00Z"

_ADMIN = TEST_USERS["admin_headers"]
_WAREHOUSE = TEST_USERS["warehouse_headers"]


# ─── Primitive builders ───────────────────────────────────────────────

def set_clock(iso: str):
    """Set the logical clock (CatalogAdmin only)."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, _ADMIN))


def create_catalog_item(**overrides) -> dict:
    return get_success_data(api_client.create_catalog(create_catalog_item_payload(**overrides), _ADMIN))


def create_inventory_unit(catalog_item_id, **overrides) -> dict:
    return get_success_data(api_client.create_inventory_unit(
        create_inventory_unit_payload(catalog_item_id, **overrides), _ADMIN))


def create_customer(**overrides) -> dict:
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), _ADMIN))


def top_up(customer_id, amount_cents):
    return get_success_data(api_client.create_wallet_adjustment(
        customer_id, create_wallet_adjustment_payload(amount_cents), _ADMIN))


def create_funded_customer(amount_cents, **overrides) -> dict:
    """Onboard a customer and (if amount>0) fund the wallet. Returns the re-read
    customer (so version and wallet_credit_cents reflect the adjustment)."""
    cust = create_customer(**overrides)
    if amount_cents:
        top_up(cust["id"], amount_cents)
        cust = get_success_data(api_client.get_customer(cust["id"], _ADMIN))
    return cust


def get_customer(customer_id) -> dict:
    return get_success_data(api_client.get_customer(customer_id, _ADMIN))


def get_order(order_id) -> dict:
    return get_success_data(api_client.get_order(order_id, _WAREHOUSE))


def get_rental(rental_id) -> dict:
    return get_success_data(api_client.get_rental(rental_id, _WAREHOUSE))


def get_inventory_unit(unit_id) -> dict:
    return get_success_data(api_client.get_inventory_unit(unit_id, _WAREHOUSE))


def get_buyback_quote(quote_id) -> dict:
    return get_success_data(api_client.get_buyback_quote(quote_id, _WAREHOUSE))


# ─── Order / rental lifecycle ─────────────────────────────────────────

def create_rent_order(cat_id, customer, *, term_days=90, desired_start=CLOCK_DEFAULT) -> dict:
    headers = make_customer_headers(customer["id"])
    return get_success_data(api_client.create_order(
        create_order_payload(cat_id, "RENT", rental_term_days=term_days, desired_start_date=desired_start),
        headers))


def setup_paid_confirmed_rental(
    *,
    catalog_overrides=None,
    unit_condition="GOOD",
    topup=50000,
    term_days=90,
    desired_start=CLOCK_DEFAULT,
    start_clock=CLOCK_DEFAULT,
    email="rent@example.com",
):
    """Clock set; catalog + one InventoryUnit + funded customer; a RENT order paid
    and confirmed; the resulting Rental is ACTIVE.

    Returns dict(cat, unit, customer, headers, order, rental).
    """
    set_clock(start_clock)
    cat = create_catalog_item(**(catalog_overrides or {}))
    unit = create_inventory_unit(cat["id"], condition_grade=unit_condition)
    cust = create_funded_customer(topup, email=email)
    headers = make_customer_headers(cust["id"])

    order = get_success_data(api_client.create_order(
        create_order_payload(cat["id"], "RENT", rental_term_days=term_days, desired_start_date=desired_start),
        headers))
    api_client.pay_order(order["id"], headers)
    order = get_success_data(api_client.confirm_order(order["id"], _WAREHOUSE))

    rentals = get_success_data(api_client.list_rentals(_WAREHOUSE, params={"order_id": order["id"]}))
    rental = rentals[0]
    return {"cat": cat, "unit": unit, "customer": cust, "headers": headers,
            "order": order, "rental": rental}


def setup_return_opened(**kwargs):
    """As setup_paid_confirmed_rental, then open a return (Rental -> RETURN_INITIATED,
    ReturnShipment LABEL_ISSUED). Adds return_shipment to the returned dict."""
    ctx = setup_paid_confirmed_rental(**kwargs)
    rs = get_success_data(api_client.return_rental(ctx["rental"]["id"], ctx["headers"]))
    ctx["return_shipment"] = rs
    return ctx


def setup_inspected_rental(
    *,
    reported_condition="GOOD",
    highlight_pct_reported=0,
    is_lost=False,
    inspect_clock=None,
    **kwargs,
):
    """Full rent -> return -> inspect chain. Optionally advances the clock to
    inspect_clock before the inspect call. Adds the inspect response to the dict."""
    ctx = setup_return_opened(**kwargs)
    if inspect_clock is not None:
        set_clock(inspect_clock)
    payload = {
        "reported_condition": reported_condition,
        "highlight_pct_reported": highlight_pct_reported,
        "is_lost": is_lost,
    }
    ctx["inspect_result"] = get_success_data(
        api_client.inspect_return_shipment(ctx["return_shipment"]["id"], payload, _WAREHOUSE))
    return ctx


# ─── Buyback lifecycle ────────────────────────────────────────────────

def create_buyback_quote(cat_id, customer, declared_condition, headers=None) -> dict:
    headers = headers or make_customer_headers(customer["id"])
    return get_success_data(api_client.create_buyback_quote(
        create_buyback_quote_payload(cat_id, declared_condition, customer["version"]), headers))


def setup_accepted_buyback(*, declared_condition="NEW", catalog_overrides=None, email="seller@example.com"):
    """Catalog + customer; a buyback quote is created (declared_condition) and ACCEPTED.
    Returns dict(cat, customer, headers, quote)."""
    cat = create_catalog_item(**(catalog_overrides or {}))
    cust = create_customer(email=email)
    headers = make_customer_headers(cust["id"])
    quote = create_buyback_quote(cat["id"], cust, declared_condition, headers)
    quote = get_success_data(api_client.accept_buyback_quote(quote["id"], headers))
    return {"cat": cat, "customer": cust, "headers": headers, "quote": quote}


def setup_revised_buyback(*, declared_condition="NEW", assessed_condition="GOOD",
                          catalog_overrides=None, email="seller@example.com"):
    """Accepted buyback whose warehouse inspection assessed a DIFFERENT condition,
    landing the quote in REVISED. Returns dict(cat, customer, headers, quote)."""
    ctx = setup_accepted_buyback(declared_condition=declared_condition,
                                 catalog_overrides=catalog_overrides, email=email)
    ctx["quote"] = get_success_data(api_client.inspect_buyback_quote(
        ctx["quote"]["id"], {"assessed_condition": assessed_condition}, _WAREHOUSE))
    return ctx


# ─── Subscriptions ────────────────────────────────────────────────────

def create_plan(**overrides) -> dict:
    return get_success_data(api_client.create_subscription_plan(
        create_subscription_plan_payload(**overrides), _ADMIN))


def setup_active_subscription(
    *,
    tier="STUDY",
    monthly_fee_cents=1499,
    rental_discount_pct=0.05,
    includes_solutions=False,
    term_months=1,
    topup=0,
    start_date=CLOCK_DEFAULT,
    start_clock=CLOCK_DEFAULT,
    email="sub@example.com",
):
    """Clock set; a plan + a customer (optionally funded) with one ACTIVE subscription.
    Returns dict(plan, customer, headers, subscription)."""
    set_clock(start_clock)
    plan = create_plan(tier=tier, monthly_fee_cents=monthly_fee_cents,
                       rental_discount_pct=rental_discount_pct,
                       includes_solutions=includes_solutions, term_months=term_months)
    cust = create_funded_customer(topup, email=email)
    headers = make_customer_headers(cust["id"])
    sub = get_success_data(api_client.create_subscription(
        cust["id"], create_subscription_payload(plan["id"], start_date=start_date), headers))
    return {"plan": plan, "customer": cust, "headers": headers, "subscription": sub}
