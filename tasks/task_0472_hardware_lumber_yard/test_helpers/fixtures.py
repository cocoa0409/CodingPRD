"""Composite setup helpers for multi-step test prerequisites.

Every test runs against a freshly-restarted, empty server, so every fixture
builds its preconditions from scratch using only PRD-declared endpoints.

Uses get_success_data() (lenient validator) for setup calls so a setup failure
surfaces as a clear "Setup failed" error instead of a confusing assertion
failure deep inside a test.

Identity threading: the Contractor role is entity-backed. After a fixture
creates a ContractorAccount, any Contractor-acting call uses
make_contractor_headers(account["id"]) so the ownership gate sees the real id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_vendor_payload, create_product_payload,
    create_contractor_account_payload, create_sales_order_payload,
    create_order_line_payload, create_rental_asset_payload,
    create_rental_agreement_payload, create_service_station_payload,
    create_service_ticket_payload, create_special_order_payload,
    create_purchase_order_payload,
)
from .test_users import (
    SALES, RENTAL, ACCOUNTS, INVENTORY, make_contractor_headers,
)


# ─── Catalog primitives ──────────────────────────────────────────────────

def create_vendor(**overrides):
    """Create an ACTIVE vendor. Returns the vendor dict."""
    res = api_client.create_vendor(create_vendor_payload(**overrides), INVENTORY)
    return get_success_data(res)


def create_product(vendor_id=None, on_hand=0, **overrides):
    """Create a product (optionally under a fresh vendor) and optionally seed
    its on_hand via adjust-stock. Returns the latest product dict."""
    if vendor_id is None:
        vendor_id = create_vendor()["id"]
    res = api_client.create_product(
        create_product_payload(vendor_id, **overrides), INVENTORY)
    product = get_success_data(res)
    if on_hand:
        adj = api_client.adjust_stock(product["id"], {"delta": on_hand}, INVENTORY)
        product = get_success_data(adj)
    return product


def create_account(**overrides):
    """Open an ACTIVE contractor account. Returns the account dict."""
    res = api_client.create_contractor_account(
        create_contractor_account_payload(**overrides), ACCOUNTS)
    return get_success_data(res)


# ─── Sales-order lifecycle ─────────────────────────────────────────────────

def create_order_with_line(product_id, qty, contractor_account_id=None,
                           line_overrides=None):
    """Create a DRAFT order (cash or net-term) with a single line.

    Returns (order, line) — `order` is the create response (carries version
    v0, which remains valid through the first place since adding a line does
    not bump version)."""
    order = get_success_data(api_client.create_sales_order(
        create_sales_order_payload(contractor_account_id=contractor_account_id)
        if contractor_account_id else create_sales_order_payload(), SALES))
    line = get_success_data(api_client.add_order_line(
        order["id"],
        create_order_line_payload(product_id, qty, **(line_overrides or {})),
        SALES))
    return order, line


def place_order(order_id, expected_version):
    """Place a DRAFT order with the given expected version. Returns the placed
    order dict."""
    return get_success_data(api_client.place_order(
        order_id, {"expected_sales_order_version": expected_version}, SALES))


def setup_placed_order(product_id, qty, contractor_account_id=None,
                       line_overrides=None):
    """Create DRAFT order + line, then place it. Returns the placed order dict
    (carries the post-place version)."""
    order, _ = create_order_with_line(
        product_id, qty, contractor_account_id, line_overrides)
    return place_order(order["id"], order["version"])


def setup_fulfilled_order(product_id, qty, contractor_account_id=None,
                          line_overrides=None):
    """Create + place + fulfill. Returns the fulfilled order dict."""
    placed = setup_placed_order(
        product_id, qty, contractor_account_id, line_overrides)
    fulfilled = get_success_data(api_client.fulfill_order(
        placed["id"],
        {"expected_sales_order_version": placed["version"]}, SALES))
    return fulfilled


def setup_invoiced_order(product_id, qty, contractor_account_id,
                         line_overrides=None):
    """Create + place + fulfill + invoice a net-term order. Returns the order
    dict re-fetched after invoicing (payment_status INVOICED)."""
    fulfilled = setup_fulfilled_order(
        product_id, qty, contractor_account_id, line_overrides)
    api_client.invoice_order(fulfilled["id"], ACCOUNTS)
    return get_success_data(api_client.get_sales_order(fulfilled["id"], ACCOUNTS))


# ─── Special-order lifecycle ────────────────────────────────────────────────

def create_special_order(vendor_id, account_id, qty, **overrides):
    """Open a DRAFT special order (acting as SalesAssociate). Returns the
    order dict."""
    res = api_client.create_special_order(
        create_special_order_payload(vendor_id, account_id, qty, **overrides),
        SALES)
    return get_success_data(res)


def setup_quoted_special_order(qty, quoted_unit_cents, account_overrides=None):
    """Drop-ship vendor + ACTIVE account + DRAFT special order quoted once.

    Returns (special_order, vendor, account). The order is in QUOTED state."""
    vendor = create_vendor(drop_ship_capable=True)
    account = create_account(**(account_overrides or {}))
    so = create_special_order(vendor["id"], account["id"], qty)
    quoted = get_success_data(api_client.quote_special_order(
        so["id"], {"quoted_unit_cents": quoted_unit_cents}, SALES))
    return quoted, vendor, account


def setup_confirmed_special_order(qty, quoted_unit_cents, account_overrides=None):
    """Quoted special order then confirmed by the owning Contractor.

    Returns (special_order, vendor, account). Order is CONFIRMED; an ISSUED
    Invoice now bills the account."""
    quoted, vendor, account = setup_quoted_special_order(
        qty, quoted_unit_cents, account_overrides)
    confirmed = get_success_data(api_client.confirm_special_order(
        quoted["id"], make_contractor_headers(account["id"])))
    return confirmed, vendor, account


# ─── Rental lifecycle ────────────────────────────────────────────────────

def set_clock(iso_instant):
    """Advance the server logical clock to the supplied instant."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso_instant}, INVENTORY))


