"""Composite setup helpers.

These encapsulate the multi-step API sequences needed to place the system in a
specific state so tests can focus on assertions. Every helper uses get_success_data()
(the lenient validator) so a broken precondition surfaces as a clear "Setup step failed".

Identity threading (PRD §2.1): Farm and Customer are entity_backed. Every ownership-gated
call threads make_farm_headers(farm["id"]) / make_customer_headers(customer["id"]) with the
real entity id — never a shared constant.

The per-test harness restarts the server (empty DB) before each test, so every helper builds
its whole world from scratch, beginning by pinning the logical clock.
"""
from prd_bench_local_runner.testing import get_success_data

from .factories import (
    create_farm_payload,
    create_product_payload,
    weight_product_payload,
    create_cycle_payload,
    create_offering_payload,
    create_hub_payload,
    create_customer_payload,
    create_subscription_payload,
    create_order_payload,
    add_line_payload,
    create_settlement_payload,
)
from .test_users import make_admin_headers, make_farm_headers, make_customer_headers

DEFAULT_CLOCK = "2026-06-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Primitives — one create/transition each, identity-threaded.
# ---------------------------------------------------------------------------
def set_clock(api, to_iso8601=DEFAULT_CLOCK):
    return get_success_data(api.set_clock(to_iso8601, make_admin_headers()))


def new_farm(api, **overrides):
    return get_success_data(api.create_farm(create_farm_payload(**overrides), make_admin_headers()))


def new_hub(api, **overrides):
    return get_success_data(api.create_hub(create_hub_payload(**overrides), make_admin_headers()))


def new_customer(api, **overrides):
    return get_success_data(api.create_customer(create_customer_payload(**overrides), make_admin_headers()))


def new_product(api, farm_id, **overrides):
    return get_success_data(
        api.create_product(farm_id, create_product_payload(**overrides), make_farm_headers(farm_id))
    )


def new_weight_product(api, farm_id, **overrides):
    return get_success_data(
        api.create_product(farm_id, weight_product_payload(**overrides), make_farm_headers(farm_id))
    )


def new_cycle(api, **overrides):
    return get_success_data(api.create_cycle(create_cycle_payload(**overrides), make_admin_headers()))


def new_offering(api, cycle_id, farm_id, product_id, **overrides):
    return get_success_data(
        api.create_offering(cycle_id, create_offering_payload(product_id, **overrides), make_farm_headers(farm_id))
    )


def open_cycle(api, cycle_id):
    return get_success_data(api.open_cycle(cycle_id, make_admin_headers()))


def cutoff_cycle(api, cycle_id):
    return get_success_data(api.cutoff_cycle(cycle_id, make_admin_headers()))


def settle_cycle(api, cycle_id):
    return get_success_data(api.settle_cycle(cycle_id, make_admin_headers()))


def new_order(api, customer_id, cycle_id, hub_id, **overrides):
    payload = create_order_payload(cycle_id, hub_id, **overrides)
    return get_success_data(api.create_order(payload, make_customer_headers(customer_id)))


def new_line(api, customer_id, order_id, offering_id, requested_qty=1, **overrides):
    payload = add_line_payload(offering_id, requested_qty, **overrides)
    return get_success_data(api.add_line(order_id, payload, make_customer_headers(customer_id)))


def do_checkout(api, customer_id, order_id):
    return get_success_data(api.checkout_order(order_id, make_customer_headers(customer_id)))


def do_pack(api, farm_id, line_id, **payload):
    return get_success_data(api.pack_line(line_id, payload, make_farm_headers(farm_id)))


def do_fulfill(api, order_id):
    return get_success_data(api.fulfill_order(order_id, make_admin_headers()))


def new_subscription(api, customer_id, hub_id, **overrides):
    payload = create_subscription_payload(pickup_hub_id=hub_id, **overrides)
    return get_success_data(api.create_subscription(customer_id, payload, make_customer_headers(customer_id)))


def do_settlement(api, farm_id, cycle_id, expected_farm_version):
    """Returns the raw Response (tests assert 201 / error), not the lenient data."""
    return api.create_settlement(
        farm_id, create_settlement_payload(cycle_id, expected_farm_version), make_admin_headers()
    )


def observed_farm_version(api, farm_id):
    return get_success_data(api.get_farm(farm_id, make_admin_headers()))["version"]


