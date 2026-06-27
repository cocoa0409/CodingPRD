"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient) internally so setup failures surface as clear
"Setup step failed" errors rather than confusing downstream assertion failures.

Identity threading: the Customer role is entity-backed. Every ownership-gated call
on a customer's own resources passes make_customer_headers(customer["id"]).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_customer_headers
from . import factories as F
from .constants import TEST_CLOCK_ISO

ADMIN = TEST_USERS["admin_headers"]
ASSOCIATE = TEST_USERS["store_associate_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ─── Clock ──────────────────────────────────────────────────────────────────
def set_clock(iso=TEST_CLOCK_ISO):
    """Set the logical clock (PRD §2.8). Default 2026-06-01 so DOB 2000-01-01 is age 26."""
    return get_success_data(api_client.set_clock(iso, ADMIN))


# ─── Tier 1: Customers & age verification ───────────────────────────────────
def register_customer(email, ship_state_code="CA", date_of_birth="2000-01-01", **overrides):
    """Register a customer (Anonymous). Returns the Customer dict."""
    res = api_client.register_customer(
        F.register_customer_payload(email=email, ship_state_code=ship_state_code,
                                    date_of_birth=date_of_birth, **overrides),
        ANON)
    return get_success_data(res)


def create_pending_scan(customer, id_state_code=None, id_expiry_date="2030-01-01",
                        scanned_dob=None):
    """Create a PENDING IdScan for a customer. Returns the IdScan dict."""
    state = id_state_code or customer["ship_state_code"]
    dob = scanned_dob or customer["date_of_birth"]
    res = api_client.create_id_scan(
        F.id_scan_payload(customer["id"], id_state_code=state,
                          id_expiry_date=id_expiry_date, scanned_dob=dob),
        ASSOCIATE)
    return get_success_data(res)


def create_verified_customer(email, ship_state_code="CA", date_of_birth="2000-01-01"):
    """Register a customer, scan, and verify so age_verified == true.
    Returns the (re-read) Customer dict."""
    cust = register_customer(email, ship_state_code=ship_state_code,
                             date_of_birth=date_of_birth)
    scan = create_pending_scan(cust)
    get_success_data(api_client.verify_id_scan(scan["id"], ASSOCIATE))
    return get_success_data(api_client.get_customer(cust["id"], ASSOCIATE))


# ─── Tier 2: Catalog (product → vintage → lot → release/allocation) ─────────
def create_product(sku, category="WINE", container_type="BOTTLE",
                   bottle_volume_ml=750, abv_pct=13.00, is_allocated=False, name=None):
    payload = F.product_payload(sku=sku, name=name or sku, category=category,
                                container_type=container_type,
                                bottle_volume_ml=bottle_volume_ml, abv_pct=abv_pct)
    if is_allocated:
        payload["is_allocated"] = True
    return get_success_data(api_client.create_product(payload, ADMIN))


def create_vintage(product_id, vintage_year=2020, list_price_cents=3000,
                   case_pack_size=6, allocation_cap_per_customer=None):
    payload = F.vintage_payload(vintage_year=vintage_year,
                                list_price_cents=list_price_cents,
                                case_pack_size=case_pack_size)
    if allocation_cap_per_customer is not None:
        payload["allocation_cap_per_customer"] = allocation_cap_per_customer
    return get_success_data(api_client.create_vintage(product_id, payload, ADMIN))


def create_lot(vintage_id, tax_status="TAXED", qty_on_hand=10,
               excise_band_cents_per_unit=0, as_headers=None):
    headers = as_headers or (COMPLIANCE if tax_status == "BONDED" else ADMIN)
    return get_success_data(api_client.create_lot(
        vintage_id, F.lot_payload(tax_status=tax_status, qty_on_hand=qty_on_hand,
                                  excise_band_cents_per_unit=excise_band_cents_per_unit),
        headers))


def setup_released_vintage(sku, category="WINE", container_type="BOTTLE",
                           bottle_volume_ml=750, abv_pct=13.00,
                           list_price_cents=3000, case_pack_size=6,
                           tax_status="TAXED", qty_on_hand=10,
                           excise_band_cents_per_unit=0, vintage_year=2020):
    """Product + DRAFT vintage + one lot + RELEASE. Returns (product, vintage, lot)."""
    product = create_product(sku, category=category, container_type=container_type,
                             bottle_volume_ml=bottle_volume_ml, abv_pct=abv_pct)
    vintage = create_vintage(product["id"], vintage_year=vintage_year,
                             list_price_cents=list_price_cents,
                             case_pack_size=case_pack_size)
    lot = create_lot(vintage["id"], tax_status=tax_status, qty_on_hand=qty_on_hand,
                     excise_band_cents_per_unit=excise_band_cents_per_unit)
    get_success_data(api_client.release_vintage(vintage["id"], ADMIN))
    vintage = get_success_data(api_client.get_vintage(vintage["id"], ADMIN))
    return product, vintage, lot


def setup_allocation_open_vintage(sku, allocation_cap_per_customer,
                                  list_price_cents=12000, case_pack_size=6,
                                  qty_on_hand=10, vintage_year=2017,
                                  category="SPIRITS", abv_pct=45.00):
    """Allocated product + DRAFT vintage with cap + lot + open-allocation.
    Returns (product, vintage, lot)."""
    product = create_product(sku, category=category, container_type="BOTTLE",
                             bottle_volume_ml=750, abv_pct=abv_pct, is_allocated=True)
    vintage = create_vintage(product["id"], vintage_year=vintage_year,
                             list_price_cents=list_price_cents,
                             case_pack_size=case_pack_size,
                             allocation_cap_per_customer=allocation_cap_per_customer)
    lot = create_lot(vintage["id"], tax_status="TAXED", qty_on_hand=qty_on_hand)
    get_success_data(api_client.open_allocation(vintage["id"], COMPLIANCE))
    vintage = get_success_data(api_client.get_vintage(vintage["id"], COMPLIANCE))
    return product, vintage, lot


# ─── State rules ────────────────────────────────────────────────────────────
def create_state_rule(state_code, ship_allowed=True, growler_keg_allowed=True,
                      monthly_volume_limit_ml=None, requires_adult_signature=False):
    payload = F.state_rule_payload(state_code, ship_allowed=ship_allowed,
                                   growler_keg_allowed=growler_keg_allowed,
                                   requires_adult_signature=requires_adult_signature)
    if monthly_volume_limit_ml is not None:
        payload["monthly_volume_limit_ml"] = monthly_volume_limit_ml
    return get_success_data(api_client.create_state_rule(payload, COMPLIANCE))


# ─── Tier 3: Order construction & lifecycle ─────────────────────────────────
def create_cart_order(customer, channel="POS", dest_state_code=None):
    """Create a CART order owned by customer. Returns the Order dict."""
    payload = F.order_payload(customer["id"], channel=channel)
    if dest_state_code is not None:
        payload["dest_state_code"] = dest_state_code
    return get_success_data(api_client.create_order(payload, make_customer_headers(customer["id"])))


def add_line(customer, order_id, vintage_id, qty):
    """Add an order line as the owning customer. Returns the OrderLine dict."""
    return get_success_data(api_client.add_line(
        order_id, F.order_line_payload(vintage_id, qty=qty),
        make_customer_headers(customer["id"])))


def current_order_version(customer, order_id):
    """Read the order's current version for the OCC submit field."""
    order = get_success_data(api_client.get_order(order_id, make_customer_headers(customer["id"])))
    return order["version"]


def submit_order(customer, order_id):
    """Submit a cart order with the current expected_order_version. Returns the Order dict."""
    ver = current_order_version(customer, order_id)
    return get_success_data(api_client.submit_order(
        order_id, {"expected_order_version": ver},
        make_customer_headers(customer["id"])))


def build_submitted_order(customer, vintage_id, qty, channel="POS", dest_state_code=None):
    """Create cart order + one line + submit. Returns the submitted Order dict."""
    order = create_cart_order(customer, channel=channel, dest_state_code=dest_state_code)
    add_line(customer, order["id"], vintage_id, qty)
    return submit_order(customer, order["id"])


def authorize(customer, order_id):
    return get_success_data(api_client.authorize_payment(
        order_id, make_customer_headers(customer["id"])))


def capture(order_id):
    return get_success_data(api_client.capture_payment(order_id, ASSOCIATE))


def build_captured_order(customer, vintage_id, qty, channel="POS", dest_state_code=None):
    """cart → line → submit → authorize → capture. Returns the captured Order dict."""
    order = build_submitted_order(customer, vintage_id, qty, channel=channel,
                                  dest_state_code=dest_state_code)
    authorize(customer, order["id"])
    return capture(order["id"])


def build_ready_order(customer, vintage_id, qty, channel="POS", dest_state_code=None):
    """...→ capture → mark-ready. Returns the READY Order dict."""
    order = build_captured_order(customer, vintage_id, qty, channel=channel,
                                 dest_state_code=dest_state_code)
    return get_success_data(api_client.mark_ready(order["id"], ASSOCIATE))


def build_completed_order(customer, vintage_id, qty):
    """POS lifecycle through COMPLETED (no shipment needed for POS). Returns Order dict."""
    order = build_ready_order(customer, vintage_id, qty, channel="POS")
    return get_success_data(api_client.complete_order(order["id"], ASSOCIATE))


def build_dispatched_shipment(customer, vintage_id, qty, dest_state_code,
                              carrier="LICENSED_COMMON_CARRIER"):
    """DELIVERY order → ready → shipment → dispatch. Returns (order, shipment)."""
    order = build_ready_order(customer, vintage_id, qty, channel="DELIVERY",
                              dest_state_code=dest_state_code)
    shipment = get_success_data(api_client.create_shipment(
        order["id"], F.shipment_payload(carrier=carrier), ASSOCIATE))
    shipment = get_success_data(api_client.dispatch_shipment(shipment["id"], ASSOCIATE))
    return order, shipment


# ─── Special orders ─────────────────────────────────────────────────────────
def create_special_order(customer, description="rare item", requested_qty=1):
    return get_success_data(api_client.create_special_order(
        F.special_order_payload(customer["id"], description=description,
                                requested_qty=requested_qty),
        make_customer_headers(customer["id"])))


def create_membership(customer):
    return get_success_data(api_client.create_membership(
        F.membership_payload(customer["id"]), make_customer_headers(customer["id"])))
