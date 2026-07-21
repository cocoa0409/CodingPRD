"""Composite setup helpers.

Every helper takes the `api` client as its first argument, drives the PRD-declared
endpoints from an empty database (the server is restarted before each test), and returns
parsed resource dicts. Setup calls use get_success_data() so a broken precondition surfaces
as a clear "Setup step failed" instead of a confusing assertion later.

Identity threading: Customer is entity_backed:Member, so every ownership-gated Customer call
uses make_customer_headers(member["id"]).
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import TEST_USERS, make_customer_headers
from . import factories as F

ADMIN = TEST_USERS["platform_admin_headers"]
STAFF = TEST_USERS["shop_staff_headers"]
INV = TEST_USERS["inventory_manager_headers"]
APPROVER = TEST_USERS["wholesale_approver_headers"]


# ─── Clock ────────────────────────────────────────────
def set_clock(api, to_iso8601):
    return get_success_data(api.set_clock(to_iso8601, ADMIN))


# ─── Primitive creators ───────────────────────────────
def create_member(api, allergen_restrictions=None, **overrides):
    payload = F.create_member_payload(**overrides)
    if allergen_restrictions is not None:
        payload["allergen_restrictions"] = allergen_restrictions
    return get_success_data(api.create_member(payload, ADMIN))


def create_product(api, product_type="BOTTLE", **overrides):
    payload = F.create_product_payload(product_type=product_type, **overrides)
    return get_success_data(api.create_product(payload, INV))


def create_bulk_product(api, price_per_ml_cents=0.30, shelf_life_days=540, **overrides):
    payload = F.create_bulk_product_payload(
        price_per_ml_cents=price_per_ml_cents, shelf_life_days=shelf_life_days, **overrides)
    return get_success_data(api.create_product(payload, INV))


def create_bottle(api, unit_price_cents, **overrides):
    return create_product(api, product_type="BOTTLE",
                          unit_price_cents=unit_price_cents, **overrides)


def create_gift_set(api, **overrides):
    return create_product(api, product_type="GIFT_SET", **overrides)


def add_component(api, set_id, component_id, quantity=1):
    payload = {"component_product_id": component_id, "quantity": quantity}
    return get_success_data(api.add_component(set_id, payload, INV))


def create_fusti(api, product_id, capacity_ml=10000, initial_volume_ml=10000,
                 reorder_point_ml=2000, harvest_date="2026-06-01T00:00:00Z"):
    payload = F.create_fusti_payload(
        product_id, capacity_ml=capacity_ml, initial_volume_ml=initial_volume_ml,
        reorder_point_ml=reorder_point_ml, harvest_date=harvest_date)
    return get_success_data(api.create_fusti(payload, INV))


def create_station(api, name="Test Bar"):
    return get_success_data(api.create_tasting_station({"name": name}, INV))


# ─── Order lifecycle ──────────────────────────────────
def create_order(api, member, lines, wholesale_account_id=None, use_wallet_credit=False):
    payload = {"lines": lines}
    if wholesale_account_id is not None:
        payload["wholesale_account_id"] = wholesale_account_id
    if use_wallet_credit:
        payload["use_wallet_credit"] = True
    headers = make_customer_headers(member["id"])
    return get_success_data(api.create_order(payload, headers))


def pay_order(api, member, order):
    """Pay `order` as its owning Customer. Returns the updated Order."""
    headers = make_customer_headers(member["id"])
    return get_success_data(
        api.pay_order(order["id"], {"expected_order_version": order["version"]}, headers))


def fulfill_order(api, order):
    """Fulfill a RESERVED order as ShopStaff. Returns the updated Order."""
    return get_success_data(
        api.fulfill_order(order["id"], {"expected_order_version": order["version"]}, STAFF))


def cancel_order(api, order, member=None, as_staff=False):
    """Cancel/return `order`. Customer for pre-fulfillment states, ShopStaff for returns."""
    if as_staff or member is None:
        headers = STAFF
    else:
        headers = make_customer_headers(member["id"])
    return get_success_data(
        api.cancel_order(order["id"], {"expected_order_version": order["version"]}, headers))


def get_reservation_for_order(api, order_id):
    data, _meta = _list(api.list_reservations(STAFF, params={"order_id": order_id}))
    assert data, f"expected a reservation for order {order_id}"
    return data[0]


def _list(response):
    body = get_success_data(response)
    # get_success_data returns the `data` payload; meta is on the envelope.
    meta = response.json().get("meta", {})
    return body, meta


# ─── Wholesale ────────────────────────────────────────
def create_wholesale_account(api, member, **overrides):
    headers = make_customer_headers(member["id"])
    payload = F.create_wholesale_account_payload(**overrides)
    return get_success_data(api.create_wholesale_account(payload, headers))


def submit_wholesale_account(api, member, wa):
    headers = make_customer_headers(member["id"])
    return get_success_data(api.submit_wholesale_account(wa["id"], headers))


def decide_wholesale_account(api, wa, decision, tier=None, rejection_reason=None):
    payload = {"decision": decision, "expected_wholesale_account_version": wa["version"]}
    if tier is not None:
        payload["tier"] = tier
    if rejection_reason is not None:
        payload["rejection_reason"] = rejection_reason
    return get_success_data(api.decide_wholesale_account(wa["id"], payload, APPROVER))


def create_approved_wholesale(api, member, tier="TIER_1"):
    """Full path DRAFT -> SUBMITTED -> APPROVED at `tier`. Returns the APPROVED account."""
    wa = create_wholesale_account(api, member)
    wa = submit_wholesale_account(api, member, wa)
    wa = decide_wholesale_account(api, wa, "APPROVE", tier=tier)
    return wa


# ─── Subscriptions ────────────────────────────────────
def create_subscription(api, member, product_id, cadence_days=30,
                        expected_member_version=None, **overrides):
    if expected_member_version is None:
        expected_member_version = member["version"]
    payload = F.create_subscription_payload(
        product_id, cadence_days, expected_member_version, **overrides)
    headers = make_customer_headers(member["id"])
    return get_success_data(api.create_subscription(payload, headers))


def transition_subscription(api, sub_id, action, member=None, as_staff=False):
    headers = STAFF if (as_staff or member is None) else make_customer_headers(member["id"])
    return get_success_data(api.transition_subscription(sub_id, {"action": action}, headers))


# ─── Tasting sessions ─────────────────────────────────
def book_session(api, member, station_id, start_at, end_at, party_size=None):
    payload = {"station_id": station_id, "start_at": start_at, "end_at": end_at}
    if party_size is not None:
        payload["party_size"] = party_size
    headers = make_customer_headers(member["id"])
    return get_success_data(api.create_tasting_session(payload, headers))


# ─── Composite scenarios ──────────────────────────────
def setup_refill_order_paid(api, volume_ml=1000, capacity_ml=10000, initial_volume_ml=6000,
                            reorder_point_ml=2000, harvest_date="2026-06-01T00:00:00Z",
                            price_per_ml_cents=0.30, shelf_life_days=540):
    """Member + bulk product + one fusti + a PAID/RESERVED refill order holding `volume_ml`.
    Returns (member, product, fusti, order) where `order` is the post-pay Order."""
    member = create_member(api)
    product = create_bulk_product(api, price_per_ml_cents=price_per_ml_cents,
                                  shelf_life_days=shelf_life_days)
    fusti = create_fusti(api, product["id"], capacity_ml=capacity_ml,
                         initial_volume_ml=initial_volume_ml, reorder_point_ml=reorder_point_ml,
                         harvest_date=harvest_date)
    order = create_order(api, member, [F.refill_line(product["id"], volume_ml)])
    order = pay_order(api, member, order)
    return member, product, fusti, order


def setup_bottle_order_created(api, unit_price_cents=3000, quantity=1):
    """Member + bottle + a fresh UNPAID/PENDING UNIT order. Returns (member, product, order)."""
    member = create_member(api)
    product = create_bottle(api, unit_price_cents=unit_price_cents)
    order = create_order(api, member, [F.unit_line(product["id"], quantity)])
    return member, product, order
