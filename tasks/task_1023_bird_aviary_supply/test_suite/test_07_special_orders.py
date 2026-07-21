"""Special orders: parallel axes, inventory/wallet conservation, priority conflict."""
from test_helpers import (
    validate_success, validate_error,
    new_customer, new_inventory, new_special_order, setup_paid_cancelled_order,
    make_customer_headers, TEST_USERS,
    create_subscription_payload,
)

SM = TEST_USERS["store_manager_headers"]


# ── non_linear_state_machine: parallel payment x build axes ──────────────────

def test_pay_advances_payment_axis_only(api):
    """PRD 3.8: "The owning customer pays an order, moving payment_status from UNPAID to
    PAID."
    PRD 3.8: "A new order begins with payment_status UNPAID and build_status QUEUED."
    PRD 3.8: "The two axes are independent except where a rule explicitly crosses them."

    Design: Difficulty/non_linear_state_machine/special_order_parallel_payment_build_axes
    """
    cust = new_customer(wallet_cents=2000)
    inv = new_inventory("DRY", on_hand=5)
    order = new_special_order(cust["id"], inv["id"], build_qty=1,
                              line_items=[{"unit_price_cents": 1000, "quantity": 1, "tax_rate": 0.0}])
    paid = validate_success(api.pay_order(order["id"], make_customer_headers(cust["id"])), 200)
    assert paid["payment_status"] == "PAID"
    assert paid["build_status"] == "QUEUED"  # build axis untouched


def test_start_build_advances_build_axis_only(api):
    """PRD 3.8: "Starting a build moves build_status from QUEUED to IN_BUILD".
    PRD 3.8: "The two axes are independent except where a rule explicitly crosses them."

    Design: Difficulty/non_linear_state_machine/special_order_parallel_payment_build_axes
    """
    cust = new_customer(wallet_cents=2000)
    inv = new_inventory("DRY", on_hand=5)
    order = new_special_order(cust["id"], inv["id"], build_qty=1,
                              line_items=[{"unit_price_cents": 1000, "quantity": 1, "tax_rate": 0.0}])
    validate_success(api.pay_order(order["id"], make_customer_headers(cust["id"])), 200)
    built = validate_success(api.start_build(order["id"], SM), 200)
    assert built["build_status"] == "IN_BUILD"
    assert built["payment_status"] == "PAID"  # payment axis untouched


# ── compensating_invariant: inventory units conserved on cancel-build ────────

def test_create_order_allocates_build_units(api):
    """PRD 3.8: "On creation the order allocates build_qty units of the cage_item_id
    inventory item under the conservation rule (reserving from quantity_on_hand into
    quantity_allocated, with ERR_INSUFFICIENT_INVENTORY if stock is short)".
    PRD 2.9: "To allocate n units, the system subtracts n from quantity_on_hand and adds
    n to quantity_allocated."

    Design: Difficulty/compensating_invariant/inventory_units_conserved_on_cancel_build
    """
    cust = new_customer()
    inv = new_inventory("DRY", on_hand=10)
    new_special_order(cust["id"], inv["id"], build_qty=3,
                      line_items=[{"unit_price_cents": 1000, "quantity": 1, "tax_rate": 0.0}])
    after = validate_success(api.get_inventory_item(inv["id"], SM), 200)
    assert after["quantity_on_hand"] == 7
    assert after["quantity_allocated"] == 3
    assert after["quantity_on_hand"] + after["quantity_allocated"] == 10


def test_cancel_build_releases_units(api):
    """PRD 3.8: "Cancelling a build is permitted while build_status is QUEUED or IN_BUILD,
    moving it to the terminal CANCELLED and releasing the build allocation as an exact
    reversal of the create-time allocation: build_qty units move from quantity_allocated
    back to quantity_on_hand."

    Design: Difficulty/compensating_invariant/inventory_units_conserved_on_cancel_build
    """
    cust = new_customer()
    inv = new_inventory("DRY", on_hand=10)
    order = new_special_order(cust["id"], inv["id"], build_qty=3,
                              line_items=[{"unit_price_cents": 1000, "quantity": 1, "tax_rate": 0.0}])
    validate_success(api.cancel_build(order["id"], SM), 200)
    after = validate_success(api.get_inventory_item(inv["id"], SM), 200)
    assert after["quantity_on_hand"] == 10
    assert after["quantity_allocated"] == 0
    assert after["quantity_on_hand"] + after["quantity_allocated"] == 10


# ── compensating_invariant: wallet conserved on order refund ─────────────────

def test_refund_restores_wallet(api):
    """PRD 3.8: "A StoreManager refunds a paid order, moving payment_status from PAID to
    REFUNDED; a refund is permitted only when the payment_status is PAID and the
    build_status is CANCELLED (only cancelled builds are refundable), and it credits
    invoice_total_cents back to the wallet as an exact compensation reversal of the
    payment debit."

    Design: Difficulty/compensating_invariant/wallet_credits_conserved_on_order_refund
    """
    ctx = setup_paid_cancelled_order(wallet_cents=5000)
    refunded = validate_success(api.refund_order(ctx["order"]["id"], SM), 200)
    assert refunded["payment_status"] == "REFUNDED"
    cust = validate_success(api.get_customer(ctx["customer"]["id"], SM), 200)
    assert cust["wallet_credit_cents"] == 5000


