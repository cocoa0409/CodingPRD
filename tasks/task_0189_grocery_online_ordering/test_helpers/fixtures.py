"""Composite setup helpers for grocery online-ordering tests.

The harness restarts the API server (empty DB) before every test, so every
fixture builds its preconditions from scratch using only PRD-declared endpoints.
All setup calls use the lenient get_success_data() validator so a setup failure
surfaces as a clear "Setup step failed" rather than a confusing assertion error.

Identity threading: Customer and Picker are entity_backed roles. After a fixture
creates a Customer/Picker, every ownership-gated call uses make_customer_headers/
make_picker_headers with that entity's actual id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_picker_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["store_ops_headers"]

# Default windows used throughout (deterministic, far enough apart not to collide).
DEFAULT_WINDOW_START = "2026-06-15T09:00:00Z"
DEFAULT_WINDOW_END = "2026-06-15T11:00:00Z"
DEFAULT_CLAIM_START = "2026-06-15T08:00:00Z"
DEFAULT_CLAIM_END = "2026-06-15T08:45:00Z"


# ─── Clock ────────────────────────────────────────────
def set_clock(to_iso8601: str):
    """Set the server's deterministic current UTC clock (PlatformAdmin)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ─── Tier 0: primitive provisioning ───────────────────
def create_store(name="S", **overrides) -> dict:
    payload = {"name": name}
    payload.update(overrides)
    return get_success_data(api_client.create_store(payload, ADMIN))


def create_customer(email="c@example.com", date_of_birth="1990-01-01", **overrides) -> dict:
    payload = {"email": email, "full_name": "C", "date_of_birth": date_of_birth}
    payload.update(overrides)
    return get_success_data(api_client.create_customer(payload, ADMIN))


def create_picker(store_id, full_name="P", **overrides) -> dict:
    payload = {"store_id": store_id, "full_name": full_name}
    payload.update(overrides)
    return get_success_data(api_client.create_picker(payload, OPS))


def create_product(store_id, sku="A", name="A", pricing_mode="UNIT",
                   unit_price_cents=349, **overrides) -> dict:
    payload = {
        "store_id": store_id,
        "sku": sku,
        "name": name,
        "pricing_mode": pricing_mode,
        "unit_price_cents": unit_price_cents,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_product(payload, OPS))


def create_slot(store_id, slot_type="PICKUP", window_start=DEFAULT_WINDOW_START,
                window_end=DEFAULT_WINDOW_END, capacity=1, **overrides) -> dict:
    payload = {
        "store_id": store_id,
        "slot_type": slot_type,
        "window_start": window_start,
        "window_end": window_end,
        "capacity": capacity,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_slot(payload, OPS))


def discontinue_product(product_id) -> dict:
    return get_success_data(api_client.discontinue_product(product_id, OPS))


def close_slot(slot_id) -> dict:
    return get_success_data(api_client.close_slot(slot_id, OPS))


def close_store(store_id) -> dict:
    return get_success_data(api_client.close_store(store_id, ADMIN))


def suspend_customer(customer_id) -> dict:
    return get_success_data(api_client.suspend_customer(customer_id, ADMIN))


def place_order(store_id, customer_id, slot_id, expected_slot_version, lines,
                tip_cents=None, as_customer_id=None) -> dict:
    """Place an order as the owning Customer (X-User-ID == customer_id)."""
    payload = {
        "store_id": store_id,
        "customer_id": customer_id,
        "slot_id": slot_id,
        "expected_slot_version": expected_slot_version,
        "lines": lines,
    }
    if tip_cents is not None:
        payload["tip_cents"] = tip_cents
    acting = as_customer_id if as_customer_id is not None else customer_id
    headers = make_customer_headers(acting)
    return get_success_data(api_client.create_order(payload, headers))


def get_line_ids(order_id, product_id=None, headers=None) -> list:
    """Return the order's line ids in created order (optionally filtered by product)."""
    headers = headers or OPS
    params = {"order_id": order_id}
    if product_id is not None:
        params["product_id"] = product_id
    data = get_success_data(api_client.list_order_lines(headers, params=params))
    return [ln["id"] for ln in data]


def get_slot_version(slot_id) -> int:
    return get_success_data(api_client.get_slot(slot_id, OPS))["version"]


