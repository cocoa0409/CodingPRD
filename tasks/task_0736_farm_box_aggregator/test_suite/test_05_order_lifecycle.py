"""Order and market-cycle lifecycle state preconditions.

Difficulty instances: cross_entity_state_dependency (checkout gated on cycle; fulfill gated
on all lines). Corner instances: empty-order checkout, settle-with-open-orders,
cancel-after-pack, re-open a cycle.
"""
from test_helpers import (
    validate_error, ApiErrorId,
    make_admin_headers, make_customer_headers,
    set_clock, new_hub, new_customer, new_cycle, open_cycle, new_order, new_line,
    do_checkout, do_pack, cutoff_cycle,
    setup_open_egg_market, setup_allocated_egg_line,
)


def _order(api, order_id):
    return api.get_order(order_id, make_admin_headers()).json()["data"]


def _line(api, line_id):
    return api.get_line(line_id, make_admin_headers()).json()["data"]


def _cycle(api, cycle_id):
    return api.get_cycle(cycle_id, make_admin_headers()).json()["data"]


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / checkout_requires_cycle_open_order_vs_cycle
# ---------------------------------------------------------------------------
def _cart_order_in_cutoff_cycle(api):
    world = setup_open_egg_market(api, snap_balance=0)
    order = new_order(api, world["customer"]["id"], world["cycle"]["id"], world["hub"]["id"])
    new_line(api, world["customer"]["id"], order["id"], world["offering"]["id"], 1)
    cutoff_cycle(api, world["cycle"]["id"])  # order stays CART (only PLACED orders allocate)
    world["order"] = order
    return world


def test_checkout_after_cutoff_rejected_cycle_not_open(api):
    """PRD §3.6: "The acting customer must own the order, the order must currently be in `CART`,
    and the cycle must be `OPEN` (else `ERR_CYCLE_NOT_OPEN`)."

    Design: Difficulty/cross_entity_state_dependency/checkout_requires_cycle_open_order_vs_cycle
    """
    world = _cart_order_in_cutoff_cycle(api)
    resp = api.checkout_order(world["order"]["id"], world["cust_headers"])
    validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_OPEN.value, 409)


def test_checkout_after_cutoff_leaves_order_in_cart(api):
    """PRD §3.2: "After cutoff, attempts to create an order, add a line, or check out in that
    cycle are rejected with `ERR_CYCLE_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/checkout_requires_cycle_open_order_vs_cycle
    """
    world = _cart_order_in_cutoff_cycle(api)
    api.checkout_order(world["order"]["id"], world["cust_headers"])
    assert _order(api, world["order"]["id"])["order_status"] == "CART"


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / fulfill_requires_all_lines_packed_order_vs_line
# ---------------------------------------------------------------------------
def _allocated_order_one_of_two_packed(api):
    world = setup_open_egg_market(api, snap_balance=0)
    order = new_order(api, world["customer"]["id"], world["cycle"]["id"], world["hub"]["id"])
    line1 = new_line(api, world["customer"]["id"], order["id"], world["offering"]["id"], 1)
    line2 = new_line(api, world["customer"]["id"], order["id"], world["offering"]["id"], 1)
    do_checkout(api, world["customer"]["id"], order["id"])
    cutoff_cycle(api, world["cycle"]["id"])
    do_pack(api, world["farm"]["id"], line1["id"], fulfilled_qty=1)  # line2 left ALLOCATED
    world["order"] = order
    world["line2"] = line2
    return world


def test_fulfill_with_unpacked_line_rejected(api):
    """PRD §3.8: "Attempting to fulfill while some line is not yet packed is rejected with
    `ERR_LINES_NOT_PACKED`."

    Design: Difficulty/cross_entity_state_dependency/fulfill_requires_all_lines_packed_order_vs_line
    """
    world = _allocated_order_one_of_two_packed(api)
    resp = api.fulfill_order(world["order"]["id"], make_admin_headers())
    validate_error(resp, ApiErrorId.ERR_LINES_NOT_PACKED.value, 409)


