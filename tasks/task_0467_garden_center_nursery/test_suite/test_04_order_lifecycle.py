"""Order fulfillment/payment dimensions, allocation, fulfill/cancel cascades, OCC.

Difficulty: order_parallel_payment_and_fulfillment_dimensions,
fulfill_depletes_lot_and_finalizes_shrink, cancel_allocated_releases_lot_reservation,
cancel_conserves_lot_unit_count.
Corner: fulfill_unpaid_order_rejected, cancel_fulfilled_order_rejected,
lot_allocation_selector_picks_oldest_received, allocate_insufficient_stock_rejected,
occ_version_increments_on_each_mutation.
"""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error,
    assert_lot_unit_conservation,
    factories as F, fixtures as X,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INV = TEST_USERS["inventory_manager_headers"]
CLERK = TEST_USERS["sales_clerk_headers"]


# ---------------------------------------------------------------------------
# Difficulty: order_parallel_payment_and_fulfillment_dimensions
# ---------------------------------------------------------------------------
def test_pay_advances_payment_without_touching_fulfillment(api):
    """PRD §3.3: "The order carries two independent status dimensions that evolve
    separately and meet only at confirmation: `fulfillment_status` tracks the
    physical progress of the goods, and `payment_status` tracks settlement."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_dimensions
    """
    ctx = X.setup_confirmed_order(unit_price_cents=500, qty=2)
    paid = validate_success(api.pay_order(ctx["order"]["id"], F.version_payload(ctx["version"]), CLERK))
    assert paid["payment_status"] == "PAID"
    assert paid["fulfillment_status"] == "CONFIRMED", "paying must not advance fulfillment"


def test_allocate_advances_fulfillment_without_touching_payment(api):
    """PRD §3.4: "an inventory manager allocates stock to it, advancing
    `fulfillment_status` from `CONFIRMED` to `ALLOCATED`."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_dimensions
    """
    ctx = X.setup_confirmed_order(unit_price_cents=500, qty=2)
    paid = validate_success(api.pay_order(ctx["order"]["id"], F.version_payload(ctx["version"]), CLERK))
    allocated = validate_success(api.allocate_order(ctx["order"]["id"], F.version_payload(paid["version"]), INV))
    assert allocated["fulfillment_status"] == "ALLOCATED"
    assert allocated["payment_status"] == "PAID", "allocating must not change payment"


# ---------------------------------------------------------------------------
# Difficulty: fulfill_depletes_lot_and_finalizes_shrink
# ---------------------------------------------------------------------------
def test_fulfill_converts_reserved_to_sold(api):
    """PRD §3.4: "each line's reserved quantity on its lot is converted to sold:
    the lot's reserved quantity decreases by the line quantity, its sold quantity
    increases by the same".

    Design: Difficulty/transitive_cascade/fulfill_depletes_lot_and_finalizes_shrink
    """
    ctx = X.setup_allocated_order(unit_price_cents=1000, qty=4)
    # whole lot reserved; pay then fulfill consumes it.
    paid = X.pay(ctx["order"]["id"], ctx["version"])
    validate_success(api.fulfill_order(ctx["order"]["id"], F.version_payload(paid["version"]), INV))
    lot = validate_success(api.get_inventory_lot(ctx["lot"]["id"], INV))
    assert lot["sold_qty"] == 4
    assert lot["reserved_qty"] == 0
    # received was max(qty*5,10)=20 so qty_on_hand returns to received - sold.
    assert lot["qty_on_hand"] == lot["received_qty"] - 4


def test_fulfilling_last_units_auto_depletes_lot(api):
    """PRD §3.4: "Any lot whose sellable quantity thereby reaches 0 with no
    remaining reservations auto-transitions from `AVAILABLE` to `DEPLETED`."

    Design: Difficulty/transitive_cascade/fulfill_depletes_lot_and_finalizes_shrink
    """
    # Build an order consuming a whole lot (received_qty exactly == qty).
    nursery = X.create_nursery()
    account = X.create_account(nursery["id"])
    product = X.create_product(nursery["id"], sku="DG-3", name="Bag", unit_price_cents=1000)
    lot = X.create_released_lot(product["id"], received_qty=4, unit_cost_cents=250)
    order = X.create_order(account["id"])
    X.add_line(order["id"], product["id"], qty=4)
    c = X.confirm(order["id"], order["version"])
    a = X.allocate(order["id"], c["version"])
    p = X.pay(order["id"], a["version"])
    validate_success(api.fulfill_order(order["id"], F.version_payload(p["version"]), INV))
    final = validate_success(api.get_inventory_lot(lot["id"], INV))
    assert final["status"] == "DEPLETED"
    assert final["qty_on_hand"] == 0
    assert final["sold_qty"] == 4