# ─── Tier 1/2: provisioning bundles ───────────────────
def provision_store_customer_picker(ebt_enabled=None, snap_ebt_balance_cents=None,
                                     cold_chain_hold_minutes=None,
                                     window_cooldown_minutes=None,
                                     email="c@example.com"):
    """Active store + active customer + available picker. Returns (store, customer,
    picker)."""
    store_over = {}
    if ebt_enabled is not None:
        store_over["ebt_enabled"] = ebt_enabled
    if cold_chain_hold_minutes is not None:
        store_over["cold_chain_hold_minutes"] = cold_chain_hold_minutes
    store = create_store(**store_over)

    cust_over = {}
    if snap_ebt_balance_cents is not None:
        cust_over["snap_ebt_balance_cents"] = snap_ebt_balance_cents
    customer = create_customer(email=email, **cust_over)

    picker_over = {}
    if window_cooldown_minutes is not None:
        picker_over["window_cooldown_minutes"] = window_cooldown_minutes
    picker = create_picker(store["id"], **picker_over)
    return store, customer, picker


# ─── Tier 3: lifecycle shortcuts ──────────────────────
def claim_order(order_id, picker_id, window_start=DEFAULT_CLAIM_START,
                window_end=DEFAULT_CLAIM_END) -> dict:
    payload = {"window_start": window_start, "window_end": window_end}
    return get_success_data(
        api_client.claim_order(order_id, payload, make_picker_headers(picker_id))
    )


def pick_line(line_id, picker_id, picked_qty=None, actual_weight_kg=None) -> dict:
    payload = {}
    if picked_qty is not None:
        payload["picked_qty"] = picked_qty
    if actual_weight_kg is not None:
        payload["actual_weight_kg"] = actual_weight_kg
    return get_success_data(
        api_client.pick_order_line(line_id, payload, make_picker_headers(picker_id))
    )


def stage_order(order_id, picker_id) -> dict:
    return get_success_data(
        api_client.stage_order(order_id, make_picker_headers(picker_id))
    )


def capture_order(order_id) -> dict:
    return get_success_data(api_client.capture_order(order_id, OPS))


def handoff_order(order_id) -> dict:
    return get_success_data(api_client.handoff_order(order_id, OPS))


def setup_single_unit_order_picking(unit_price_cents=349, requested_qty=1,
                                    ebt_eligible=None, age_restricted=None,
                                    cold_chain=None, ebt_enabled=None,
                                    snap_ebt_balance_cents=None,
                                    cold_chain_hold_minutes=None,
                                    email="c@example.com"):
    """Store/customer/picker + one UNIT product + cap-1 slot + placed order claimed
    into PICKING. Returns (store, customer, picker, product, slot, order, line_id).
    The single line is left PENDING."""
    store, customer, picker = provision_store_customer_picker(
        ebt_enabled=ebt_enabled, snap_ebt_balance_cents=snap_ebt_balance_cents,
        cold_chain_hold_minutes=cold_chain_hold_minutes, email=email,
    )
    prod_over = {}
    if ebt_eligible is not None:
        prod_over["ebt_eligible"] = ebt_eligible
    if age_restricted is not None:
        prod_over["age_restricted"] = age_restricted
    if cold_chain is not None:
        prod_over["cold_chain"] = cold_chain
    product = create_product(store["id"], unit_price_cents=unit_price_cents, **prod_over)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(
        store["id"], customer["id"], slot["id"], slot["version"],
        [{"product_id": product["id"], "requested_qty": requested_qty}],
    )
    line_id = get_line_ids(order["id"])[0]
    claim_order(order["id"], picker["id"])
    return store, customer, picker, product, slot, order, line_id


def setup_single_unit_order_staged(unit_price_cents=349, requested_qty=1,
                                   picked_qty=1, **kwargs):
    """Drive setup_single_unit_order_picking forward: pick the line then stage.
    Returns (store, customer, picker, product, slot, order, line_id)."""
    store, customer, picker, product, slot, order, line_id = setup_single_unit_order_picking(
        unit_price_cents=unit_price_cents, requested_qty=requested_qty, **kwargs
    )
    pick_line(line_id, picker["id"], picked_qty=picked_qty)
    stage_order(order["id"], picker["id"])
    return store, customer, picker, product, slot, order, line_id


def setup_single_unit_order_captured(unit_price_cents=349, requested_qty=1,
                                     picked_qty=1, **kwargs):
    """Drive forward to a STAGED + CAPTURED order on a single UNIT line.
    Returns (store, customer, picker, product, slot, order, line_id)."""
    store, customer, picker, product, slot, order, line_id = setup_single_unit_order_staged(
        unit_price_cents=unit_price_cents, requested_qty=requested_qty,
        picked_qty=picked_qty, **kwargs
    )
    capture_order(order["id"])
    return store, customer, picker, product, slot, order, line_id
