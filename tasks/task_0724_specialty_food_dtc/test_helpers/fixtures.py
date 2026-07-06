"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "Setup failed" errors, not confusing assertion failures.

Identity threading: after creating an entity-backed Customer, every ownership-gated
call uses make_customer_headers(customer["id"]) / make_corporate_buyer_headers(buyer["id"]),
never the shared TEST_USERS constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_customer_payload, create_sku_payload, create_lot_payload,
    release_lot_payload, create_subscription_payload, create_order_payload,
    create_order_line_payload, pay_order_payload, create_bulk_quote_payload,
)
from .test_users import TEST_USERS, make_customer_headers, make_corporate_buyer_headers
from .constants import FAR_EXPIRY_ISO

INV = TEST_USERS["inventory_manager_headers"]
COMP = TEST_USERS["compliance_officer_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ─── Primitive builders ────────────────────────────────────────────────

def create_customer(home_zone="Z1", email=None, **overrides):
    """Create a customer (PlatformAdmin). Returns the Customer entity.

    Email is auto-uniquified to avoid ERR_DUPLICATE_EMAIL across multi-customer setups.
    """
    if email is None:
        email = f"c{create_customer._n}@example.com"
        create_customer._n += 1
    payload = create_customer_payload(email=email, home_zone=home_zone, **overrides)
    return get_success_data(api_client.create_customer(payload, ADMIN))
create_customer._n = 0


def create_corporate_buyer(home_zone="Z1", email=None, **overrides):
    """Create a customer account that will act as a CorporateBuyer. Returns the Customer entity."""
    if email is None:
        email = f"b{create_corporate_buyer._n}@example.com"
        create_corporate_buyer._n += 1
    payload = create_customer_payload(email=email, home_zone=home_zone, **overrides)
    return get_success_data(api_client.create_customer(payload, TEST_USERS["corporate_buyer_headers"]))
create_corporate_buyer._n = 0


def create_draft_sku(name="Test Sauce", category="HOT_SAUCE", storage_class="AMBIENT",
                     unit_price_cents=1000, **overrides):
    """Create a DRAFT SKU (InventoryManager). Returns the Sku entity."""
    payload = create_sku_payload(name=name, category=category, storage_class=storage_class,
                                 unit_price_cents=unit_price_cents, **overrides)
    return get_success_data(api_client.create_sku(payload, INV))


def create_quarantine_lot(sku_id, produced_units=50, expiry_iso=FAR_EXPIRY_ISO, lot_code="L-A"):
    """Create a QUARANTINE lot (InventoryManager). Returns the Lot entity (status QUARANTINE)."""
    payload = create_lot_payload(sku_id, produced_units=produced_units,
                                 expiry_iso=expiry_iso, lot_code=lot_code)
    return get_success_data(api_client.create_lot(payload, INV))


def release_lot(lot):
    """Release a QUARANTINE lot using its current version. Returns the released Lot."""
    res = api_client.release_lot(lot["id"], release_lot_payload(lot["version"]), INV)
    return get_success_data(res)


def create_active_sku_with_lot(name="Active Sauce", category="HOT_SAUCE",
                               storage_class="AMBIENT", unit_price_cents=1000,
                               produced_units=50, expiry_iso=FAR_EXPIRY_ISO, lot_code="L-A"):
    """SKU -> approve label -> create lot -> release lot -> activate SKU.

    Returns (sku, lot) where sku.status == ACTIVE and lot.status == RELEASED.
    """
    sku = create_draft_sku(name=name, category=category, storage_class=storage_class,
                           unit_price_cents=unit_price_cents)
    get_success_data(api_client.approve_label(sku["id"], COMP))
    lot = create_quarantine_lot(sku["id"], produced_units=produced_units,
                                expiry_iso=expiry_iso, lot_code=lot_code)
    lot = release_lot(lot)
    sku = get_success_data(api_client.activate_sku(sku["id"], INV))
    return sku, lot


# ─── Subscriptions ─────────────────────────────────────────────────────

def create_active_subscription(customer_id, sku_id, tier="STARTER", cadence_days=14):
    """Create an ACTIVE subscription owned by customer_id. Returns the Subscription."""
    payload = create_subscription_payload(customer_id, sku_id, tier=tier, cadence_days=cadence_days)
    return get_success_data(
        api_client.create_subscription(payload, make_customer_headers(customer_id)))


def setup_customer_with_active_subscription(tier="STARTER", cadence_days=14, home_zone="Z1",
                                            sku_overrides=None):
    """ACTIVE SKU (in-stock) + customer + ACTIVE subscription on that SKU.

    Returns (customer, sku, lot, subscription).
    """
    sku_overrides = sku_overrides or {}
    sku, lot = create_active_sku_with_lot(category="COFFEE", **sku_overrides)
    customer = create_customer(home_zone=home_zone)
    sub = create_active_subscription(customer["id"], sku["id"], tier=tier, cadence_days=cadence_days)
    return customer, sku, lot, sub


# ─── Orders ────────────────────────────────────────────────────────────

def create_draft_order(customer_id, **order_overrides):
    """Create a DRAFT order owned by customer_id. Returns the Order."""
    payload = create_order_payload(customer_id, **order_overrides)
    return get_success_data(api_client.create_order(payload, make_customer_headers(customer_id)))


def add_line(order_id, customer_id, sku_id, quantity=1):
    """Add one line to a DRAFT order. Returns the OrderLine."""
    payload = create_order_line_payload(sku_id, quantity)
    return get_success_data(
        api_client.add_order_line(order_id, payload, make_customer_headers(customer_id)))


def reserve_order(order_id, customer_id):
    """Reserve a DRAFT order (DRAFT -> RESERVED). Returns the Order with frozen totals."""
    return get_success_data(api_client.reserve_order(order_id, make_customer_headers(customer_id)))


def pay_order(order_id, customer_id, outcome="SUCCEEDED"):
    """Attempt payment. Returns the Order."""
    return get_success_data(
        api_client.pay_order(order_id, pay_order_payload(outcome), make_customer_headers(customer_id)))


def ship_order(order_id):
    """Ship a paid reserved order (InventoryManager). Returns the shipped Order."""
    return get_success_data(api_client.ship_order(order_id, INV))


def build_reserved_order(customer_id, lines, **order_overrides):
    """Create a DRAFT order, add `lines` [(sku_id, qty), ...], reserve it.

    Returns the RESERVED Order (with frozen subtotal/discount/handling/shipping/total).
    """
    order = create_draft_order(customer_id, **order_overrides)
    for sku_id, qty in lines:
        add_line(order["id"], customer_id, sku_id, qty)
    return reserve_order(order["id"], customer_id)


def build_paid_reserved_order(customer_id, lines, **order_overrides):
    """Create -> add lines -> reserve -> pay(SUCCEEDED). Returns the PAID RESERVED Order."""
    order = build_reserved_order(customer_id, lines, **order_overrides)
    pay_order(order["id"], customer_id, "SUCCEEDED")
    return get_success_data(api_client.get_order(order["id"], make_customer_headers(customer_id)))


def build_shipped_order(customer_id, lines, **order_overrides):
    """Create -> add lines -> reserve -> pay -> ship. Returns the SHIPPED Order."""
    order = build_paid_reserved_order(customer_id, lines, **order_overrides)
    return ship_order(order["id"])


# ─── Dual-variant renewal: ACTIVE CLASSIC sub in Z2, advanced to due ────

def setup_subscription_due_for_renewal(tier="CLASSIC", cadence_days=28, home_zone="Z2",
                                       unit_price_cents=4900, due_iso="2026-04-01T00:00:00Z"):
    """Active in-stock SKU + customer in `home_zone` + ACTIVE subscription, clock advanced
    so the subscription is due. Returns (customer, sku, subscription).

    Captures the subscription's provisional_charge_cents on the returned `subscription` dict.
    """
    sku, lot = create_active_sku_with_lot(name="Renewal Coffee", category="COFFEE",
                                          storage_class="AMBIENT", unit_price_cents=unit_price_cents,
                                          produced_units=100)
    customer = create_customer(home_zone=home_zone)
    sub = create_active_subscription(customer["id"], sku["id"], tier=tier, cadence_days=cadence_days)
    get_success_data(api_client.set_clock(due_iso, ADMIN))
    return customer, sku, sub


# ─── Churn windows: customer with 2 old skips, clock advanced past window ─

def setup_churn_customer_with_old_skips(num_skips=2, due_iso="2026-06-30T00:00:00Z"):
    """Customer with a STARTER cadence-14 subscription, takes `num_skips` skips, then the clock
    advances past the 90-day acute window. Returns (customer, subscription).
    """
    sku, lot = create_active_sku_with_lot(name="Churn Snack", category="SNACK",
                                          storage_class="AMBIENT", unit_price_cents=1000)
    customer = create_customer(home_zone="Z1")
    sub = create_active_subscription(customer["id"], sku["id"], tier="STARTER", cadence_days=14)
    for _ in range(num_skips):
        get_success_data(api_client.skip_subscription(sub["id"], make_customer_headers(customer["id"])))
    get_success_data(api_client.set_clock(due_iso, ADMIN))
    return customer, sub


# ─── Skips already taken ───────────────────────────────────────────────

def setup_subscription_with_skips(num_skips=2):
    """ACTIVE subscription on an in-stock SKU with `num_skips` skips already taken.

    Returns (customer, subscription_after_skips).
    """
    sku, lot = create_active_sku_with_lot(name="Skip Coffee", category="COFFEE",
                                          storage_class="AMBIENT", unit_price_cents=1000)
    customer = create_customer(home_zone="Z1")
    sub = create_active_subscription(customer["id"], sku["id"], tier="STARTER", cadence_days=14)
    last = sub
    for _ in range(num_skips):
        last = get_success_data(
            api_client.skip_subscription(sub["id"], make_customer_headers(customer["id"])))
    return customer, last


# ─── Bulk quotes ───────────────────────────────────────────────────────

def setup_draft_bulk_quote(quantity=10, unit_price_cents=1000, gift_box_count=None,
                           activate_sku=True):
    """Create a SKU (optionally ACTIVE) + corporate buyer + DRAFT bulk quote.

    Returns (buyer, sku, bulk_quote).
    """
    if activate_sku:
        sku, lot = create_active_sku_with_lot(name="Bulk Sauce", category="HOT_SAUCE",
                                              storage_class="AMBIENT",
                                              unit_price_cents=unit_price_cents,
                                              produced_units=max(quantity, 50) + 1000)
    else:
        sku = create_draft_sku(name="Bulk Sauce", category="HOT_SAUCE",
                               storage_class="AMBIENT", unit_price_cents=unit_price_cents)
    buyer = create_corporate_buyer(home_zone="Z1")
    bq_overrides = {} if gift_box_count is None else {"gift_box_count": gift_box_count}
    payload = create_bulk_quote_payload(buyer["id"], sku["id"], quantity, **bq_overrides)
    bq = get_success_data(
        api_client.create_bulk_quote(payload, make_corporate_buyer_headers(buyer["id"])))
    return buyer, sku, bq


# ─── Referrals ─────────────────────────────────────────────────────────

def setup_referrer_and_referred_with_referral():
    """Referrer customer + referred customer (created with referrer_id), plus the auto-created
    PENDING Referral and an ACTIVE in-stock SKU.

    Returns (referrer, referred, referral, sku).
    """
    sku, lot = create_active_sku_with_lot(name="Ref Sauce", category="HOT_SAUCE",
                                          storage_class="AMBIENT", unit_price_cents=1000)
    referrer = create_customer(home_zone="Z1")
    referred_payload = create_customer_payload(
        email=f"red{setup_referrer_and_referred_with_referral._n}@example.com",
        home_zone="Z1", referrer_id=referrer["id"])
    setup_referrer_and_referred_with_referral._n += 1
    referred = get_success_data(api_client.create_customer(referred_payload, ADMIN))
    data, _meta = _list(api_client.list_referrals(ADMIN, params={"referred_id": referred["id"]}))
    referral = data[0]
    return referrer, referred, referral, sku
setup_referrer_and_referred_with_referral._n = 0


def setup_qualified_referral():
    """Full chain to a QUALIFIED referral: referred customer's first order ships.

    Returns (referrer, referred, referral, sku) with referral.status == QUALIFIED.
    """
    referrer, referred, referral, sku = setup_referrer_and_referred_with_referral()
    build_shipped_order(referred["id"], [(sku["id"], 1)])
    data, _meta = _list(api_client.list_referrals(ADMIN, params={"referred_id": referred["id"]}))
    return referrer, referred, data[0], sku


# ─── helpers ───────────────────────────────────────────────────────────

def _list(response):
    """Lenient extraction of (data_list, meta) from a list response for setup use."""
    body = response.json()
    return body.get("data", []), body.get("meta", {})


def set_clock(to_iso8601):
    """Advance the logical clock (PlatformAdmin)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))
