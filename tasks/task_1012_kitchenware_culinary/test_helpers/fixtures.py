"""Composite setup helpers for multi-step test prerequisites.

The harness restarts the server (and resets the logical clock to its startup
default) before every test, so each helper builds its preconditions from
scratch using only PRD-declared endpoints. get_success_data() (lenient) is used
internally so setup failures surface as clear "setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_store_payload, create_sku_payload, create_member_payload,
    create_order_payload, create_cooking_class_payload,
    create_class_registration_payload, create_service_ticket_payload,
    create_return_payload, create_special_order_payload, order_line,
)
from .test_users import TEST_USERS, make_member_headers

ADMIN = TEST_USERS["admin_headers"]
ASSOC = TEST_USERS["associate_headers"]


# ─── Primitive builders ───────────────────────────────────────
def set_clock(iso: str):
    """Set the server logical clock to the given ISO 8601 instant."""
    return api_client.set_clock({"to_iso8601": iso}, ADMIN)


def make_store(state_code="OR", status=None, name="Test Store") -> dict:
    payload = create_store_payload(name=name, state_code=state_code)
    if status is not None:
        payload["status"] = status
    return get_success_data(api_client.create_store(payload, ADMIN))


def make_sku(list_price_cents=10000, on_hand_qty=10, category="COOKWARE",
             name="Test SKU", status=None, **overrides) -> dict:
    payload = create_sku_payload(name=name, category=category,
                                 list_price_cents=list_price_cents,
                                 on_hand_qty=on_hand_qty, **overrides)
    if status is not None:
        payload["status"] = status
    return get_success_data(api_client.create_sku(payload, ADMIN))


def make_member(home_store_id: str, full_name="Test Member", email=None) -> dict:
    kwargs = {"full_name": full_name}
    if email is not None:
        kwargs["email"] = email
    return get_success_data(
        api_client.create_member(create_member_payload(home_store_id, **kwargs), ADMIN))


def make_order(member_id: str, store_id: str, lines: list,
               fulfillment_type="BOPIS") -> dict:
    return get_success_data(api_client.create_order(
        create_order_payload(member_id, store_id, lines, fulfillment_type=fulfillment_type),
        ADMIN))


def pay_order(order_id: str) -> dict:
    return get_success_data(api_client.pay_order(order_id, ASSOC))


def fulfill_order(order_id: str, exclude_line_ids=None) -> dict:
    payload = {} if exclude_line_ids is None else {"exclude_line_ids": exclude_line_ids}
    return get_success_data(api_client.fulfill_order(order_id, payload, ASSOC))


def cancel_order(order_id: str) -> dict:
    return get_success_data(api_client.cancel_order(order_id, ASSOC))


# ─── Tier 2/3: Order-centric composites ───────────────────────
def setup_store_member_sku(state_code="OR", list_price_cents=10000, on_hand_qty=10,
                           category="COOKWARE", store_status="OPEN", sku_status=None):
    """Active store + one member + one sku. Returns (store, member, sku)."""
    store = make_store(state_code=state_code, status=store_status)
    sku = make_sku(list_price_cents=list_price_cents, on_hand_qty=on_hand_qty,
                   category=category, status=sku_status)
    member = make_member(store["id"])
    return store, member, sku


def setup_reserved_order(state_code="OR", list_price_cents=10000, on_hand_qty=10,
                         qty=1, category="COOKWARE", store_status="OPEN"):
    """store + member + sku + a RESERVED order of one sku line. Returns (store, member, sku, order)."""
    store, member, sku = setup_store_member_sku(
        state_code=state_code, list_price_cents=list_price_cents,
        on_hand_qty=on_hand_qty, category=category, store_status=store_status)
    order = make_order(member["id"], store["id"], [order_line(sku["id"], qty)])
    return store, member, sku, order


def setup_paid_order(state_code="OR", list_price_cents=10000, on_hand_qty=10, qty=1,
                     store_status="OPEN", clock=None):
    """store + member + sku + a PAID (still RESERVED) order. Returns (store, member, sku, order)."""
    if clock:
        set_clock(clock)
    store, member, sku, order = setup_reserved_order(
        state_code=state_code, list_price_cents=list_price_cents,
        on_hand_qty=on_hand_qty, qty=qty, store_status=store_status)
    order = pay_order(order["id"])
    return store, member, sku, order


def setup_fulfilled_order(state_code="OR", list_price_cents=30000, on_hand_qty=5, qty=1,
                          clock="2026-07-05T00:00:00Z"):
    """store + member + sku + a fully FULFILLED order. Returns (store, member, sku, order).
    The single line's line_id is available at order['lines'][0]['line_id']."""
    if clock:
        set_clock(clock)
    store, member, sku, order = setup_reserved_order(
        state_code=state_code, list_price_cents=list_price_cents,
        on_hand_qty=on_hand_qty, qty=qty)
    pay_order(order["id"])
    reserved = order  # keep line ids from create response
    order = fulfill_order(order["id"])
    # ensure line_id retained (fulfill response carries lines too)
    if not order.get("lines"):
        order["lines"] = reserved["lines"]
    return store, member, sku, order


