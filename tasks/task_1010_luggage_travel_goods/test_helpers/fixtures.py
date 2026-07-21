"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because the test harness restarts the server (fresh, empty DB and a
logical clock reset to 2026-07-01T00:00:00Z) before every individual test.

Helpers use get_success_data() (lenient 2xx validator) so a broken precondition
surfaces as a clear "Setup failed" rather than a confusing assertion later.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS
from . import factories as f

MANAGER = TEST_USERS["manager_headers"]
ASSOCIATE = TEST_USERS["associate_headers"]


# ==========================================================================
# Logical clock
# ==========================================================================
def set_clock(iso: str, api=api_client):
    return get_success_data(api.set_clock(iso, MANAGER))


# ==========================================================================
# Single-entity creators (return the created resource dict)
# ==========================================================================
def new_product(api=api_client, **overrides) -> dict:
    return get_success_data(api.create_product(f.create_product_payload(**overrides), ASSOCIATE))


def new_airline(api=api_client, **overrides) -> dict:
    return get_success_data(api.create_airline(f.create_airline_payload(**overrides), MANAGER))


def new_customer(api=api_client, **overrides) -> dict:
    return get_success_data(api.create_customer(f.create_customer_payload(**overrides), ASSOCIATE))


def new_bench(api=api_client, **overrides) -> dict:
    return get_success_data(api.create_service_bench(f.create_service_bench_payload(**overrides), MANAGER))


def new_station(api=api_client, **overrides) -> dict:
    return get_success_data(api.create_monogram_station(f.create_monogram_station_payload(**overrides), MANAGER))


def new_registration(product_id, customer_id, api=api_client, **overrides) -> dict:
    return get_success_data(
        api.create_registration(f.create_registration_payload(product_id, customer_id, **overrides), ASSOCIATE)
    )


def new_claim(registration_id, expected_version, api=api_client, **overrides) -> dict:
    return get_success_data(
        api.create_claim(f.create_claim_payload(registration_id, expected_version, **overrides), ASSOCIATE)
    )


def new_repair_order(customer_id, product_id, api=api_client, **overrides) -> dict:
    return get_success_data(
        api.create_repair_order(f.create_repair_order_payload(customer_id, product_id, **overrides), ASSOCIATE)
    )


def new_repair_line(repair_order_id, api=api_client, **overrides) -> dict:
    return get_success_data(
        api.create_repair_line(f.create_repair_line_payload(repair_order_id, **overrides), ASSOCIATE)
    )


def new_sales_order(customer_id, api=api_client, **overrides) -> dict:
    return get_success_data(
        api.create_sales_order(f.create_sales_order_payload(customer_id, **overrides), ASSOCIATE)
    )


def new_sales_order_line(sales_order_id, product_id, api=api_client, **overrides) -> dict:
    return get_success_data(
        api.create_sales_order_line(
            f.create_sales_order_line_payload(sales_order_id, product_id, **overrides), ASSOCIATE
        )
    )


def new_trade_in(customer_id, product_id, expected_customer_version, api=api_client, **overrides) -> dict:
    return get_success_data(
        api.create_trade_in(
            f.create_trade_in_payload(customer_id, product_id, expected_customer_version, **overrides), ASSOCIATE
        )
    )


def new_special_order(customer_id, product_id, api=api_client, **overrides) -> dict:
    return get_success_data(
        api.create_special_order(f.create_special_order_payload(customer_id, product_id, **overrides), ASSOCIATE)
    )


def new_recall_notice(product_id, api=api_client, **overrides) -> dict:
    return get_success_data(
        api.create_recall_notice(f.create_recall_notice_payload(product_id, **overrides), MANAGER)
    )


# ==========================================================================
# Refresh helpers
# ==========================================================================
def get_product(product_id, api=api_client) -> dict:
    return get_success_data(api.get_product(product_id, MANAGER))


def get_customer(customer_id, api=api_client) -> dict:
    return get_success_data(api.get_customer(customer_id, MANAGER))


def get_registration(registration_id, api=api_client) -> dict:
    return get_success_data(api.get_registration(registration_id, MANAGER))


def get_claim(claim_id, api=api_client) -> dict:
    return get_success_data(api.get_claim(claim_id, MANAGER))


def get_repair_order(repair_order_id, api=api_client) -> dict:
    return get_success_data(api.get_repair_order(repair_order_id, MANAGER))


def get_sales_order(sales_order_id, api=api_client) -> dict:
    return get_success_data(api.get_sales_order(sales_order_id, MANAGER))


def get_sales_order_line(line_id, api=api_client) -> dict:
    return get_success_data(api.get_sales_order_line(line_id, MANAGER))