# ---------------------------------------------------------------------------
# Difficulty: cancel_allocated_releases_lot_reservation
# ---------------------------------------------------------------------------
def test_cancel_allocated_releases_reservation(api):
    """PRD §3.4: "If the order was `ALLOCATED`, each line's reservation is released
    — the lot's reserved quantity is reduced by the line quantity, the line moves to
    `RELEASED`, and the lot's sellable quantity is recomputed, restoring availability."

    Design: Difficulty/transitive_cascade/cancel_allocated_releases_lot_reservation
    """
    nursery = X.create_nursery()
    account = X.create_account(nursery["id"])
    product = X.create_product(nursery["id"], sku="DG-4", name="Tool", unit_price_cents=800)
    lot = X.create_released_lot(product["id"], received_qty=6, unit_cost_cents=300)
    order = X.create_order(account["id"])
    X.add_line(order["id"], product["id"], qty=6)
    c = X.confirm(order["id"], order["version"])
    a = X.allocate(order["id"], c["version"])  # reserved 6, qty_on_hand 0
    cancelled = validate_success(api.cancel_order(order["id"], F.version_payload(a["version"]), CLERK))
    assert cancelled["fulfillment_status"] == "CANCELLED"
    final = validate_success(api.get_inventory_lot(lot["id"], INV))
    assert final["reserved_qty"] == 0
    assert final["qty_on_hand"] == 6


def test_cancel_allocated_lot_not_depleted(api):
    """PRD §3.2: "When a lot's sellable quantity reaches exactly 0 while it holds no
    reservations, the server automatically and irreversibly transitions it to
    `DEPLETED`".

    Design: Difficulty/transitive_cascade/cancel_allocated_releases_lot_reservation
    """
    nursery = X.create_nursery()
    account = X.create_account(nursery["id"])
    product = X.create_product(nursery["id"], sku="DG-4b", name="Tool2", unit_price_cents=800)
    lot = X.create_released_lot(product["id"], received_qty=6, unit_cost_cents=300)
    order = X.create_order(account["id"])
    X.add_line(order["id"], product["id"], qty=6)
    c = X.confirm(order["id"], order["version"])
    a = X.allocate(order["id"], c["version"])
    validate_success(api.cancel_order(order["id"], F.version_payload(a["version"]), CLERK))
    final = validate_success(api.get_inventory_lot(lot["id"], INV))
    assert final["status"] == "AVAILABLE", "units restored, not depleted"


# ---------------------------------------------------------------------------
# Difficulty: cancel_conserves_lot_unit_count
# ---------------------------------------------------------------------------
def test_cancel_conserves_physical_lot_units(api):
    """PRD §3.4: "If the order was `ALLOCATED`, each line's reservation is released
    — the lot's reserved quantity is reduced by the line quantity, the line moves to
    `RELEASED`, and the lot's sellable quantity is recomputed, restoring availability."

    Design: Difficulty/compensating_invariant/cancel_conserves_lot_unit_count
    """
    nursery = X.create_nursery()
    account = X.create_account(nursery["id"])
    product = X.create_product(nursery["id"], sku="DG-11", name="Sand", unit_price_cents=700)
    lot = X.create_released_lot(product["id"], received_qty=6, unit_cost_cents=200)
    order = X.create_order(account["id"])
    X.add_line(order["id"], product["id"], qty=6)
    c = X.confirm(order["id"], order["version"])
    a = X.allocate(order["id"], c["version"])
    validate_success(api.cancel_order(order["id"], F.version_payload(a["version"]), CLERK))
    final = validate_success(api.get_inventory_lot(lot["id"], INV))
    assert final["qty_on_hand"] == 6
    assert final["reserved_qty"] == 0
    assert final["shrink_qty"] == 0
    assert final["sold_qty"] == 0


def test_cancel_lot_invariant_zero_drift(api):
    """PRD §3.2: "The sellable quantity is always derived as the received quantity
    less reserved, less shrink, less sold units."

    Design: Difficulty/compensating_invariant/cancel_conserves_lot_unit_count
    """
    nursery = X.create_nursery()
    account = X.create_account(nursery["id"])
    product = X.create_product(nursery["id"], sku="DG-11b", name="Sand2", unit_price_cents=700)
    lot = X.create_released_lot(product["id"], received_qty=6, unit_cost_cents=200)
    order = X.create_order(account["id"])
    X.add_line(order["id"], product["id"], qty=6)
    c = X.confirm(order["id"], order["version"])
    a = X.allocate(order["id"], c["version"])
    validate_success(api.cancel_order(order["id"], F.version_payload(a["version"]), CLERK))
    final = validate_success(api.get_inventory_lot(lot["id"], INV))
    assert_lot_unit_conservation(final)
    assert final["received_qty"] == 6


