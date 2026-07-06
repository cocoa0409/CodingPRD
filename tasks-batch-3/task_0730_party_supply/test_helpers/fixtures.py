"""Composite setup helpers — one place for the multi-step setups needed
by design-index instances. Setup calls use get_success_data() so any
setup failure surfaces as a clear 'Setup failed' error.
"""
import uuid
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    make_store_manager_headers, make_store_clerk_headers,
    make_customer_headers, TEST_USERS,
)


# -----------------------------------------------------------------
# Unique-value helpers — every test starts against an empty DB, but
# multiple entities per test still need unique codes/emails.
# -----------------------------------------------------------------

def unique_email(prefix="user") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@example.com"


def unique_sku_code(prefix="SKU") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def unique_tank_code(prefix="TANK") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def unique_bundle_code(prefix="BUNDLE") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def unique_package_code(prefix="PKG") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def unique_van_id(prefix="V") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


# -----------------------------------------------------------------
# Clock
# -----------------------------------------------------------------

def set_clock(iso: str):
    """Set the server logical clock to `iso`."""
    r = api_client.set_clock(iso, make_store_manager_headers())
    return get_success_data(r)


# -----------------------------------------------------------------
# Tier 1 — atoms
# -----------------------------------------------------------------

def create_customer(email=None, full_name="Test Cust"):
    r = api_client.create_customer(
        {"email": email or unique_email(), "full_name": full_name},
        make_store_clerk_headers(),
    )
    return get_success_data(r)


def create_sku(sku_code=None, category="DECOR", unit_price_cents=500,
               theme_tag=None, seasonal_window_start=None,
               seasonal_window_end=None):
    payload = {
        "sku_code": sku_code or unique_sku_code(),
        "category": category,
        "unit_price_cents": unit_price_cents,
    }
    if theme_tag is not None:
        payload["theme_tag"] = theme_tag
    if seasonal_window_start is not None:
        payload["seasonal_window_start"] = seasonal_window_start
    if seasonal_window_end is not None:
        payload["seasonal_window_end"] = seasonal_window_end
    r = api_client.create_sku(payload, make_store_manager_headers())
    return get_success_data(r)


def restock_sku(sku_id, delta):
    r = api_client.restock_sku(sku_id, delta, make_store_manager_headers())
    return get_success_data(r)


def create_sku_with_stock(unit_price_cents=500, on_hand=10, category="DECOR",
                          sku_code=None, theme_tag=None,
                          seasonal_window_start=None,
                          seasonal_window_end=None):
    """Create an SKU and restock to `on_hand` in one step.
    Returns the SKU dict AFTER the restock (with fresh version)."""
    sku = create_sku(sku_code=sku_code, category=category,
                     unit_price_cents=unit_price_cents,
                     theme_tag=theme_tag,
                     seasonal_window_start=seasonal_window_start,
                     seasonal_window_end=seasonal_window_end)
    if on_hand > 0:
        sku = restock_sku(sku["id"], on_hand)
    return sku


def create_helium_tank(tank_code=None, capacity=100):
    r = api_client.create_helium_tank(
        {"tank_code": tank_code or unique_tank_code(),
         "capacity_cubic_ft": capacity},
        make_store_manager_headers(),
    )
    return get_success_data(r)


def create_event_package(package_code=None, base_price_cents=20000,
                         deposit_pct=0.30, min_lead_days=7):
    r = api_client.create_event_package(
        {"package_code": package_code or unique_package_code(),
         "base_price_cents": base_price_cents,
         "deposit_pct": deposit_pct,
         "min_lead_days": min_lead_days},
        make_store_manager_headers(),
    )
    return get_success_data(r)


def create_delivery_slot(window_start, window_end, van_id=None,
                         setup_included=False):
    payload = {
        "window_start": window_start,
        "window_end": window_end,
        "van_id": van_id or unique_van_id(),
    }
    if setup_included:
        payload["setup_included"] = True
    r = api_client.create_delivery_slot(payload, make_store_clerk_headers())
    return get_success_data(r)


def create_order(customer_id, channel="IN_STORE", lines=None,
                 pickup_window_start=None, pickup_window_end=None,
                 delivery_slot_id=None):
    payload = {
        "customer_id": customer_id,
        "channel": channel,
        "lines": lines or [],
    }
    if pickup_window_start is not None:
        payload["pickup_window_start"] = pickup_window_start
    if pickup_window_end is not None:
        payload["pickup_window_end"] = pickup_window_end
    if delivery_slot_id is not None:
        payload["delivery_slot_id"] = delivery_slot_id
    r = api_client.create_order(payload, make_store_clerk_headers())
    return get_success_data(r)


