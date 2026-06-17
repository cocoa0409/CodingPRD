"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures surface as clear
"Setup failed" errors rather than confusing assertion failures.

The dominant preamble in this domain is:
  price-tier -> part (+ receive-stock) -> account -> sales-order -> order-line
  -> allocate -> ship -> invoice -> pay,
with branches into core returns, warranty claims, reorder lifecycle, and hotshot
delivery runs. These helpers expose every value tests need to control via keyword
arguments and default the rest.

All four roles use opaque identity (see test_users.py), so shared role headers are
used throughout; no ownership threading is required.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_part_payload, create_vehicle_payload, create_fitment_payload,
    create_cross_reference_payload, create_price_tier_payload, create_account_payload,
    create_sales_order_payload, create_order_line_payload, allocate_payload, ship_payload,
    receive_stock_payload, create_core_return_payload, create_warranty_claim_payload,
    create_reorder_request_payload, receive_reorder_payload, create_driver_payload,
    create_bay_payload, create_delivery_run_payload,
)
from .test_users import TEST_USERS

CLERK = TEST_USERS["counter_clerk_headers"]
REP = TEST_USERS["wholesale_rep_headers"]
INV = TEST_USERS["inventory_manager_headers"]
ADMIN = TEST_USERS["warranty_admin_headers"]

# Standard JOBBER tier used throughout the difficulty/corner chains.
JOBBER = {"name": "JOBBER", "discount_pct": 0.30, "core_discount_pct": 0.10, "min_margin_pct": 0.20}

_sku_counter = [0]


def unique_sku(prefix="SKU"):
    """Each call returns a fresh, unique SKU within a test run."""
    _sku_counter[0] += 1
    return f"{prefix}-{_sku_counter[0]}"


# ─── Atomic builders ────────────────────────────────────────────────────────

def create_price_tier(name="JOBBER", discount_pct=0.30, core_discount_pct=0.10,
                      min_margin_pct=0.20):
    """Create a price tier. Returns the tier dict."""
    return get_success_data(api_client.create_price_tier(
        create_price_tier_payload(name=name, discount_pct=discount_pct,
                                  core_discount_pct=core_discount_pct,
                                  min_margin_pct=min_margin_pct), INV))


def create_jobber_tier():
    return create_price_tier(**JOBBER)


def create_part(sku=None, description="Test part", list_price_cents=20000,
                cost_cents=9000, **overrides):
    """Create a part with a unique SKU by default. Returns the part dict."""
    if sku is None:
        sku = unique_sku("PART")
    return get_success_data(api_client.create_part(
        create_part_payload(sku=sku, description=description,
                            list_price_cents=list_price_cents,
                            cost_cents=cost_cents, **overrides), INV))


def stock_part(part_id, qty):
    """Ad-hoc receive `qty` units into a part. Returns the updated part."""
    return get_success_data(api_client.receive_stock(
        part_id, receive_stock_payload(qty), INV))


def create_stocked_part(qty=5, **part_overrides):
    """Create a stockable part and receive `qty` units. Returns the part (post-receipt)."""
    part = create_part(**part_overrides)
    if qty:
        part = stock_part(part["id"], qty)
    return part


def create_account(price_tier_id, name="Test Account", account_type="WHOLESALE",
                   credit_limit_cents=1_000_000, **overrides):
    """Create an account. credit_limit_cents defaults high so credit never blocks
    unless a test explicitly overrides it. Returns the account dict."""
    payload_kwargs = dict(name=name, account_type=account_type,
                          price_tier_id=price_tier_id, **overrides)
    if account_type == "WHOLESALE":
        payload_kwargs.setdefault("credit_limit_cents", credit_limit_cents)
    return get_success_data(api_client.create_account(
        create_account_payload(**payload_kwargs), REP))


def create_vehicle(year=2020, make="TOYOTA", model="CAMRY", **overrides):
    return get_success_data(api_client.create_vehicle(
        create_vehicle_payload(year=year, make=make, model=model, **overrides), INV))


def create_fitment(part_id, vehicle_id, **overrides):
    return get_success_data(api_client.create_fitment(
        create_fitment_payload(part_id, vehicle_id, **overrides), INV))


def create_cross_reference(part_id, interchange_part_id, **overrides):
    return get_success_data(api_client.create_cross_reference(
        create_cross_reference_payload(part_id, interchange_part_id, **overrides), INV))