def test_pay_then_refund_conserves_wallet(api):
    """PRD 3.8: "Payment debits invoice_total_cents from the wallet."
    PRD 3.8: "it credits invoice_total_cents back to the wallet as an exact compensation
    reversal of the payment debit."

    Design: Difficulty/compensating_invariant/wallet_credits_conserved_on_order_refund
    """
    ctx = setup_paid_cancelled_order(wallet_cents=5000)
    mid = validate_success(api.get_customer(ctx["customer"]["id"], SM), 200)
    assert mid["wallet_credit_cents"] == 4000  # 5000 - 1000 pay debit
    validate_success(api.refund_order(ctx["order"]["id"], SM), 200)
    after = validate_success(api.get_customer(ctx["customer"]["id"], SM), 200)
    assert after["wallet_credit_cents"] == 5000  # 1000 refund exactly reverses the debit


# ── priority_pair_validation_conflict: inventory beats wallet ────────────────

def test_subscription_inventory_shortage_beats_wallet(api):
    """PRD 2.1: "the first failing check determines the error returned."
    PRD 2.1: "(13) inventory sufficiency; (14) wallet sufficiency"
    PRD 2.9: "Before any allocation, the system verifies that quantity_on_hand is at least
    the number of units requested; if it is not, the allocation is rejected with
    ERR_INSUFFICIENT_INVENTORY (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/subscription_inventory_beats_wallet_fiscal
    """
    cust = new_customer(wallet_cents=0)
    inv = new_inventory("FRESH", on_hand=1)  # short: need 2 for bird_count 2
    res = api.create_subscription(
        create_subscription_payload(cust["id"], tier="PREMIUM", bird_count=2,
                                    fresh_feed=True, fresh_item_id=inv["id"]),
        make_customer_headers(cust["id"]))
    validate_error(res, "ERR_INSUFFICIENT_INVENTORY", expected_status=409)


def test_subscription_inventory_block_leaves_wallet_untouched(api):
    """PRD 2.1: "the first failing check determines the error returned."
    PRD 2.1: "(13) inventory sufficiency; (14) wallet sufficiency"
    PRD 2.6: "Any debit that would do so is rejected with ERR_INSUFFICIENT_WALLET (HTTP
    402), and the balance is left untouched."

    Design: Difficulty/priority_pair_validation_conflict/subscription_inventory_beats_wallet_fiscal
    """
    cust = new_customer(wallet_cents=0)
    inv = new_inventory("FRESH", on_hand=1)
    validate_error(api.create_subscription(
        create_subscription_payload(cust["id"], tier="PREMIUM", bird_count=2,
                                    fresh_feed=True, fresh_item_id=inv["id"]),
        make_customer_headers(cust["id"])), "ERR_INSUFFICIENT_INVENTORY", expected_status=409)
    after = validate_success(api.get_customer(cust["id"], SM), 200)
    assert after["wallet_credit_cents"] == 0  # no debit applied


# ── corner: deliver an unpaid order ──────────────────────────────────────────

def test_deliver_unpaid_order_rejected(api):
    """PRD 3.8: "Delivering moves build_status from BUILT to DELIVERED, but carries a
    cross-axis guard: the order's payment_status must be PAID, else ERR_ORDER_NOT_PAID —
    an unpaid order cannot be delivered."

    Design: Corner/state_machines/deliver_unpaid_order_rejected
    """
    cust = new_customer()
    inv = new_inventory("DRY", on_hand=5)
    order = new_special_order(cust["id"], inv["id"], build_qty=1,
                              line_items=[{"unit_price_cents": 1000, "quantity": 1, "tax_rate": 0.0}])
    validate_success(api.start_build(order["id"], SM), 200)
    validate_success(api.mark_built(order["id"], SM), 200)
    res = api.deliver_order(order["id"], SM)
    validate_error(res, "ERR_ORDER_NOT_PAID", expected_status=409)
    after = validate_success(api.get_special_order(order["id"], SM), 200)
    assert after["build_status"] == "BUILT"


# ── corner: pay an already-paid order ────────────────────────────────────────

def test_pay_already_paid_order_rejected(api):
    """PRD 3.8: "Payment requires payment_status to be UNPAID, else ERR_ORDER_ALREADY_PAID".

    Design: Corner/state_machines/pay_already_paid_order_rejected
    """
    cust = new_customer(wallet_cents=5000)
    inv = new_inventory("DRY", on_hand=5)
    order = new_special_order(cust["id"], inv["id"], build_qty=1,
                              line_items=[{"unit_price_cents": 1000, "quantity": 1, "tax_rate": 0.0}])
    validate_success(api.pay_order(order["id"], make_customer_headers(cust["id"])), 200)
    res = api.pay_order(order["id"], make_customer_headers(cust["id"]))
    validate_error(res, "ERR_ORDER_ALREADY_PAID", expected_status=409)
    cust_after = validate_success(api.get_customer(cust["id"], SM), 200)
    assert cust_after["wallet_credit_cents"] == 4000  # debited only once