# ---------------------------------------------------------------------------
# Corner: fulfillment preconditions and allocation
# ---------------------------------------------------------------------------
def test_fulfill_unpaid_order_rejected(api):
    """PRD §3.4: "It is permitted only when the order has been settled — its
    `payment_status` is either `ON_ACCOUNT` or `PAID` (otherwise
    `ERR_ORDER_NOT_SETTLED`)".

    Design: Corner/state_machines/fulfill_unpaid_order_rejected
    """
    ctx = X.setup_allocated_order(unit_price_cents=900, qty=2)  # never paid
    resp = api.fulfill_order(ctx["order"]["id"], F.version_payload(ctx["version"]), INV)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_SETTLED.value)


def test_cancel_fulfilled_order_rejected(api):
    """PRD §3.4: "An order may be cancelled by a sales clerk from any non-terminal
    fulfillment state — `DRAFT`, `CONFIRMED`, or `ALLOCATED` — as long as it has not
    already been fulfilled (otherwise `ERR_ORDER_ALREADY_FULFILLED`)".

    Design: Corner/state_machines/cancel_fulfilled_order_rejected
    """
    ctx = X.setup_fulfilled_order(unit_price_cents=600, qty=2)
    resp = api.cancel_order(ctx["order"]["id"], F.version_payload(ctx["version"]), CLERK)
    validate_error(resp, ApiErrorId.ERR_ORDER_ALREADY_FULFILLED.value)


def test_allocate_picks_oldest_received_lot(api):
    """PRD §3.4: "Candidates are ranked oldest-received first by ascending
    `created_at` ... The first ranked lot is chosen. The line's `allocated_lot_id`
    is set to that lot".

    Design: Corner/endpoints/lot_allocation_selector_picks_oldest_received
    """
    nursery = X.create_nursery()
    account = X.create_account(nursery["id"])
    product = X.create_product(nursery["id"], sku="DG-SEL", name="Clip", unit_price_cents=100)
    lot1 = X.create_released_lot(product["id"], received_qty=10, unit_cost_cents=50)
    lot2 = X.create_released_lot(product["id"], received_qty=10, unit_cost_cents=50)
    order = X.create_order(account["id"])
    line = X.add_line(order["id"], product["id"], qty=3)
    c = X.confirm(order["id"], order["version"])
    validate_success(api.allocate_order(order["id"], F.version_payload(c["version"]), INV))
    fetched_line = validate_success(api.get_order_line(line["id"], INV))
    assert fetched_line["allocated_lot_id"] == lot1["id"]
    refreshed = validate_success(api.get_inventory_lot(lot1["id"], INV))
    assert refreshed["reserved_qty"] == 3


def test_allocate_insufficient_stock_rejected(api):
    """PRD §3.4: "Allocation requires that every line be satisfiable from a single
    `AVAILABLE` lot of its product whose sellable quantity is at least the line's
    quantity (otherwise `ERR_INSUFFICIENT_STOCK`)".

    Design: Corner/validations/allocate_insufficient_stock_rejected
    """
    nursery = X.create_nursery()
    account = X.create_account(nursery["id"])
    product = X.create_product(nursery["id"], sku="DG-IS", name="Twig", unit_price_cents=100)
    X.create_released_lot(product["id"], received_qty=4, unit_cost_cents=50)
    X.create_released_lot(product["id"], received_qty=4, unit_cost_cents=50)  # 8 total, no single lot >= 10
    order = X.create_order(account["id"])
    X.add_line(order["id"], product["id"], qty=10)
    c = X.confirm(order["id"], order["version"])
    resp = api.allocate_order(order["id"], F.version_payload(c["version"]), INV)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK.value)


def test_order_version_increments_on_confirm(api):
    """PRD §2.5: "`version` — an integer that starts at its initial value and
    increments by one on every mutation of the resource."
    PRD §3.3: "advances the order to `CONFIRMED`, and increments the order's
    `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_each_mutation
    """
    nursery = X.create_nursery()
    account = X.create_account(nursery["id"])
    product = X.create_product(nursery["id"], sku="DG-VER", name="Nut", unit_price_cents=300)
    order = X.create_order(account["id"])
    X.add_line(order["id"], product["id"], qty=1)
    before = validate_success(api.get_order(order["id"], CLERK))["version"]
    confirmed = validate_success(api.confirm_order(order["id"], F.confirm_payload(before), CLERK))
    assert confirmed["version"] == before + 1, "confirm increments version by exactly one"