def create_open_order(account_id, channel="WHOLESALE", hotshot_requested=False, as_role=REP):
    """Open a sales order. Returns the order dict (OPEN/UNBILLED)."""
    payload = create_sales_order_payload(account_id, channel=channel)
    if hotshot_requested:
        payload["hotshot_requested"] = True
    return get_success_data(api_client.create_sales_order(payload, as_role))


def add_line(order_id, part_id, qty=1, as_role=REP):
    """Add an order line. Returns the line dict."""
    return get_success_data(api_client.create_order_line(
        create_order_line_payload(order_id, part_id, qty), as_role))


def current_version(order_id, as_role=REP):
    """Read the current version of a sales order."""
    return get_success_data(api_client.get_sales_order(order_id, as_role))["version"]


def allocate(order_id, expected_version=None, as_role=REP):
    """Allocate an order. If expected_version omitted, reads the live version first.
    Returns the allocated order dict."""
    if expected_version is None:
        expected_version = current_version(order_id, as_role)
    return get_success_data(api_client.allocate_order(
        order_id, allocate_payload(expected_version), as_role))


def ship(order_id, expected_version=None, as_role=REP):
    """Ship an allocated order. If expected_version omitted, reads the live version.
    Returns the shipped order dict."""
    if expected_version is None:
        expected_version = current_version(order_id, as_role)
    return get_success_data(api_client.ship_order(
        order_id, ship_payload(expected_version), as_role))


def invoice(order_id, as_role=REP):
    return get_success_data(api_client.invoice_order(order_id, as_role))


def pay(order_id, as_role=REP):
    return get_success_data(api_client.pay_order(order_id, as_role))


# ─── Tier 2: hierarchies ─────────────────────────────────────────────────────

def setup_wholesale_context(stock_qty=5, part_overrides=None, tier=None):
    """Active JOBBER tier + a stocked wholesale part + a wholesale account.

    Returns (tier, part, account). part_overrides lets callers control the part's
    pricing/rebuildable/stockable flags; stock_qty controls the on-hand stock.
    """
    tier = tier or create_jobber_tier()
    part = create_stocked_part(qty=stock_qty, **(part_overrides or {}))
    account = create_account(tier["id"], name="WS Shop", account_type="WHOLESALE")
    return tier, part, account


def setup_open_wholesale_order_with_line(qty=1, stock_qty=5, part_overrides=None):
    """Active tier + stocked part + wholesale account + OPEN order + one line.

    Returns (part, account, order, line).
    """
    _, part, account = setup_wholesale_context(stock_qty=stock_qty,
                                               part_overrides=part_overrides)
    order = create_open_order(account["id"], channel="WHOLESALE")
    line = add_line(order["id"], part["id"], qty)
    return part, account, order, line


# ─── Tier 3: lifecycle shortcuts ─────────────────────────────────────────────

def setup_allocated_wholesale_order(qty=1, stock_qty=5, part_overrides=None):
    """OPEN order with one line, then allocated.

    Returns (part, account, order_after_allocate, line). The order dict is the
    post-allocate snapshot (ALLOCATED, version bumped).
    """
    part, account, order, line = setup_open_wholesale_order_with_line(
        qty=qty, stock_qty=stock_qty, part_overrides=part_overrides)
    order = allocate(order["id"])
    return part, account, order, line


def setup_shipped_wholesale_order(qty=1, stock_qty=5, part_overrides=None):
    """Order driven all the way to SHIPPED.

    Returns (part, account, order_after_ship, line).
    """
    part, account, order, line = setup_allocated_wholesale_order(
        qty=qty, stock_qty=stock_qty, part_overrides=part_overrides)
    order = ship(order["id"])
    return part, account, order, line


def setup_invoiced_wholesale_order(qty=1, stock_qty=5, part_overrides=None):
    """Order driven to SHIPPED then INVOICED (A/R charged).

    Returns (part, account, order_after_invoice, line).
    """
    part, account, order, line = setup_shipped_wholesale_order(
        qty=qty, stock_qty=stock_qty, part_overrides=part_overrides)
    order = invoice(order["id"])
    return part, account, order, line


# Standard rebuildable caliper used by core-return and dual-variant claim chains.
CALIPER = dict(description="Brake caliper", list_price_cents=20000, cost_cents=9000,
               core_charge_cents=6000, is_rebuildable=True, warranty_days=90,
               stockable=True, reorder_point=0, reorder_qty=0)