def attach_helium(order_id, latex_count=0, foil_count=0):
    r = api_client.attach_helium(
        order_id,
        {"latex_count": latex_count, "foil_count": foil_count},
        make_store_clerk_headers(),
    )
    return get_success_data(r)


def attach_custom_print(order_id, art_reference="https://art.example/x",
                        banner_length_ft=5):
    r = api_client.attach_custom_print(
        order_id,
        {"art_reference": art_reference,
         "banner_length_ft": banner_length_ft},
        make_store_clerk_headers(),
    )
    return get_success_data(r)


def create_rental_contract(order_id, sku_id, qty, rental_start, rental_end):
    r = api_client.create_rental_contract(
        {"order_id": order_id, "sku_id": sku_id, "qty": qty,
         "rental_start": rental_start, "rental_end": rental_end},
        make_store_clerk_headers(),
    )
    return get_success_data(r)


def create_event_booking(order_id, event_package_id, event_date):
    r = api_client.create_event_booking(
        {"order_id": order_id,
         "event_package_id": event_package_id,
         "event_date": event_date},
        make_store_clerk_headers(),
    )
    return get_success_data(r)


# -----------------------------------------------------------------
# Tier 1 — clearance/unclear atoms
# -----------------------------------------------------------------

def apply_clearance(sku_id, pct, expected_sku_version):
    r = api_client.clearance_sku(
        sku_id,
        {"pct": pct, "expected_sku_version": expected_sku_version},
        make_store_manager_headers(),
    )
    return get_success_data(r)


# -----------------------------------------------------------------
# Tier 1 — order transitions
# -----------------------------------------------------------------

def reserve_order(order_id, expected_order_version):
    r = api_client.reserve_order(
        order_id, expected_order_version, make_store_clerk_headers(),
    )
    return get_success_data(r)


def pay_order(order_id, mode):
    r = api_client.pay_order(order_id, mode, make_store_clerk_headers())
    return get_success_data(r)


def start_picking(order_id):
    r = api_client.start_picking_order(order_id, make_store_clerk_headers())
    return get_success_data(r)


def mark_ready(order_id):
    r = api_client.mark_ready_order(order_id, make_store_clerk_headers())
    return get_success_data(r)


def pickup(order_id):
    r = api_client.pickup_order(order_id, make_store_clerk_headers())
    return get_success_data(r)


def cancel_order(order_id):
    r = api_client.cancel_order(order_id, make_store_clerk_headers())
    return get_success_data(r)


# -----------------------------------------------------------------
# Tier 2 — Hierarchies
# -----------------------------------------------------------------

def setup_customer_and_sku(sku_price=500, on_hand=10,
                           category="DECOR"):
    """Baseline: clock at 2026-06-15, one customer, one SKU restocked."""
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=sku_price,
                                on_hand=on_hand, category=category)
    return cust, sku


def setup_draft_order(customer_id, sku_id, qty=1, channel="IN_STORE",
                       pickup_window_start=None, pickup_window_end=None,
                       delivery_slot_id=None):
    """Create a DRAFT order with a single sku_id line at qty=`qty`."""
    return create_order(
        customer_id=customer_id,
        channel=channel,
        lines=[{"sku_id": sku_id, "qty": qty}],
        pickup_window_start=pickup_window_start,
        pickup_window_end=pickup_window_end,
        delivery_slot_id=delivery_slot_id,
    )


def setup_reserved_order(customer_id=None, sku_price=500, on_hand=10,
                         qty=1, channel="IN_STORE",
                         pickup_window_start=None, pickup_window_end=None,
                         category="DECOR"):
    """Full path: clock→customer→sku→order→reserve. Returns
    (customer, sku, order-after-reserve)."""
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer() if customer_id is None else {"id": customer_id}
    sku = create_sku_with_stock(unit_price_cents=sku_price, on_hand=on_hand,
                                category=category)
    order = setup_draft_order(cust["id"], sku["id"], qty=qty,
                              channel=channel,
                              pickup_window_start=pickup_window_start,
                              pickup_window_end=pickup_window_end)
    reserved = reserve_order(order["id"], order["version"])
    return cust, sku, reserved