# ---------------------------------------------------------------------------
# Composite: base open marketplace with a single FIXED egg offering.
# The most common preamble across the suite.
# ---------------------------------------------------------------------------
def setup_open_egg_market(
    api,
    *,
    offered_qty=100,
    snap_balance=0,
    egg_snap_eligible=False,
    snap_authorized=True,
    commission_pct=0.15,
    hub_type="PICKUP",
    slot_capacity=100,
    unit_price_cents=400,
):
    """Clock + farm + hub + customer + FIXED egg product + cycle + egg offering + OPEN cycle.

    Returns a dict of all created entities plus threaded header helpers.
    """
    set_clock(api)
    farm = new_farm(api, snap_authorized=snap_authorized, commission_pct=commission_pct)
    hub = new_hub(api, hub_type=hub_type, slot_capacity=slot_capacity)
    customer = new_customer(api, snap_balance_cents=snap_balance)
    product = new_product(
        api, farm["id"], name="Eggs", category="DAIRY", pricing_mode="FIXED",
        unit_price_cents=unit_price_cents, snap_eligible=egg_snap_eligible,
    )
    cycle = new_cycle(api)
    offering = new_offering(api, cycle["id"], farm["id"], product["id"], offered_qty=offered_qty)
    open_cycle(api, cycle["id"])
    return {
        "farm": farm,
        "hub": hub,
        "customer": customer,
        "product": product,
        "cycle": cycle,
        "offering": offering,
        "farm_headers": make_farm_headers(farm["id"]),
        "cust_headers": make_customer_headers(customer["id"]),
        "admin_headers": make_admin_headers(),
    }


def setup_allocated_egg_line(api, *, requested_qty=2, offered_qty=100, snap_balance=0):
    """An egg line that has reached ALLOCATED: order created, one line added, checked out,
    cycle cut off. Order and line are both ALLOCATED, allocated_qty == requested_qty.

    Returns the setup_open_egg_market dict extended with 'order' and 'line'.
    """
    world = setup_open_egg_market(api, offered_qty=offered_qty, snap_balance=snap_balance)
    order = new_order(api, world["customer"]["id"], world["cycle"]["id"], world["hub"]["id"])
    line = new_line(api, world["customer"]["id"], order["id"], world["offering"]["id"], requested_qty)
    do_checkout(api, world["customer"]["id"], order["id"])
    cutoff_cycle(api, world["cycle"]["id"])
    world["order"] = order
    world["line"] = line
    return world


# ---------------------------------------------------------------------------
# Composite: the three-line SNAP order (tomato WEIGHT + egg FIXED + flower FIXED).
# subtotal 2500, eligible_subtotal 2000, customer snap_balance 800.
# Used by the dual-variant, benefit, and cascade difficulty instances.
# ---------------------------------------------------------------------------
def setup_snap_three_line_cart(api, *, snap_balance=800):
    """CART order carrying three lines under one snap-authorized farm:
      - tomato  WEIGHT 800/kg, est_weight 0.5, snap_eligible  -> qty 3, estimated 1200
      - egg     FIXED 400,                     snap_eligible  -> qty 2, estimated 800
      - flower  FIXED 500,                     NOT eligible   -> qty 1, estimated 500

    Returns a dict of entities and line handles (order still in CART, not checked out).
    """
    set_clock(api)
    farm = new_farm(api, snap_authorized=True, commission_pct=0.15)
    hub = new_hub(api)
    customer = new_customer(api, snap_balance_cents=snap_balance)

    tomato = new_weight_product(
        api, farm["id"], name="Heirloom Tomatoes", category="PRODUCE",
        price_per_kg_cents=800, estimated_weight_kg=0.5, snap_eligible=True,
    )
    egg = new_product(
        api, farm["id"], name="Eggs", category="DAIRY", pricing_mode="FIXED",
        unit_price_cents=400, snap_eligible=True,
    )
    flower = new_product(
        api, farm["id"], name="Cut Flowers", category="OTHER", pricing_mode="FIXED",
        unit_price_cents=500, snap_eligible=False,
    )

    cycle = new_cycle(api)
    off_tom = new_offering(api, cycle["id"], farm["id"], tomato["id"], offered_qty=100)
    off_egg = new_offering(api, cycle["id"], farm["id"], egg["id"], offered_qty=100)
    off_flower = new_offering(api, cycle["id"], farm["id"], flower["id"], offered_qty=50)
    open_cycle(api, cycle["id"])

    order = new_order(api, customer["id"], cycle["id"], hub["id"])
    line_tom = new_line(api, customer["id"], order["id"], off_tom["id"], 3)
    line_egg = new_line(api, customer["id"], order["id"], off_egg["id"], 2)
    line_flower = new_line(api, customer["id"], order["id"], off_flower["id"], 1)

    return {
        "farm": farm,
        "hub": hub,
        "customer": customer,
        "cycle": cycle,
        "off_tom": off_tom,
        "off_egg": off_egg,
        "off_flower": off_flower,
        "order": order,
        "line_tom": line_tom,
        "line_egg": line_egg,
        "line_flower": line_flower,
        "farm_headers": make_farm_headers(farm["id"]),
        "cust_headers": make_customer_headers(customer["id"]),
        "admin_headers": make_admin_headers(),
    }


def setup_snap_three_line_placed(api, *, snap_balance=800):
    """As setup_snap_three_line_cart, then checked out (order PLACED, payment AUTHORIZED).
    Adds 'checkout' (the checkout response data) to the returned dict."""
    world = setup_snap_three_line_cart(api, snap_balance=snap_balance)
    world["checkout"] = do_checkout(api, world["customer"]["id"], world["order"]["id"])
    return world