def get_trade_in(trade_in_id, api=api_client) -> dict:
    return get_success_data(api.get_trade_in(trade_in_id, MANAGER))


# ==========================================================================
# Composite: warranty claim progression
# ==========================================================================
def reviewed_claim(api=api_client, warranty_months=24, purchase_date="2026-06-01T00:00:00Z"):
    """Product + Customer + ACTIVE registration + a claim advanced to UNDER_REVIEW.
    Returns (product, customer, registration, claim)."""
    product = new_product(api, warranty_months=warranty_months)
    customer = new_customer(api)
    reg = new_registration(product["id"], customer["id"], api, purchase_date=purchase_date)
    claim = new_claim(reg["id"], reg["version"], api)
    get_success_data(api.review_claim(claim["id"], ASSOCIATE))
    return product, customer, get_registration(reg["id"], api), get_claim(claim["id"], api)


def resolved_repair_claim(api=api_client):
    """Product + Customer + registration + a claim resolved with resolution REPAIR.
    Returns (product, customer, registration, claim)."""
    product, customer, reg, claim = reviewed_claim(api)
    get_success_data(api.resolve_claim(claim["id"], "REPAIR", MANAGER))
    return product, customer, reg, get_claim(claim["id"], api)


# ==========================================================================
# Composite: repair order progression
# ==========================================================================
def repair_order_with_lines(customer_id, product_id, lines, claim_id=None, api=api_client):
    """Create an INTAKE repair order and attach the given repair lines.
    `lines` is a list of override dicts for create_repair_line_payload.
    Returns (repair_order, [line, ...])."""
    over = {} if claim_id is None else {"claim_id": claim_id}
    ro = new_repair_order(customer_id, product_id, api, **over)
    created = [new_repair_line(ro["id"], api, **ln) for ln in lines]
    return ro, created


def quoted_repair(customer_id, product_id, lines, claim_id=None, api=api_client):
    ro, created = repair_order_with_lines(customer_id, product_id, lines, claim_id, api)
    get_success_data(api.quote_repair_order(ro["id"], MANAGER))
    return get_repair_order(ro["id"], api), created


def approved_repair(customer_id, product_id, lines, api=api_client):
    ro, created = quoted_repair(customer_id, product_id, lines, None, api)
    get_success_data(api.approve_repair_order(ro["id"], MANAGER))
    return get_repair_order(ro["id"], api), created


def scheduled_repair(customer_id, product_id, bench_id, bench_start, bench_end,
                     lines=None, api=api_client):
    if lines is None:
        lines = [{"repair_type": "WHEEL", "labor_hours": 1, "complexity": "STANDARD", "parts_cost_cents": 500}]
    ro, _ = approved_repair(customer_id, product_id, lines, api)
    get_success_data(api.schedule_repair_order(
        ro["id"], {"bench_id": bench_id, "bench_start": bench_start, "bench_end": bench_end}, ASSOCIATE))
    return get_repair_order(ro["id"], api)


def in_repair_order(customer_id, product_id, bench_id, bench_start, bench_end, api=api_client):
    ro = scheduled_repair(customer_id, product_id, bench_id, bench_start, bench_end, api=api)
    get_success_data(api.start_repair_order(ro["id"], ASSOCIATE))
    return get_repair_order(ro["id"], api)


# ==========================================================================
# Composite: sales order progression
# ==========================================================================
def sales_order_with_line(customer_id, product_id, line_overrides=None, order_overrides=None, api=api_client):
    """PENDING sales order with a single line. Returns (order, line)."""
    order = new_sales_order(customer_id, api, **(order_overrides or {}))
    line = new_sales_order_line(order["id"], product_id, api, **(line_overrides or {}))
    return get_sales_order(order["id"], api), line


def captured_order_with_line(customer_id, product_id, unit_price_cents=10000, qty=1, api=api_client):
    """A sales order with one line, captured. Returns the captured order dict."""
    order, _ = sales_order_with_line(
        customer_id, product_id, line_overrides={"unit_price_cents": unit_price_cents, "qty": qty}, api=api)
    get_success_data(api.capture_sales_order(order["id"], ASSOCIATE))
    return get_sales_order(order["id"], api)


def raise_customer_to_spend(customer_id, product_id, net_line_cents, api=api_client):
    """Push a customer's lifetime spend upward by capturing a fresh order whose
    single BRONZE-priced line nets exactly `net_line_cents` (no discount at
    BRONZE). Returns the refreshed customer dict."""
    captured_order_with_line(customer_id, product_id, unit_price_cents=net_line_cents, qty=1, api=api)
    return get_customer(customer_id, api)
