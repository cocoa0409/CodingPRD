"""Order parallel state axes, ship cascade, recall cascade, refund/loyalty invariants.

Difficulty queue: non_linear_state_machine (parallel axes), transitive_cascade,
cross_entity_state_dependency, compensating_invariant.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_order_payload, create_order_line_payload, pay_order_payload,
    create_active_sku_with_lot, create_customer, create_active_subscription,
    build_reserved_order, build_paid_reserved_order,
    make_customer_headers, TEST_USERS, ApiErrorId,
)

INV = TEST_USERS["inventory_manager_headers"]
COMP = TEST_USERS["compliance_officer_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ───────────────────────── parallel payment x fulfillment axes ─────────────────────────

def test_order_axes_advance_independently(api):
    """PRD §3.3: "A new order opens with payment_status UNPAID and fulfillment_status DRAFT;
    the two axes move independently, as described in §3.4 and §3.5."
    PRD §3.4: "From UNPAID, a succeeded outcome moves the order UNPAID → PAID"

    Design: Difficulty/non_linear_state_machine/nonlinear_order_parallel_payment_fulfillment
    """
    sku, _ = create_active_sku_with_lot(name="Cold Sauce", category="HOT_SAUCE",
                                        storage_class="AMBIENT", unit_price_cents=1200,
                                        produced_units=10)
    cust = create_customer(home_zone="Z1")
    cid = cust["id"]
    order = get_success_data(api.create_order(
        create_order_payload(cid, order_kind="ONE_TIME", ship_zone="Z1"), make_customer_headers(cid)))
    api.add_order_line(order["id"], create_order_line_payload(sku["id"], 1), make_customer_headers(cid))
    # Pay first (payment axis advances), then reserve (fulfillment axis advances separately).
    api.pay_order(order["id"], pay_order_payload("SUCCEEDED"), make_customer_headers(cid))
    reserved = validate_success(api.reserve_order(order["id"], make_customer_headers(cid)), 200)
    assert reserved["payment_status"] == "PAID"
    assert reserved["fulfillment_status"] == "RESERVED"


def test_payment_failed_axis_does_not_block_reservation(api):
    """PRD §3.4: "a declined outcome moves it UNPAID → FAILED."
    PRD §3.3: "the two axes move independently"

    Design: Difficulty/non_linear_state_machine/nonlinear_order_parallel_payment_fulfillment
    """
    sku, _ = create_active_sku_with_lot(name="Decl Sauce", category="HOT_SAUCE",
                                        storage_class="AMBIENT", unit_price_cents=1200,
                                        produced_units=10)
    cust = create_customer(home_zone="Z1")
    cid = cust["id"]
    order = get_success_data(api.create_order(
        create_order_payload(cid, order_kind="ONE_TIME", ship_zone="Z1"), make_customer_headers(cid)))
    api.add_order_line(order["id"], create_order_line_payload(sku["id"], 1), make_customer_headers(cid))
    failed = validate_success(api.pay_order(order["id"], pay_order_payload("DECLINED"),
                                            make_customer_headers(cid)), 200)
    assert failed["payment_status"] == "FAILED"
    reserved = validate_success(api.reserve_order(order["id"], make_customer_headers(cid)), 200)
    assert reserved["fulfillment_status"] == "RESERVED"


# ───────────────────────── ship cascade hop1->hop2->hop3 ─────────────────────────

def test_ship_cascade_depletes_lot_sku_and_autopauses_subscription(api):
    """PRD §3.5: "each line moves PENDING → COMMITTED and its drawn lot's remaining_units is
    decremented by the line quantity (hop 1); the SKU's reserved_units is decremented by the
    line quantity and its available_units is recomputed (hop 2); and if a SKU's available_units
    lands at zero, every ACTIVE subscription on that SKU auto-pauses (hop 3)."

    Design: Difficulty/transitive_cascade/cascade_ship_lot_sku_subscription_autopause
    """
    sku, lot = create_active_sku_with_lot(name="Last Sauce", category="HOT_SAUCE",
                                          storage_class="AMBIENT", unit_price_cents=1000,
                                          produced_units=2)
    cust = create_customer(home_zone="Z1")
    cid = cust["id"]
    sub = create_active_subscription(cid, sku["id"], tier="STARTER", cadence_days=14)
    order = build_paid_reserved_order(cid, [(sku["id"], 2)])
    validate_success(api.ship_order(order["id"], INV), 200)

    lot_after = validate_success(api.get_lot(lot["id"], INV), 200)
    assert lot_after["remaining_units"] == 0, "hop1: lot decremented to 0"
    sku_after = validate_success(api.get_sku(sku["id"], INV), 200)
    assert sku_after["available_units"] == 0, "hop2: SKU availability recomputed to 0"
    sub_after = validate_success(api.get_subscription(sub["id"], make_customer_headers(cid)), 200)
    assert sub_after["status"] == "PAUSED", "hop3: ACTIVE subscription auto-paused"


def test_ship_decrements_lot_remaining_units(api):
    """PRD §3.5: "each line moves PENDING → COMMITTED and its drawn lot's remaining_units is
    decremented by the line quantity (hop 1)"

    Design: Difficulty/transitive_cascade/cascade_ship_lot_sku_subscription_autopause
    """
    sku, lot = create_active_sku_with_lot(name="Decr Sauce", category="HOT_SAUCE",
                                          storage_class="AMBIENT", unit_price_cents=1000,
                                          produced_units=10)
    cust = create_customer(home_zone="Z1")
    cid = cust["id"]
    order = build_paid_reserved_order(cid, [(sku["id"], 3)])
    validate_success(api.ship_order(order["id"], INV), 200)
    lot_after = validate_success(api.get_lot(lot["id"], INV), 200)
    assert lot_after["remaining_units"] == 7, "10 produced - 3 committed"


# ───────────────────────── recall cascade hop1->hop2 ─────────────────────────

def test_recall_depletes_sku_and_autopauses_subscription(api):
    """PRD §3.2: "recall sets the lot's remaining_units to 0, recomputes the parent SKU's
    available_units, and if that availability reaches zero, auto-pauses every ACTIVE
    subscription on that SKU."

    Design: Difficulty/transitive_cascade/cascade_recall_sku_subscription_autopause
    """
    sku, lot = create_active_sku_with_lot(name="Recall Coffee", category="COFFEE",
                                          storage_class="AMBIENT", unit_price_cents=1000,
                                          produced_units=5)
    cust = create_customer(home_zone="Z1")
    cid = cust["id"]
    sub = create_active_subscription(cid, sku["id"], tier="STARTER", cadence_days=14)
    validate_success(api.recall_lot(lot["id"], COMP), 200)

    sku_after = validate_success(api.get_sku(sku["id"], INV), 200)
    assert sku_after["available_units"] == 0, "hop1: availability recomputed to 0 on recall"
    sub_after = validate_success(api.get_subscription(sub["id"], make_customer_headers(cid)), 200)
    assert sub_after["status"] == "PAUSED", "hop2: ACTIVE subscription auto-paused"


def test_recall_zeroes_lot_remaining_units(api):
    """PRD §3.2: "recall sets the lot's remaining_units to 0"

    Design: Difficulty/transitive_cascade/cascade_recall_sku_subscription_autopause
    """
    sku, lot = create_active_sku_with_lot(name="Recall2 Coffee", category="COFFEE",
                                          storage_class="AMBIENT", unit_price_cents=1000,
                                          produced_units=5)
    recalled = validate_success(api.recall_lot(lot["id"], COMP), 200)
    assert recalled["status"] == "RECALLED"
    assert recalled["remaining_units"] == 0


# ───────────────────────── cross-entity: ship requires paid ─────────────────────────

def test_ship_unpaid_reserved_order_rejected(api):
    """PRD §3.5: "Shipping is an InventoryManager action that moves an order RESERVED → SHIPPED
    and is the point at which the reserve-then-commit lifecycle commits. Shipping requires that
    the order's payment_status is PAID"

    Design: Difficulty/cross_entity_state_dependency/cross_entity_ship_requires_order_paid
    """
    sku, _ = create_active_sku_with_lot(name="Pay Sauce", category="HOT_SAUCE",
                                        storage_class="AMBIENT", unit_price_cents=1000,
                                        produced_units=5)
    cust = create_customer(home_zone="Z1")
    cid = cust["id"]
    order = build_reserved_order(cid, [(sku["id"], 1)])  # reserved but UNPAID
    res = api.ship_order(order["id"], INV)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_ship_paid_reserved_order_succeeds(api):
    """PRD §3.5: "Shipping is an InventoryManager action that moves an order RESERVED → SHIPPED"

    Design: Difficulty/cross_entity_state_dependency/cross_entity_ship_requires_order_paid
    """
    sku, _ = create_active_sku_with_lot(name="Pay2 Sauce", category="HOT_SAUCE",
                                        storage_class="AMBIENT", unit_price_cents=1000,
                                        produced_units=5)
    cust = create_customer(home_zone="Z1")
    cid = cust["id"]
    order = build_paid_reserved_order(cid, [(sku["id"], 1)])
    shipped = validate_success(api.ship_order(order["id"], INV), 200)
    assert shipped["fulfillment_status"] == "SHIPPED"


# ───────────────────────── compensating invariants ─────────────────────────

def test_cancel_paid_reserved_refunds_to_wallet(api):
    """PRD §3.5: "If that cancelled order had been paid, the same compensation as §3.4
    applies — its payment axis moves to REFUNDED and total_cents is added to the customer's
    wallet_credit_cents."

    Design: Difficulty/compensating_invariant/invariant_cancel_refund_wallet_conserved
    """
    sku, _ = create_active_sku_with_lot(name="Ref Sauce", category="HOT_SAUCE",
                                        storage_class="AMBIENT", unit_price_cents=1000,
                                        produced_units=5)
    cust = create_customer(home_zone="Z1")
    cid = cust["id"]
    order = build_paid_reserved_order(cid, [(sku["id"], 1)])
    total = order["total_cents"]
    cancelled = validate_success(api.cancel_order(order["id"], make_customer_headers(cid)), 200)
    assert cancelled["payment_status"] == "REFUNDED"
    cust_after = validate_success(api.get_customer(cid, make_customer_headers(cid)), 200)
    assert cust_after["wallet_credit_cents"] == total, "refund equals the charge; money conserved"


def test_cancel_paid_reserved_moves_payment_to_refunded(api):
    """PRD §3.4: "If the order is PAID and is cancelled while its fulfillment_status is DRAFT
    or RESERVED, the payment axis moves PAID → REFUNDED and the order's total_cents is added to
    the customer's wallet_credit_cents. REFUNDED is the terminal payment state."

    Design: Difficulty/compensating_invariant/invariant_cancel_refund_wallet_conserved
    """
    sku, _ = create_active_sku_with_lot(name="Ref2 Sauce", category="HOT_SAUCE",
                                        storage_class="AMBIENT", unit_price_cents=1500,
                                        produced_units=5)
    cust = create_customer(home_zone="Z1")
    cid = cust["id"]
    order = build_paid_reserved_order(cid, [(sku["id"], 1)])
    cancelled = validate_success(api.cancel_order(order["id"], make_customer_headers(cid)), 200)
    assert cancelled["payment_status"] == "REFUNDED"
    assert cancelled["fulfillment_status"] == "CANCELLED"
    # Wallet credit exactly equals the order's frozen total (no drift).
    cust_after = validate_success(api.get_customer(cid, make_customer_headers(cid)), 200)
    assert cust_after["wallet_credit_cents"] == order["total_cents"]


def test_cancel_before_ship_leaves_loyalty_unchanged(api):
    """PRD §3.5: "Because loyalty points are credited only on shipment, a cancellation before
    shipment leaves the customer's loyalty balance unchanged; nothing is reversed."

    Design: Difficulty/compensating_invariant/invariant_cancel_before_ship_loyalty_conserved
    """
    sku, _ = create_active_sku_with_lot(name="Loy Sauce", category="HOT_SAUCE",
                                        storage_class="AMBIENT", unit_price_cents=2000,
                                        produced_units=5)
    cust = create_customer(home_zone="Z1")
    cid = cust["id"]
    order = build_reserved_order(cid, [(sku["id"], 1)])  # reserved, never shipped
    cancelled = validate_success(api.cancel_order(order["id"], make_customer_headers(cid)), 200)
    assert cancelled["fulfillment_status"] == "CANCELLED"
    cust_after = validate_success(api.get_customer(cid, make_customer_headers(cid)), 200)
    assert cust_after["loyalty_points_balance"] == 0, "no points ever credited; cancel reverses nothing"


def test_cancel_reserved_releases_lines_without_loyalty_change(api):
    """PRD §3.5: "Cancelling a RESERVED order moves it RESERVED → CANCELLED and unwinds the
    reservation: every line moves from PENDING to RELEASED (line_status) and the SKU's
    reserved_units is reduced by the line quantity, with no lot decrement because nothing was
    committed."
    PRD §3.5: "Because loyalty points are credited only on shipment, a cancellation before
    shipment leaves the customer's loyalty balance unchanged; nothing is reversed."

    Design: Difficulty/compensating_invariant/invariant_cancel_before_ship_loyalty_conserved
    """
    sku, _ = create_active_sku_with_lot(name="Loy2 Sauce", category="HOT_SAUCE",
                                        storage_class="AMBIENT", unit_price_cents=2000,
                                        produced_units=5)
    cust = create_customer(home_zone="Z1")
    cid = cust["id"]
    order = build_reserved_order(cid, [(sku["id"], 2)])
    sku_reserved = validate_success(api.get_sku(sku["id"], INV), 200)
    assert sku_reserved["reserved_units"] == 2
    validate_success(api.cancel_order(order["id"], make_customer_headers(cid)), 200)
    sku_after = validate_success(api.get_sku(sku["id"], INV), 200)
    assert sku_after["reserved_units"] == 0, "reservation freed on cancel"
    cust_after = validate_success(api.get_customer(cid, make_customer_headers(cid)), 200)
    assert cust_after["loyalty_points_balance"] == 0, "loyalty conserved; nothing accrued or reversed"
