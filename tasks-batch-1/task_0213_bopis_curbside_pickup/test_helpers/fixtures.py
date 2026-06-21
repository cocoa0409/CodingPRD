"""Composite setup helpers.

Every test runs against a freshly-restarted, empty server. These helpers build the
multi-step preconditions (seed catalog → walk an order through its fulfillment
lifecycle) so tests can focus on assertions. All setup calls use get_success_data()
(lenient) so a setup failure surfaces clearly rather than as a confusing assertion.

Identity threading: the Customer role is entity_backed, so every ownership-gated call
(create order, add line, submit, accept/decline substitution, curbside check-in,
customer-side cancel) uses make_customer_headers(customer["id"]).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    make_customer_headers, make_picker_headers, make_associate_headers,
    make_manager_headers, make_admin_headers, anonymous_headers,
)
from . import factories as f


# Far-future slot window so cutoff never trips unless a test intends it.
DEFAULT_CLOCK = "2026-06-01T00:00:00Z"
DEFAULT_WINDOW_START = "2026-06-02T00:00:00Z"
DEFAULT_WINDOW_END = "2026-06-02T02:00:00Z"


# --- Tier 0: atomic seed helpers ------------------------------------------

def create_customer(email=None, full_name="Cust", phone="111"):
    payload = f.create_customer_payload(full_name=full_name, phone=phone)
    if email is not None:
        payload["email"] = email
    return get_success_data(api_client.create_customer(payload, anonymous_headers()))


def create_store(curbside_spaces=2, hold_window_minutes=60, name="S", state_code="CA"):
    payload = f.create_store_payload(name=name, state_code=state_code,
                                     curbside_spaces=curbside_spaces)
    if hold_window_minutes is not None:
        payload["hold_window_minutes"] = hold_window_minutes
    return get_success_data(api_client.create_store(payload, make_admin_headers()))


def create_product(unit_price_cents=1000, sku=None, name="Prod", substitution_group=None):
    payload = f.create_product_payload(name=name, unit_price_cents=unit_price_cents)
    if sku is not None:
        payload["sku"] = sku
    if substitution_group is not None:
        payload["substitution_group"] = substitution_group
    return get_success_data(api_client.create_product(payload, make_admin_headers()))


def create_inventory(store_id, product_id, on_hand=5):
    payload = f.create_store_inventory_payload(store_id, product_id, on_hand=on_hand)
    return get_success_data(api_client.create_store_inventory(payload, make_admin_headers()))


def create_slot(store_id, window_start=DEFAULT_WINDOW_START, window_end=DEFAULT_WINDOW_END,
                capacity=5, cutoff_offset_minutes=0):
    payload = f.create_pickup_slot_payload(store_id, window_start, window_end, capacity=capacity)
    if cutoff_offset_minutes is not None:
        payload["cutoff_offset_minutes"] = cutoff_offset_minutes
    return get_success_data(api_client.create_pickup_slot(payload, make_admin_headers()))


def set_clock(to_iso8601):
    return get_success_data(api_client.clock_set(f.clock_payload(to_iso8601), make_admin_headers()))


def advance_clock(to_iso8601):
    return get_success_data(api_client.clock_advance(f.clock_payload(to_iso8601), make_admin_headers()))


def get_slot_version(slot_id):
    return get_success_data(api_client.get_pickup_slot(slot_id, make_manager_headers()))["version"]


def get_inventory_version(inventory_id):
    return get_success_data(api_client.get_store_inventory(inventory_id, make_manager_headers()))["version"]


# --- Tier 1: base scenario (catalog + clock + one customer) ----------------

def seed_base_scenario(products=None, on_hand=10, curbside_spaces=2, hold_window_minutes=60,
                       capacity=5, cutoff_offset_minutes=0, clock=DEFAULT_CLOCK,
                       window_start=DEFAULT_WINDOW_START, window_end=DEFAULT_WINDOW_END):
    """Seed a store, one or more products (each with inventory), a clock, an OPEN slot,
    and a customer. `products` is a list of dicts: {price, on_hand?, substitution_group?, sku?}.
    Defaults to one product priced 1000.

    Returns a dict with: store, products (list), inventories (list, parallel to products),
    slot, slot_version, customer.
    """
    if products is None:
        products = [{"price": 1000}]
    store = create_store(curbside_spaces=curbside_spaces, hold_window_minutes=hold_window_minutes)
    prod_objs = []
    inv_objs = []
    for spec in products:
        p = create_product(
            unit_price_cents=spec["price"],
            substitution_group=spec.get("substitution_group"),
            sku=spec.get("sku"),
        )
        prod_objs.append(p)
        inv = create_inventory(store["id"], p["id"], on_hand=spec.get("on_hand", on_hand))
        inv_objs.append(inv)
    set_clock(clock)
    slot = create_slot(store["id"], window_start=window_start, window_end=window_end,
                       capacity=capacity, cutoff_offset_minutes=cutoff_offset_minutes)
    customer = create_customer()
    return {
        "store": store,
        "products": prod_objs,
        "inventories": inv_objs,
        "slot": slot,
        "slot_version": slot["version"],
        "customer": customer,
    }


# --- Tier 2/3: order lifecycle drivers -------------------------------------

def create_draft_order(customer_id, store_id):
    return get_success_data(api_client.create_order(
        f.create_order_payload(customer_id, store_id), make_customer_headers(customer_id)))


def add_line(order_id, customer_id, product_id, qty_ordered):
    return get_success_data(api_client.add_order_line(
        order_id, f.create_order_line_payload(product_id, qty_ordered),
        make_customer_headers(customer_id)))


def submit_order(order_id, customer_id, slot_id, expected_slot_version):
    return get_success_data(api_client.submit_order(
        order_id, f.submit_order_payload(slot_id, expected_slot_version),
        make_customer_headers(customer_id)))


def create_order_with_lines(customer_id, store_id, slot_id, slot_version, lines):
    """Create a DRAFT order, add lines, submit it. `lines` is a list of (product_id, qty).
    Returns (order, line_objs). Caller passes the *current* slot_version.
    """
    order = create_draft_order(customer_id, store_id)
    line_objs = [add_line(order["id"], customer_id, pid, qty) for (pid, qty) in lines]
    submitted = submit_order(order["id"], customer_id, slot_id, slot_version)
    return submitted, line_objs


def start_picking(order_id):
    return get_success_data(api_client.start_picking(order_id, make_picker_headers()))


def pick_line(line_id, qty_picked):
    return get_success_data(api_client.pick_line(
        line_id, {"qty_picked": qty_picked}, make_picker_headers()))


def stage_order(order_id):
    return get_success_data(api_client.stage_order(order_id, make_picker_headers()))


def ready_order(order_id):
    return get_success_data(api_client.ready_order(order_id, make_picker_headers()))


def verify_order(order_id, presented_name="Cust", presented_phone="111"):
    return get_success_data(api_client.verify_order(
        order_id, f.verify_payload(presented_name, presented_phone), make_associate_headers()))


def propose_substitution(order_line_id, substitute_product_id, substitute_qty):
    return get_success_data(api_client.create_substitution(
        f.create_substitution_payload(order_line_id, substitute_product_id, substitute_qty),
        make_picker_headers()))


def accept_substitution(substitution_id, customer_id):
    return get_success_data(api_client.accept_substitution(
        substitution_id, make_customer_headers(customer_id)))


# --- Tier 4: high-level lifecycle shortcuts --------------------------------

def setup_awaiting_pickup_order(line_specs, verified=True, curbside_spaces=2,
                                hold_window_minutes=60, capacity=5, clock=DEFAULT_CLOCK):
    """Drive a single-customer order to AWAITING_PICKUP, optionally verified.

    `line_specs` is a list of dicts: {price, qty, pick?, substitution_group?}.
      - price: product unit_price_cents
      - qty: qty_ordered
      - pick: qty_picked (defaults to qty for a full pick)
    Each spec maps to its own product+inventory (on_hand large enough).

    Returns a dict: store, products (list), inventories (list), slot, customer,
    order (latest fetched), lines (list, parallel to line_specs).
    """
    products = []
    for spec in line_specs:
        products.append({
            "price": spec["price"],
            "on_hand": spec.get("on_hand", 10),
            "substitution_group": spec.get("substitution_group"),
        })
    base = seed_base_scenario(products=products, curbside_spaces=curbside_spaces,
                              hold_window_minutes=hold_window_minutes, capacity=capacity,
                              clock=clock)
    customer = base["customer"]
    lines_input = [(base["products"][i]["id"], line_specs[i]["qty"])
                   for i in range(len(line_specs))]
    order, line_objs = create_order_with_lines(
        customer["id"], base["store"]["id"], base["slot"]["id"],
        base["slot_version"], lines_input)
    start_picking(order["id"])
    for i, spec in enumerate(line_specs):
        pick_qty = spec.get("pick", spec["qty"])
        pick_line(line_objs[i]["id"], pick_qty)
    stage_order(order["id"])
    ready_order(order["id"])
    if verified:
        order = verify_order(order["id"])
    else:
        order = get_success_data(api_client.get_order(order["id"], make_manager_headers()))
    return {
        "store": base["store"],
        "products": base["products"],
        "inventories": base["inventories"],
        "slot": base["slot"],
        "customer": customer,
        "order": order,
        "lines": line_objs,
    }


def setup_short_picked_with_proposal(original_price=1500, substitute_price=1800,
                                     qty=2, substitute_qty=2,
                                     substitution_group="BREAD",
                                     extra_substitute_groups=None):
    """Build an order in PICKING with one line short-picked to 0 and a PROPOSED
    substitution. Optionally seed extra substitute products sharing the group.

    Returns dict: store, customer, order, line (the short-picked line),
    original_product, substitute_product, substitute_inventory, substitution,
    extra_products (list).
    """
    product_specs = [
        {"price": original_price, "substitution_group": substitution_group, "on_hand": 5},
        {"price": substitute_price, "substitution_group": substitution_group, "on_hand": 5},
    ]
    extra_specs = extra_substitute_groups or []
    for ep in extra_specs:
        product_specs.append({"price": ep["price"],
                              "substitution_group": substitution_group, "on_hand": 5})
    base = seed_base_scenario(products=product_specs)
    customer = base["customer"]
    order, lines = create_order_with_lines(
        customer["id"], base["store"]["id"], base["slot"]["id"], base["slot_version"],
        [(base["products"][0]["id"], qty)])
    start_picking(order["id"])
    pick_line(lines[0]["id"], 0)
    substitution = propose_substitution(
        lines[0]["id"], base["products"][1]["id"], substitute_qty)
    return {
        "store": base["store"],
        "customer": customer,
        "order": order,
        "line": lines[0],
        "original_product": base["products"][0],
        "substitute_product": base["products"][1],
        "substitute_inventory": base["inventories"][1],
        "substitution": substitution,
        "extra_products": base["products"][2:],
    }


def setup_picking_order(line_specs, curbside_spaces=2, hold_window_minutes=60, capacity=5,
                        on_hand=10):
    """Drive a single-customer order to PICKING (submitted + start-picking), lines RESERVED.
    `line_specs`: list of {price, qty, substitution_group?, on_hand?}.
    Returns dict: store, products, inventories, slot, customer, order, lines.
    """
    products = [{"price": s["price"], "on_hand": s.get("on_hand", on_hand),
                 "substitution_group": s.get("substitution_group")} for s in line_specs]
    base = seed_base_scenario(products=products, curbside_spaces=curbside_spaces,
                              hold_window_minutes=hold_window_minutes, capacity=capacity)
    customer = base["customer"]
    lines_input = [(base["products"][i]["id"], line_specs[i]["qty"]) for i in range(len(line_specs))]
    order, line_objs = create_order_with_lines(
        customer["id"], base["store"]["id"], base["slot"]["id"], base["slot_version"], lines_input)
    start_picking(order["id"])
    return {
        "store": base["store"],
        "products": base["products"],
        "inventories": base["inventories"],
        "slot": base["slot"],
        "customer": customer,
        "order": order,
        "lines": line_objs,
    }


# --- Tier: no-show strike accumulation -------------------------------------

def raise_customer_to_strikes(target_strikes, hold_window_minutes=60):
    """Drive one customer to exactly `target_strikes` no-show strikes by cycling
    submit→pick→stage→ready→(advance clock past hold)→expire, target_strikes times.

    Returns dict: store, product, inventory, slot, customer (re-fetched with final
    strikes/standing). The inventory has on_hand 1 restored after each expiry (a
    picked-but-not-collected unit returns to stock on EXPIRE), so each cycle reuses it.
    """
    from datetime import datetime, timedelta, timezone

    store = create_store(curbside_spaces=2, hold_window_minutes=hold_window_minutes)
    product = create_product(unit_price_cents=1000)
    inventory = create_inventory(store["id"], product["id"], on_hand=1)
    # Generous fixed window far ahead; only the hold clock advances each cycle.
    set_clock("2026-06-01T00:00:00Z")
    slot = create_slot(store["id"], window_start="2026-06-10T00:00:00Z",
                       window_end="2026-06-10T06:00:00Z", capacity=target_strikes + 2,
                       cutoff_offset_minutes=0)
    customer = create_customer()
    # Each cycle stages the order at a distinct instant, then advances the logical
    # clock to staged_at + hold_window_minutes (the §2.8 hold deadline) so that the
    # §3.7 expiry's hold-expirability check (clock >= expires_at) is satisfied. The
    # per-cycle stride exceeds the hold window so successive cycles never overlap.
    base = datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    stride = timedelta(minutes=hold_window_minutes + 60)

    def _fmt(dt):
        return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"

    for cycle in range(target_strikes):
        staged_at = base + cycle * stride
        set_clock(_fmt(staged_at))
        slot_v = get_slot_version(slot["id"])
        order = create_draft_order(customer["id"], store["id"])
        line = add_line(order["id"], customer["id"], product["id"], 1)
        submit_order(order["id"], customer["id"], slot["id"], slot_v)
        start_picking(order["id"])
        pick_line(line["id"], 1)
        stage_order(order["id"])
        ready_order(order["id"])
        # advance the logical clock to exactly the hold deadline so it is expirable
        expirable_at = staged_at + timedelta(minutes=hold_window_minutes)
        set_clock(_fmt(expirable_at))
        get_success_data(api_client.expire_order(order["id"], make_manager_headers()))
    customer = get_success_data(api_client.get_customer(customer["id"], make_manager_headers()))
    return {
        "store": store,
        "product": product,
        "inventory": inventory,
        "slot": slot,
        "customer": customer,
    }
