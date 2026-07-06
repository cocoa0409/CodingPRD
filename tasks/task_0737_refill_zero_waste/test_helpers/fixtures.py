"""Composite setup helpers.

Every test starts against a fresh, empty database (the runner restarts the
server before each test), so these helpers build all preconditions from scratch
using only PRD-declared endpoints. Setup calls use the lenient get_success_data
validator so a broken precondition surfaces as a clear "Setup step failed".

Actor conventions (PRD §2.1):
- Catalog / inventory ops (products, stations, bins, recounts, restock
  completions, vehicles) use the InventoryManager (opaque operator).
- Member-facing ops (members, containers, orders, lines, fills, subscriptions,
  deliveries) use the StoreClerk, who is explicitly permitted to act on behalf
  of any member. Both roles are opaque, so no ownership threading is required
  for setup; the entity_backed Member headers are only used by the RBAC tests
  that assert an ownership/role denial.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS
from . import factories as f

CLERK = TEST_USERS["store_clerk_headers"]
IM = TEST_USERS["inventory_manager_headers"]

# Default station fill-window (a single order per test can reuse this).
WINDOW_START = "2026-03-02T09:00:00Z"
WINDOW_END = "2026-03-02T10:00:00Z"


# ─── Granular creators (return the entity data dict) ───────────────────────

def create_member(api=api_client, *, tier=None, email=None, full_name="Test Member"):
    overrides = {"full_name": full_name}
    if tier is not None:
        overrides["membership_tier"] = tier
    if email is not None:
        overrides["email"] = email
    return get_success_data(api.create_member(f.create_member_payload(**overrides), CLERK))


def create_product(api=api_client, **overrides):
    return get_success_data(api.create_product(f.create_product_payload(**overrides), IM))


def create_station(api=api_client, **overrides):
    return get_success_data(api.create_station(f.create_station_payload(**overrides), IM))


def create_bin(api=api_client, *, product_id, station_id, **overrides):
    return get_success_data(
        api.create_bin(f.create_bin_payload(product_id, station_id, **overrides), IM))


def create_container(api=api_client, *, container_type="BYO", declared_tare_g=200,
                     member_id=None):
    return get_success_data(api.create_container(
        f.create_container_payload(container_type, declared_tare_g, member_id), CLERK))


def issue_container(api=api_client, *, container_id, member_id):
    return get_success_data(
        api.issue_container(container_id, {"member_id": member_id}, CLERK))


def create_order(api=api_client, *, member_id, station_id,
                 fill_window_start_at=WINDOW_START, fill_window_end_at=WINDOW_END,
                 **overrides):
    payload = f.create_order_payload(member_id, station_id,
                                     fill_window_start_at, fill_window_end_at, **overrides)
    return get_success_data(api.create_order(payload, CLERK))


def add_line(api=api_client, *, order_id, product_id, container_id, estimated_gross_g=1150):
    return get_success_data(api.add_line(
        order_id, f.add_line_payload(product_id, container_id, estimated_gross_g), CLERK))


def start_fill(api=api_client, *, order_id):
    return get_success_data(api.start_fill(order_id, CLERK))


def fill_line(api=api_client, *, line_id, gross_weight_g, measured_tare_g):
    return get_success_data(api.fill_line(
        line_id, f.fill_line_payload(gross_weight_g, measured_tare_g), CLERK))


def checkout_order(api=api_client, *, order_id, redeem_points=None):
    payload = {} if redeem_points is None else {"redeem_points": redeem_points}
    return get_success_data(api.checkout_order(order_id, payload, CLERK))


def recount_bin(api=api_client, *, bin_id, physical_g):
    return get_success_data(api.recount_bin(bin_id, {"physical_g": physical_g}, IM))


def create_vehicle(api=api_client, **overrides):
    return get_success_data(
        api.create_delivery_vehicle(f.create_vehicle_payload(**overrides), IM))


def create_delivery(api=api_client, *, order_id, vehicle_id,
                    window_start_at="2026-03-02T12:00:00Z",
                    window_end_at="2026-03-02T13:00:00Z"):
    payload = f.create_delivery_payload(order_id, vehicle_id, window_start_at, window_end_at)
    return get_success_data(api.create_delivery(payload, CLERK))


def create_subscription(api=api_client, *, member_id, product_id, station_id,
                        target_net_g=500, interval_days=7):
    payload = f.create_subscription_payload(member_id, product_id, station_id,
                                            target_net_g, interval_days)
    return get_success_data(api.create_subscription(payload, CLERK))


# ─── Tier 1/2: catalog + owned container + cart line ───────────────────────

def setup_catalog(api=api_client, *, member_tier=None,
                  product_overrides=None, bin_overrides=None):
    """Active baseline: one member + one product + one station + one bin bound
    to that product at that station. Returns dict(member, product, station, bin)."""
    member = create_member(api, tier=member_tier)
    product = create_product(api, **(product_overrides or {}))
    station = create_station(api)
    bin_ = create_bin(api, product_id=product["id"], station_id=station["id"],
                      **(bin_overrides or {}))
    return {"member": member, "product": product, "station": station, "bin": bin_}


def setup_cart_line(api=api_client, *, member_tier=None, product_overrides=None,
                    bin_overrides=None, container_type="BYO", declared_tare_g=200,
                    estimated_gross_g=1150, channel=None,
                    window_start=WINDOW_START, window_end=WINDOW_END):
    """Catalog + a member-owned container + a CART order + one PROVISIONAL line.
    Returns dict(member, product, station, bin, container, order, line)."""
    base = setup_catalog(api, member_tier=member_tier,
                         product_overrides=product_overrides, bin_overrides=bin_overrides)
    container = create_container(api, container_type=container_type,
                                 declared_tare_g=declared_tare_g,
                                 member_id=base["member"]["id"])
    order_kwargs = {}
    if channel is not None:
        order_kwargs["fulfillment_channel"] = channel
    order = create_order(api, member_id=base["member"]["id"], station_id=base["station"]["id"],
                         fill_window_start_at=window_start, fill_window_end_at=window_end,
                         **order_kwargs)
    line = add_line(api, order_id=order["id"], product_id=base["product"]["id"],
                    container_id=container["id"], estimated_gross_g=estimated_gross_g)
    return {**base, "container": container, "order": order, "line": line}


def setup_filling_line(api=api_client, **kwargs):
    """As setup_cart_line, then start-fill (order -> FILLING, line still PROVISIONAL)."""
    s = setup_cart_line(api, **kwargs)
    start_fill(api, order_id=s["order"]["id"])
    return s


def setup_final_line(api=api_client, *, gross_weight_g, measured_tare_g, **kwargs):
    """As setup_filling_line, then fill the line to FINAL. The returned 'line'
    is the fill response (carries final net_weight_g/line_price_cents/stage)."""
    s = setup_filling_line(api, **kwargs)
    filled = fill_line(api, line_id=s["line"]["id"],
                       gross_weight_g=gross_weight_g, measured_tare_g=measured_tare_g)
    s["line"] = filled
    return s


# ─── Tier 3/5: deposit container through checkout / delivery lifecycle ──────

def setup_committed_deposit_order(api=api_client, *, channel=None,
                                  container_type="GLASS_500", declared_tare_g=250,
                                  estimated_gross_g=750, gross_weight_g=750,
                                  measured_tare_g=250):
    """Issue a deposit container to the member, fill and check out an order that
    references it, so the container is IN_USE and its deposit is committed. The
    member's deposit_liability equals the container deposit; wallet is 0.
    Returns dict(member, product, station, bin, container, order, line)."""
    base = setup_catalog(api)
    container = create_container(api, container_type=container_type,
                                 declared_tare_g=declared_tare_g)
    issue_container(api, container_id=container["id"], member_id=base["member"]["id"])
    order_kwargs = {}
    if channel is not None:
        order_kwargs["fulfillment_channel"] = channel
    order = create_order(api, member_id=base["member"]["id"], station_id=base["station"]["id"],
                         **order_kwargs)
    line = add_line(api, order_id=order["id"], product_id=base["product"]["id"],
                    container_id=container["id"], estimated_gross_g=estimated_gross_g)
    start_fill(api, order_id=order["id"])
    fill_line(api, line_id=line["id"], gross_weight_g=gross_weight_g,
              measured_tare_g=measured_tare_g)
    checkout_order(api, order_id=order["id"])
    return {**base, "container": create_or_none(api, container["id"]),
            "order": order, "line": line}


def create_or_none(api, container_id):
    """Re-fetch a container's current state (used after a lifecycle transition)."""
    return get_success_data(api.get_container(container_id, CLERK))


def setup_delivered_order(api=api_client):
    """A DELIVERY order carried all the way through to a DELIVERED delivery with a
    committed deposit container still IN_USE (ready for return-received).
    Returns dict(member, container, order, vehicle, delivery)."""
    s = setup_committed_deposit_order(api, channel="DELIVERY")
    vehicle = create_vehicle(api)
    delivery = create_delivery(api, order_id=s["order"]["id"], vehicle_id=vehicle["id"])
    get_success_data(api.dispatch_delivery(delivery["id"], CLERK))
    get_success_data(api.deliver_delivery(delivery["id"], CLERK))
    return {"member": s["member"], "container": s["container"], "order": s["order"],
            "vehicle": vehicle, "delivery": delivery}