def setup_shipped_caliper_order(qty=1, stock_qty=3, warranty_days=90):
    """Shipped wholesale order for one rebuildable caliper line (cores opened at ship).

    Caliper: list 20000, cost 9000, core 6000 on the JOBBER tier ->
    unit_merch 14000, unit_core 5400.

    Returns (part, account, order, line).
    """
    overrides = dict(CALIPER)
    overrides["warranty_days"] = warranty_days
    return setup_shipped_wholesale_order(qty=qty, stock_qty=stock_qty,
                                         part_overrides=overrides)


def setup_pending_core_return(qty=1, line_qty=1, warranty_days=90):
    """Shipped+invoiced caliper line with a PENDING_INSPECTION core return for `qty`.

    Returns (part, account, order, line, core_return).
    """
    overrides = dict(CALIPER)
    overrides["warranty_days"] = warranty_days
    part, account, order, line = setup_shipped_wholesale_order(
        qty=line_qty, stock_qty=3, part_overrides=overrides)
    order = invoice(order["id"])
    cr = get_success_data(api_client.create_core_return(
        create_core_return_payload(line["id"], qty), REP))
    return part, account, order, line, cr


def setup_warranty_claim(resolution="REFUND", qty=1, line_qty=1, warranty_days=365,
                         restock_defective=None, escalate=True, invoiced=True,
                         stock_qty=5):
    """Shipped (optionally invoiced) line with a warranty claim, optionally escalated
    to UNDER_REVIEW.

    Returns (part, account, order, line, claim).
    """
    overrides = dict(CALIPER)
    overrides["warranty_days"] = warranty_days
    part, account, order, line = setup_shipped_wholesale_order(
        qty=line_qty, stock_qty=stock_qty, part_overrides=overrides)
    if invoiced:
        order = invoice(order["id"])
    claim_overrides = {"resolution": resolution}
    if restock_defective is not None:
        claim_overrides["restock_defective"] = restock_defective
    claim = get_success_data(api_client.create_warranty_claim(
        create_warranty_claim_payload(line["id"], qty=qty, reason="defective",
                                      **claim_overrides), REP))
    if escalate:
        claim = get_success_data(api_client.start_review_claim(claim["id"], ADMIN))
    return part, account, order, line, claim


# ─── Reorder lifecycle ───────────────────────────────────────────────────────

def create_reorder(part_id, as_role=INV):
    """Manually create a SUGGESTED reorder request. Returns the reorder dict."""
    return get_success_data(api_client.create_reorder_request(
        create_reorder_request_payload(part_id), as_role))


def setup_ordered_reorder(reorder_qty=10, reorder_point=2):
    """Part with a manually created reorder request placed (ORDERED).

    Returns (part, reorder).
    """
    part = create_part(stockable=True, reorder_point=reorder_point, reorder_qty=reorder_qty)
    ro = create_reorder(part["id"])
    ro = get_success_data(api_client.place_reorder_request(ro["id"], INV))
    return part, ro


# ─── Hotshot delivery building blocks ────────────────────────────────────────

def create_driver(name="Driver", turnaround_min=0):
    return get_success_data(api_client.create_driver(
        create_driver_payload(name=name, turnaround_min=turnaround_min), REP))


def create_bay(code=None):
    if code is None:
        code = unique_sku("BAY")
    return get_success_data(api_client.create_bay(create_bay_payload(code=code), REP))


def setup_allocated_hotshot_order(qty=1, special=True):
    """Allocated wholesale hotshot order with one (special-order by default) line.

    special=True uses a non-stockable part (always special-order). Returns
    (part, account, order_after_allocate, line).
    """
    tier = create_jobber_tier()
    if special:
        part = create_part(description="Special order part", list_price_cents=7000,
                           cost_cents=3000, stockable=False, reorder_point=0, reorder_qty=0)
    else:
        part = create_stocked_part(qty=5, description="Stocked", list_price_cents=5000,
                                   cost_cents=2000, stockable=True,
                                   reorder_point=0, reorder_qty=0)
    account = create_account(tier["id"], name="WS Shop", account_type="WHOLESALE")
    order = create_open_order(account["id"], channel="WHOLESALE", hotshot_requested=True)
    line = add_line(order["id"], part["id"], qty)
    order = allocate(order["id"])
    return part, account, order, line


def schedule_run(order_id, driver_id, bay_id, window_start_min, window_end_min, as_role=REP):
    """Schedule a delivery run. Returns the run dict (SCHEDULED)."""
    return get_success_data(api_client.create_delivery_run(
        create_delivery_run_payload(order_id, driver_id, bay_id,
                                    window_start_min, window_end_min), as_role))
