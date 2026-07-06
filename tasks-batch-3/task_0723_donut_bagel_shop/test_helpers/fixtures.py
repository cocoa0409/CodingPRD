"""Composite setup helpers.

These encapsulate the multi-step preambles that the difficulty/corner design
recipes share, so test bodies can focus on the trigger + assertions. The test
harness restarts the server (empty DB) before every test, so each helper builds
its preconditions from scratch using only PRD-declared endpoints.

All setup calls go through get_success_data() (lenient) so a setup break surfaces
as a clear "Setup failed" rather than a confusing assertion error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS
from . import factories as F

ADMIN = TEST_USERS["shop_admin_headers"]
BAKER = TEST_USERS["bake_manager_headers"]
CASHIER = TEST_USERS["cashier_headers"]
DRIVER = TEST_USERS["route_driver_headers"]


# ---------------------------------------------------------------------------
# Primitive creators
# ---------------------------------------------------------------------------
def create_product(spec="GLAZED", **overrides) -> dict:
    resp = api_client.create_product(F.create_product_payload(spec, **overrides), ADMIN)
    return get_success_data(resp)


def create_production_day(**overrides) -> dict:
    resp = api_client.create_production_day(F.create_production_day_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_loyalty_account(**overrides) -> dict:
    resp = api_client.create_loyalty_account(F.create_loyalty_account_payload(**overrides), CASHIER)
    return get_success_data(resp)


def create_wholesale_account(**overrides) -> dict:
    resp = api_client.create_wholesale_account(F.create_wholesale_account_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_standing_order(account_id, line_items, delivery_dow=0) -> dict:
    resp = api_client.create_standing_order(
        F.create_standing_order_payload(account_id, line_items, delivery_dow), ADMIN)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: ProductionDay state progression with batches
# ---------------------------------------------------------------------------
def create_planned_batch(day_id, product_id, par_qty=30) -> dict:
    resp = api_client.create_bake_batch(
        day_id, F.create_bake_batch_payload(product_id, par_qty), BAKER)
    return get_success_data(resp)


def setup_selling_day_with_baked_batch(product_spec="GLAZED", par_qty=60, baked_qty=None):
    """Active SELLING day with one BAKED batch of the given product.

    Returns (day, product, batch). baked_qty defaults to par_qty.
    """
    if baked_qty is None:
        baked_qty = par_qty
    product = create_product(product_spec)
    day = create_production_day()
    batch = create_planned_batch(day["id"], product["id"], par_qty)
    get_success_data(api_client.start_baking(day["id"], BAKER))
    batch = get_success_data(
        api_client.bake_batch(day["id"], batch["id"], F.bake_payload(baked_qty), BAKER))
    get_success_data(api_client.open_sales(day["id"], BAKER))
    return day, product, batch


def setup_baking_day_with_planned_batch(product_spec="GLAZED", par_qty=30):
    """Day in BAKING with one still-PLANNED batch. Returns (day, product, batch)."""
    product = create_product(product_spec)
    day = create_production_day()
    batch = create_planned_batch(day["id"], product["id"], par_qty)
    get_success_data(api_client.start_baking(day["id"], BAKER))
    return day, product, batch


def setup_open_day_with_planned_batch(product_spec="GLAZED", par_qty=30):
    """Day still OPEN with one PLANNED batch. Returns (day, product, batch)."""
    product = create_product(product_spec)
    day = create_production_day()
    batch = create_planned_batch(day["id"], product["id"], par_qty)
    return day, product, batch


# ---------------------------------------------------------------------------
# Tier 2/3: Retail order helpers
# ---------------------------------------------------------------------------
def create_cart(day_id, line_items, loyalty_account_id=None, redeem_reward=False) -> dict:
    resp = api_client.create_retail_order(
        day_id,
        F.create_retail_order_payload(line_items, loyalty_account_id, redeem_reward),
        CASHIER)
    return get_success_data(resp)


def create_paid_order(day_id, line_items, loyalty_account_id=None, redeem_reward=False) -> dict:
    order = create_cart(day_id, line_items, loyalty_account_id, redeem_reward)
    return get_success_data(api_client.pay_retail_order(day_id, order["id"], CASHIER))


# ---------------------------------------------------------------------------
# Tier 4: Loyalty accumulation
# ---------------------------------------------------------------------------
def setup_loyalty_at_nine_punches(par_qty=120):
    """SELLING day with GLAZED stock and a loyalty account driven to punch_count 9
    by one prior PAID order of 108 GLAZED (9 dozens). Returns (day, product, batch, loyalty).
    """
    day, product, batch = setup_selling_day_with_baked_batch("GLAZED", par_qty=par_qty)
    loyalty = create_loyalty_account()
    create_paid_order(day["id"],
                      [F.line_item(product["id"], 108, marked_down=False)],
                      loyalty_account_id=loyalty["id"])
    return day, product, batch, loyalty


# ---------------------------------------------------------------------------
# Wholesale: standing order, delivery progression, ledger
# ---------------------------------------------------------------------------
def setup_account_with_standing_order(line_items, discount_pct=0.15,
                                      credit_limit_cents=100000, delivery_dow=3):
    """Active account + active standing order. Returns (account, standing_order, products_by_sku).
    `line_items` is a list of (sku, qty) tuples; the products are created here.
    """
    products = {}
    so_lines = []
    for sku, qty in line_items:
        if sku not in products:
            products[sku] = create_product(sku)
        so_lines.append(F.wholesale_line(products[sku]["id"], qty))
    account = create_wholesale_account(discount_pct=discount_pct,
                                       credit_limit_cents=credit_limit_cents)
    so = create_standing_order(account["id"], so_lines, delivery_dow)
    return account, so, products


def schedule_delivery(day_id, standing_order_id, start, end, headers=None) -> dict:
    headers = headers or ADMIN
    resp = api_client.create_wholesale_delivery(
        day_id, F.create_wholesale_delivery_payload(standing_order_id, start, end), headers)
    return get_success_data(resp)


def setup_delivered_delivery(line_items, discount_pct=0.15, credit_limit_cents=100000,
                            start="2027-06-01T08:00:00Z", end="2027-06-01T09:00:00Z"):
    """Account + standing order + a DELIVERED delivery on a fresh day.
    Returns (account, standing_order, day, delivery).
    """
    account, so, _products = setup_account_with_standing_order(
        line_items, discount_pct=discount_pct, credit_limit_cents=credit_limit_cents)
    day = create_production_day()
    delivery = schedule_delivery(day["id"], so["id"], start, end)
    get_success_data(api_client.pick_delivery(day["id"], delivery["id"], DRIVER))
    delivery = get_success_data(api_client.deliver_delivery(day["id"], delivery["id"], DRIVER))
    return account, so, day, delivery


def setup_invoiced_delivery(line_items, discount_pct=0.15, credit_limit_cents=100000):
    """Account + standing order + an INVOICED delivery. Returns (account, so, day, delivery)."""
    account, so, day, delivery = setup_delivered_delivery(
        line_items, discount_pct=discount_pct, credit_limit_cents=credit_limit_cents)
    delivery = get_success_data(api_client.invoice_delivery(day["id"], delivery["id"], ADMIN))
    return account, so, day, delivery


# ---------------------------------------------------------------------------
# Pre-orders / catering
# ---------------------------------------------------------------------------
def create_pre_order(account_id, day_id, start, end, line_items, headers=None) -> dict:
    headers = headers or ADMIN
    resp = api_client.create_pre_order(
        F.create_pre_order_payload(account_id, day_id, start, end, line_items), headers)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 5: Reconcile-ready / reconciled days
# ---------------------------------------------------------------------------
def setup_cutoff_day_one_swept_batch(product_spec="GLAZED", par_qty=10, baked_qty=10):
    """Day in CUTOFF with one SWEPT batch, ready to reconcile.
    Returns (day, product, batch).
    """
    day, product, batch = setup_selling_day_with_baked_batch(
        product_spec, par_qty=par_qty, baked_qty=baked_qty)
    get_success_data(api_client.sweep_batch(day["id"], batch["id"], BAKER))
    get_success_data(api_client.close_cutoff(day["id"], ADMIN))
    return day, product, batch


def reconcile(day_id, headers=None):
    """Read current version, then reconcile with it. Returns the reconcile response."""
    headers = headers or BAKER
    day = get_success_data(api_client.get_production_day(day_id, headers))
    return api_client.reconcile_day(
        day_id, {"expected_production_day_version": day["version"]}, headers)


def setup_reconciled_day(product_spec="GLAZED", par_qty=10, baked_qty=10):
    """A fully RECONCILED day. Returns (day, product, batch)."""
    day, product, batch = setup_cutoff_day_one_swept_batch(product_spec, par_qty, baked_qty)
    get_success_data(reconcile(day["id"]))
    return day, product, batch