def create_rental_asset(**overrides):
    """Register an AVAILABLE rental asset. Returns the asset dict."""
    return get_success_data(api_client.create_rental_asset(
        create_rental_asset_payload(**overrides), RENTAL))


def create_reservation(asset_id, start_at, due_at, **overrides):
    """Reserve an asset for [start_at, due_at). Returns the RESERVED agreement."""
    return get_success_data(api_client.create_rental_agreement(
        create_rental_agreement_payload(asset_id, start_at, due_at, **overrides),
        RENTAL))


def setup_checked_out_rental(start_at, due_at, checkout_clock,
                             daily_rate_cents=5000):
    """Asset + reservation, advance clock to checkout_clock, then check out.

    Returns (agreement, asset). Agreement is CHECKED_OUT."""
    asset = create_rental_asset(daily_rate_cents=daily_rate_cents)
    agreement = create_reservation(asset["id"], start_at, due_at)
    set_clock(checkout_clock)
    checked_out = get_success_data(api_client.check_out_rental(agreement["id"], RENTAL))
    return checked_out, asset


# ─── Service stations / tickets ────────────────────────────────────────────

def create_station(**overrides):
    """Create an ACTIVE service station. Returns the station dict."""
    return get_success_data(api_client.create_service_station(
        create_service_station_payload(**overrides), INVENTORY))


def book_ticket(station_id, service_type, scheduled_start, scheduled_end,
                **overrides):
    """Book a BOOKED service ticket. Returns the ticket dict."""
    return get_success_data(api_client.create_service_ticket(
        create_service_ticket_payload(
            station_id, service_type, scheduled_start, scheduled_end, **overrides),
        SALES))


# ─── Purchase orders ──────────────────────────────────────────────────────

def create_draft_po(vendor_id, lines):
    """Draft a purchase order. Returns the PO dict."""
    return get_success_data(api_client.create_purchase_order(
        create_purchase_order_payload(vendor_id, lines), INVENTORY))


def setup_submitted_po(vendor, product_id, qty, unit_cost_cents):
    """Draft + submit a PO for one product line. Returns the SUBMITTED PO."""
    po = create_draft_po(vendor["id"],
                         [{"product_id": product_id, "qty": qty,
                           "unit_cost_cents": unit_cost_cents}])
    return get_success_data(api_client.submit_purchase_order(po["id"], INVENTORY))
