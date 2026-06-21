"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the system to be walked through 5-15 API calls to
reach the testable state (a roasted lot exists only after plan -> start -> drop ->
complete; an issued invoice only after order -> fulfill -> ship -> invoice). These
helpers encapsulate those preambles so tests focus on assertions.

All helpers use get_success_data() (lenient validator) so setup failures surface as
clear "Setup failed" errors. Every helper builds its preconditions from scratch — the
server database is empty at the start of every test.

Identity threading: WholesaleBuyer is entity_backed; ownership-gated buyer calls must
use make_buyer_headers(account_id). SalesRep/RoasterStaff are opaque operators.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_price_tier_payload, create_account_payload, create_roast_profile_payload,
    create_product_payload, create_green_lot_payload, create_roast_batch_payload,
    start_roast_batch_payload, complete_roast_batch_payload, create_order_payload,
    order_line, create_fulfillment_payload, create_standing_order_payload,
    create_sample_request_payload, review_sample_request_payload, clock_payload,
)
from .test_users import TEST_USERS

ROASTER = TEST_USERS["roaster_headers"]
SALES = TEST_USERS["sales_headers"]


# ─── Tier 0: clock control ──────────────────────────────────────────────────

def clock_set(iso: str):
    """Pin the simulated clock to an instant (no aging)."""
    return get_success_data(api_client.clock_set(clock_payload(iso), ROASTER))


def clock_advance(iso: str):
    """Advance the clock and run the aging sweep."""
    return get_success_data(api_client.clock_advance(clock_payload(iso), SALES))


# ─── Tier 1: single-entity creators ─────────────────────────────────────────

def create_tier(**overrides):
    return get_success_data(api_client.create_price_tier(
        create_price_tier_payload(**overrides), SALES))


def create_account(price_tier_id=None, **overrides):
    if price_tier_id is None:
        price_tier_id = create_tier()["id"]
    return get_success_data(api_client.create_account(
        create_account_payload(price_tier_id, **overrides), SALES))


def create_profile(**overrides):
    return get_success_data(api_client.create_roast_profile(
        create_roast_profile_payload(**overrides), ROASTER))


def create_product(roast_profile_id=None, **overrides):
    if roast_profile_id is None:
        roast_profile_id = create_profile()["id"]
    return get_success_data(api_client.create_product(
        create_product_payload(roast_profile_id, **overrides), ROASTER))


def create_green_lot(**overrides):
    return get_success_data(api_client.create_green_lot(
        create_green_lot_payload(**overrides), ROASTER))


# ─── Tier 2: catalog + account bundle ───────────────────────────────────────

def setup_catalog(tier_overrides=None, profile_overrides=None,
                  product_overrides=None, account_overrides=None):
    """Tier + account + profile + product. Returns dict of all four entities.

    The common commercial preamble shared by nearly every test that places an order.
    """
    tier = create_tier(**(tier_overrides or {}))
    account = create_account(tier["id"], **(account_overrides or {}))
    profile = create_profile(**(profile_overrides or {}))
    product = create_product(profile["id"], **(product_overrides or {}))
    return {"tier": tier, "account": account, "profile": profile, "product": product}


# ─── Tier 3: roast lifecycle -> roasted lot ─────────────────────────────────

def create_planned_batch(green_lot_id, product_id, planned_green_kg=20, **overrides):
    """Plan a batch against a freshly-read green-lot version. Returns the batch."""
    gl = get_success_data(api_client.get_green_lot(green_lot_id, ROASTER))
    payload = create_roast_batch_payload(
        green_lot_id, product_id, gl["version"],
        planned_green_kg=planned_green_kg, **overrides)
    return get_success_data(api_client.create_roast_batch(payload, ROASTER))


def produce_roasted_lot(product_id, green_lot_id=None, actual_green_kg=30,
                        actual_roasted_kg=25, planned_green_kg=None):
    """Drive a batch PLANNED -> ROASTING -> COOLING -> COMPLETED, producing a roasted lot.

    Returns (batch, roasted_lot). If green_lot_id is None a 100kg lot is created.
    """
    if green_lot_id is None:
        green_lot_id = create_green_lot(received_kg=200, par_level_kg=5)["id"]
    if planned_green_kg is None:
        planned_green_kg = actual_green_kg
    batch = create_planned_batch(green_lot_id, product_id, planned_green_kg=planned_green_kg)
    api_client.start_roast_batch(batch["id"], start_roast_batch_payload(actual_green_kg), ROASTER)
    api_client.drop_roast_batch(batch["id"], ROASTER)
    batch = get_success_data(api_client.complete_roast_batch(
        batch["id"], complete_roast_batch_payload(actual_roasted_kg), ROASTER))
    lots, _ = _list_lots(batch["id"])
    return batch, lots[0]