def setup_requested_return(state_code="OR", list_price_cents=30000, on_hand_qty=5,
                           reason="DEFECTIVE", refund_destination="WALLET", return_qty=1,
                           clock="2026-07-05T00:00:00Z"):
    """A FULFILLED order with one REQUESTED return on its single line.
    Returns (store, member, sku, order, ret)."""
    store, member, sku, order = setup_fulfilled_order(
        state_code=state_code, list_price_cents=list_price_cents,
        on_hand_qty=on_hand_qty, qty=1, clock=clock)
    line_id = order["lines"][0]["line_id"]
    ret = get_success_data(api_client.create_return(
        create_return_payload(order["id"], member["id"], line_id,
                              return_qty=return_qty, reason=reason,
                              refund_destination=refund_destination),
        ASSOC))
    return store, member, sku, order, ret


# ─── Cooking class / registration composites ──────────────────
def make_class(store_id, station="DEMO_KITCHEN", start_at="2026-07-20T10:00:00Z",
               end_at="2026-07-20T12:00:00Z", capacity=6, price_cents=5000, title="Test Class"):
    return get_success_data(api_client.create_cooking_class(
        create_cooking_class_payload(store_id, station=station, start_at=start_at,
                                     end_at=end_at, capacity=capacity,
                                     price_cents=price_cents, title=title),
        ASSOC))


def setup_open_class(state_code="NY", station="DEMO_KITCHEN",
                     start_at="2026-07-20T10:00:00Z", end_at="2026-07-20T12:00:00Z",
                     capacity=6, price_cents=5000, clock="2026-07-05T00:00:00Z"):
    """store + an OPEN cooking class. Returns (store, cls)."""
    if clock:
        set_clock(clock)
    store = make_store(state_code=state_code)
    cls = make_class(store["id"], station=station, start_at=start_at, end_at=end_at,
                     capacity=capacity, price_cents=price_cents)
    cls = get_success_data(api_client.open_class(cls["id"], ASSOC))
    return store, cls


def book_registration(class_id, member_id):
    return get_success_data(api_client.create_class_registration(
        create_class_registration_payload(class_id, member_id), ADMIN))


# ─── Service ticket composites ────────────────────────────────
def make_service_ticket(store_id, service_type="KNIFE_SHARPENING",
                        start_at="2026-07-12T09:00:00Z", end_at="2026-07-12T09:30:00Z",
                        price_cents=1500):
    return get_success_data(api_client.create_service_ticket(
        create_service_ticket_payload(store_id, service_type=service_type,
                                      start_at=start_at, end_at=end_at,
                                      price_cents=price_cents),
        ASSOC))


# ─── Special order composites ─────────────────────────────────
def setup_special_order(state_code="NY", estimated_cost_cents=40000,
                        description="Custom item"):
    """store + member + a DRAFT special order (version 1). Returns (store, member, so)."""
    store = make_store(state_code=state_code)
    member = make_member(store["id"])
    so = get_success_data(api_client.create_special_order(
        create_special_order_payload(member["id"], store["id"],
                                     description=description,
                                     estimated_cost_cents=estimated_cost_cents),
        ADMIN))
    return store, member, so


def quote_special_order(so_id, expected_version, quoted_total_cents, deposit_cents=None):
    payload = {"expected_special_order_version": expected_version,
               "quoted_total_cents": quoted_total_cents}
    if deposit_cents is not None:
        payload["deposit_cents"] = deposit_cents
    return get_success_data(api_client.quote_special_order(so_id, payload, ASSOC))