def test_fulfill_rejection_leaves_order_and_line_allocated(api):
    """PRD §3.8: "Once every line of an `ALLOCATED` order is in a terminal packout state —
    `PACKED`, `SUBSTITUTED`, or `SHORTED` — a `Farm` or `PlatformAdmin` fulfills the order,
    advancing it `ALLOCATED → FULFILLED` and moving each of those lines to `FULFILLED`; a shorted
    line carries its (possibly zero) `fulfilled_qty` forward."

    Design: Difficulty/cross_entity_state_dependency/fulfill_requires_all_lines_packed_order_vs_line
    """
    world = _allocated_order_one_of_two_packed(api)
    api.fulfill_order(world["order"]["id"], make_admin_headers())
    assert _order(api, world["order"]["id"])["order_status"] == "ALLOCATED"
    assert _line(api, world["line2"]["id"])["line_status"] == "ALLOCATED"


# ---------------------------------------------------------------------------
# Corner: validations / checkout_empty_order_rejected
# ---------------------------------------------------------------------------
def test_checkout_empty_order_rejected(api):
    """PRD §3.6: "An order with no lines cannot be checked out and is rejected with
    `ERR_EMPTY_ORDER`."

    Design: Corner/validations/checkout_empty_order_rejected
    """
    set_clock(api)
    hub = new_hub(api)
    customer = new_customer(api, snap_balance_cents=0)
    cycle = new_cycle(api)
    open_cycle(api, cycle["id"])
    order = new_order(api, customer["id"], cycle["id"], hub["id"])

    resp = api.checkout_order(order["id"], make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_EMPTY_ORDER.value, 409)
    assert _order(api, order["id"])["order_status"] == "CART"


# ---------------------------------------------------------------------------
# Corner: validations / settle_cycle_with_open_orders_rejected
# ---------------------------------------------------------------------------
def test_settle_cycle_with_open_orders_rejected(api):
    """PRD §3.2: "Settling a cycle is permitted only from `CUTOFF`, and only once every order in
    the cycle has reached `FULFILLED` or `CANCELLED`; if any order is still open, settlement is
    rejected with `ERR_CYCLE_HAS_OPEN_ORDERS`."

    Design: Corner/validations/settle_cycle_with_open_orders_rejected
    """
    world = setup_allocated_egg_line(api, requested_qty=1)  # order left ALLOCATED (unfulfilled)
    resp = api.settle_cycle(world["cycle"]["id"], make_admin_headers())
    validate_error(resp, ApiErrorId.ERR_CYCLE_HAS_OPEN_ORDERS.value, 409)
    assert _cycle(api, world["cycle"]["id"])["status"] == "CUTOFF"


# ---------------------------------------------------------------------------
# Corner: validations / cancel_allocated_order_after_pack_rejected
# ---------------------------------------------------------------------------
def test_cancel_allocated_order_after_pack_rejected(api):
    """PRD §3.8: "An allocated order cannot be cancelled once any of its lines is already
    `PACKED`, `SUBSTITUTED`, `SHORTED`, or `FULFILLED`; such a request is rejected with
    `ERR_ORDER_IN_PACKOUT`."

    Design: Corner/validations/cancel_allocated_order_after_pack_rejected
    """
    world = setup_open_egg_market(api, snap_balance=0)
    order = new_order(api, world["customer"]["id"], world["cycle"]["id"], world["hub"]["id"])
    line1 = new_line(api, world["customer"]["id"], order["id"], world["offering"]["id"], 1)
    new_line(api, world["customer"]["id"], order["id"], world["offering"]["id"], 1)
    do_checkout(api, world["customer"]["id"], order["id"])
    cutoff_cycle(api, world["cycle"]["id"])
    do_pack(api, world["farm"]["id"], line1["id"], fulfilled_qty=1)

    resp = api.cancel_order(order["id"], make_admin_headers())
    validate_error(resp, ApiErrorId.ERR_ORDER_IN_PACKOUT.value, 409)
    assert _order(api, order["id"])["order_status"] == "ALLOCATED"


# ---------------------------------------------------------------------------
# Corner: state_machines / open_already_open_cycle_rejected
# ---------------------------------------------------------------------------
def test_open_already_open_cycle_rejected(api):
    """PRD §3.2: "Each transition requires the cycle to currently hold the expected predecessor
    state; an out-of-order attempt is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/open_already_open_cycle_rejected
    """
    set_clock(api)
    cycle = new_cycle(api)
    open_cycle(api, cycle["id"])
    resp = api.open_cycle(cycle["id"], make_admin_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    assert _cycle(api, cycle["id"])["status"] == "OPEN"