def _list_lots(batch_id):
    res = api_client.list_batch_roasted_lots(batch_id, ROASTER)
    data = get_success_data(res)
    # get_success_data on an array endpoint returns the data list directly.
    return data, None


def cooling_batch(product_id, green_lot_id=None, actual_green_kg=20, planned_green_kg=20):
    """Drive a batch to COOLING (planned -> started -> dropped). Returns the batch."""
    if green_lot_id is None:
        green_lot_id = create_green_lot(received_kg=100, par_level_kg=5)["id"]
    batch = create_planned_batch(green_lot_id, product_id, planned_green_kg=planned_green_kg)
    api_client.start_roast_batch(batch["id"], start_roast_batch_payload(actual_green_kg), ROASTER)
    batch = get_success_data(api_client.drop_roast_batch(batch["id"], ROASTER))
    return batch


# ─── Tier 4: order / fulfillment / invoice lifecycle ────────────────────────

def place_order(account_id, lines, headers=None):
    """Place an order. lines is a list of order_line(...) dicts. Returns the order."""
    return get_success_data(api_client.create_order(
        account_id, create_order_payload(lines), headers or SALES))


def reserve_fulfillment(order_id, product_id, roasted_lot_id, allocated_kg):
    """Reserve a fulfillment against a freshly-read roasted-lot version. Returns it."""
    rl = get_success_data(api_client.get_roasted_lot(roasted_lot_id, SALES))
    payload = create_fulfillment_payload(
        product_id, roasted_lot_id, allocated_kg, rl["version"])
    return get_success_data(api_client.create_fulfillment(order_id, payload, SALES))


def ship_fulfillment(fulfillment_id):
    return get_success_data(api_client.ship_fulfillment(fulfillment_id, ROASTER))


def setup_shipped_order(account_id, product_id, roasted_lot_id, qty_kg=10,
                        allocated_kg=None):
    """Place an order, reserve a fulfillment, and ship it.

    Returns (order, fulfillment). After this the order has at least one SHIPPED
    fulfillment, so it is invoiceable.
    """
    if allocated_kg is None:
        allocated_kg = qty_kg
    order = place_order(account_id, [order_line(product_id, qty_kg)])
    ful = reserve_fulfillment(order["id"], product_id, roasted_lot_id, allocated_kg)
    ful = ship_fulfillment(ful["id"])
    order = get_success_data(api_client.get_order(order["id"], SALES))
    return order, ful


def issue_invoice(order_id):
    """Issue an invoice for a (partially) fulfilled order. Returns the invoice."""
    return get_success_data(api_client.invoice_order(order_id, SALES))


def setup_issued_invoice(qty_kg=10, base_price_cents_per_kg=2000, discount_bps=0,
                         net_terms_days=30, credit_limit_cents=1_000_000,
                         freshness_max_days=60, freshness_window_days=60):
    """Full chain to an ISSUED invoice on an ACTIVE account.

    plan -> start -> drop -> complete (roasted lot) -> order -> fulfill -> ship -> invoice.
    Returns dict: tier, account, profile, product, batch, roasted_lot, order, fulfillment, invoice.
    """
    cat = setup_catalog(
        tier_overrides={"discount_bps": discount_bps, "freshness_max_days": freshness_max_days},
        account_overrides={"net_terms_days": net_terms_days,
                           "credit_limit_cents": credit_limit_cents},
        product_overrides={"base_price_cents_per_kg": base_price_cents_per_kg,
                           "freshness_window_days": freshness_window_days},
    )
    batch, lot = produce_roasted_lot(cat["product"]["id"], actual_green_kg=qty_kg + 20,
                                     actual_roasted_kg=qty_kg + 15)
    order, ful = setup_shipped_order(cat["account"]["id"], cat["product"]["id"],
                                     lot["id"], qty_kg=qty_kg)
    invoice = issue_invoice(order["id"])
    return {**cat, "batch": batch, "roasted_lot": lot, "order": order,
            "fulfillment": ful, "invoice": invoice}