def setup_bopis_ready_for_pickup(sku_price=500, on_hand=10, qty=1):
    """BOPIS order taken to READY_FOR_PICKUP with payment_status=PAID.
    Returns (customer, sku, order)."""
    cust, sku, reserved = setup_reserved_order(
        sku_price=sku_price, on_hand=on_hand, qty=qty,
        channel="BOPIS",
        pickup_window_start="2026-06-15T14:00:00Z",
        pickup_window_end="2026-06-15T18:00:00Z",
    )
    pay_order(reserved["id"], "FULL")
    start_picking(reserved["id"])
    ready = mark_ready(reserved["id"])
    return cust, sku, ready


# -----------------------------------------------------------------
# Tier 3 — CustomPrintOrder lifecycle helpers
# -----------------------------------------------------------------

def setup_order_with_custom_print_paid(banner_length_ft=5, base_sku_price=200,
                                        base_on_hand=100, base_qty=1):
    """Full setup ending with an Order paid FULL and a DRAFT
    CustomPrintOrder attached. Returns (customer, sku, order, cpo)."""
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=base_sku_price,
                                on_hand=base_on_hand, category="DECOR")
    order = setup_draft_order(cust["id"], sku["id"], qty=base_qty)
    cpo = attach_custom_print(order["id"], banner_length_ft=banner_length_ft)
    reserved = reserve_order(order["id"], order["version"])
    pay_order(reserved["id"], "FULL")
    return cust, sku, reserved, cpo


def setup_cpo_at_proof_sent(banner_length_ft=5, base_sku_price=200,
                             base_on_hand=100):
    """Take a CustomPrintOrder from DRAFT to PROOF_SENT once (rev_count=0).
    Returns (customer, sku, order, cpo_after_first_proof)."""
    cust, sku, order, cpo = setup_order_with_custom_print_paid(
        banner_length_ft=banner_length_ft,
        base_sku_price=base_sku_price,
        base_on_hand=base_on_hand,
    )
    r = api_client.send_proof(cpo["id"], make_store_clerk_headers())
    cpo_ps = get_success_data(r)
    return cust, sku, order, cpo_ps


def do_request_revision_and_proof(cpo_id, customer_id):
    """One full round of request-revision then send-proof."""
    r1 = api_client.request_revision(cpo_id, make_customer_headers(customer_id))
    get_success_data(r1)
    r2 = api_client.send_proof(cpo_id, make_store_clerk_headers())
    return get_success_data(r2)


# -----------------------------------------------------------------
# Tier 3 — EventBooking lifecycle helpers
# -----------------------------------------------------------------

def setup_order_with_event_booking(
    event_date="2026-07-30T18:00:00Z",
    package_base_price_cents=20000,
    package_deposit_pct=0.30,
    package_min_lead_days=7,
    sku_price=100,
    on_hand=5,
    sku_qty=1,
):
    """Clock at 2026-06-15, Customer + SKU + Order + EventPackage +
    EventBooking (HELD). Order NOT yet reserved. Returns
    (customer, sku, order, package, booking)."""
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=sku_price, on_hand=on_hand)
    pkg = create_event_package(base_price_cents=package_base_price_cents,
                               deposit_pct=package_deposit_pct,
                               min_lead_days=package_min_lead_days)
    order = setup_draft_order(cust["id"], sku["id"], qty=sku_qty)
    booking = create_event_booking(order["id"], pkg["id"], event_date)
    return cust, sku, order, pkg, booking


# -----------------------------------------------------------------
# Tier 3 — Rental lifecycle helpers
# -----------------------------------------------------------------

def setup_tableware_sku_with_stock(unit_price_cents=500, on_hand=20):
    """A TABLEWARE-category SKU with on_hand stock."""
    return create_sku_with_stock(unit_price_cents=unit_price_cents,
                                 on_hand=on_hand, category="TABLEWARE")


# -----------------------------------------------------------------
# Tier 4 — Custom print numeric fixtures
# -----------------------------------------------------------------

def setup_cpo_paid_with_n_revisions(banner_length_ft, n_revisions,
                                     base_sku_price=200,
                                     base_on_hand=100):
    """End at PROOF_SENT with revision_count == n_revisions and
    the order fully paid so approve is allowed. Returns
    (customer, order, cpo_ps_after_final_proof)."""
    cust, sku, order, cpo_ps = setup_cpo_at_proof_sent(
        banner_length_ft=banner_length_ft,
        base_sku_price=base_sku_price,
        base_on_hand=base_on_hand,
    )
    latest = cpo_ps
    for _ in range(n_revisions):
        latest = do_request_revision_and_proof(cpo_ps["id"], cust["id"])
    return cust, order, latest
