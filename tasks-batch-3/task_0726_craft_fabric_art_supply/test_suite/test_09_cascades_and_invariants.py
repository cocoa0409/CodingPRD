"""Transitive cascades and compensating inventory / loyalty invariants."""
from test_helpers import (
    validate_success, get_success_data,
    set_clock, create_customer, create_product, create_inventory_lot, create_product_with_lot,
    create_order, create_order_with_line, add_line, submit_order, pay_order, record_cut,
    ready_order, pickup_order, complete_picked_up_order,
    setup_open_workshop_with_session, register_customer,
    make_customer_headers, get_loyalty_account,
)
from test_helpers import TEST_USERS


def test_workshop_cancel_cascades_to_inventory_release(api):
    """PRD §3.6: "Cancelling a workshop from DRAFT, OPEN, or CLOSED drives it to
    the terminal CANCELLED state, cascade-cancels each of its REGISTERED or
    WAITLISTED registrations, and for each cancelled registration cancels its
    supply-kit order line if one exists, releasing the associated inventory
    reservation."

    Design: Difficulty/transitive_cascade/workshop_cancel_cascade_to_inventory_release
    """
    set_clock("2026-05-01T00:00:00Z")
    customer = create_customer()
    kit = create_product(sell_mode="UNIT", unit_price_cents=1000)
    lot = create_inventory_lot(kit["id"], on_hand_yards=5)
    workshop, session, _ = setup_open_workshop_with_session(
        "2026-08-02T10:00:00Z", "2026-08-02T12:00:00Z", capacity=10, kit_product_id=kit["id"]
    )
    order = create_order(customer["id"])
    reg = register_customer(workshop["id"], session["id"], customer["id"], order_id=order["id"])
    submit_order(order["id"], customer["id"])
    api.cancel_workshop(workshop["id"], TEST_USERS["store_manager_headers"])
    reg_data = validate_success(
        api.get_registration(reg["id"], make_customer_headers(customer["id"]))
    )
    assert reg_data["status"] == "CANCELLED"
    lot_data = validate_success(
        api.get_inventory_lot(lot["id"], TEST_USERS["store_manager_headers"])
    )
    assert lot_data["reserved_yards"] == 0
    assert lot_data["available_yards"] == 5


def test_workshop_cancel_drives_workshop_to_cancelled(api):
    """PRD §3.6: "Cancelling a workshop from DRAFT, OPEN, or CLOSED drives it to
    the terminal CANCELLED state, cascade-cancels each of its REGISTERED or
    WAITLISTED registrations"

    Design: Difficulty/transitive_cascade/workshop_cancel_cascade_to_inventory_release
    """
    set_clock("2026-05-01T00:00:00Z")
    customer = create_customer()
    kit = create_product(sell_mode="UNIT", unit_price_cents=1000)
    create_inventory_lot(kit["id"], on_hand_yards=5)
    workshop, session, _ = setup_open_workshop_with_session(
        "2026-08-02T10:00:00Z", "2026-08-02T12:00:00Z", capacity=10, kit_product_id=kit["id"]
    )
    order = create_order(customer["id"])
    register_customer(workshop["id"], session["id"], customer["id"], order_id=order["id"])
    submit_order(order["id"], customer["id"])
    data = validate_success(api.cancel_workshop(workshop["id"], TEST_USERS["store_manager_headers"]))
    assert data["status"] == "CANCELLED"


def test_order_cancel_cascades_to_inventory_release(api):
    """PRD §3.5: "Cancellation drives fulfillment_status to CANCELLED and moves
    every non-cancelled line to CANCELLED. For each line that had been RESERVED,
    its requested_yards is subtracted back out of the lot's reserved_yards and
    available_yards is recomputed, releasing the reservation the submission
    created."

    Design: Difficulty/transitive_cascade/order_cancel_cascade_to_inventory_release
    """
    customer = create_customer()
    product, lot = create_product_with_lot(
        on_hand_yards=10, sell_mode="BY_YARD", unit_price_cents=200, min_cut_increment_yards=1
    )
    order, line = create_order_with_line(customer["id"], product["id"], requested_yards=3)
    submit_order(order["id"], customer["id"])
    api.cancel_order(order["id"], make_customer_headers(customer["id"]))
    line_data = validate_success(
        api.get_order_line(line["id"], make_customer_headers(customer["id"]))
    )
    assert line_data["status"] == "CANCELLED"
    lot_data = validate_success(
        api.get_inventory_lot(lot["id"], TEST_USERS["store_manager_headers"])
    )
    assert lot_data["reserved_yards"] == 0
    assert lot_data["available_yards"] == 10


def test_order_cancel_moves_all_lines_to_cancelled(api):
    """PRD §3.5: "Cancellation drives fulfillment_status to CANCELLED and moves
    every non-cancelled line to CANCELLED."

    Design: Difficulty/transitive_cascade/order_cancel_cascade_to_inventory_release
    """
    customer = create_customer()
    product, _ = create_product_with_lot(
        on_hand_yards=10, sell_mode="BY_YARD", unit_price_cents=200, min_cut_increment_yards=1
    )
    order, line = create_order_with_line(customer["id"], product["id"], requested_yards=3)
    submit_order(order["id"], customer["id"])
    data = validate_success(api.cancel_order(order["id"], make_customer_headers(customer["id"])))
    assert data["fulfillment_status"] == "CANCELLED"
    line_data = validate_success(
        api.get_order_line(line["id"], make_customer_headers(customer["id"]))
    )
    assert line_data["status"] == "CANCELLED"


def test_inventory_conserved_across_submit_then_cancel(api):
    """PRD §2.5: "for an inventory lot, on-hand stock always equals available stock
    plus reserved stock"
    PRD §3.5: "releasing the reservation the submission created."

    Design: Difficulty/compensating_invariant/inventory_yards_conserved_across_submit_then_cancel
    """
    customer = create_customer()
    product, lot = create_product_with_lot(
        on_hand_yards=10, sell_mode="BY_YARD", unit_price_cents=250, min_cut_increment_yards=1
    )
    order, _ = create_order_with_line(customer["id"], product["id"], requested_yards=4)
    submit_order(order["id"], customer["id"])
    api.cancel_order(order["id"], make_customer_headers(customer["id"]))
    lot_data = validate_success(
        api.get_inventory_lot(lot["id"], TEST_USERS["store_manager_headers"])
    )
    assert lot_data["available_yards"] == 10
    assert lot_data["reserved_yards"] == 0
    assert lot_data["on_hand_yards"] == 10


def test_submit_reserves_then_cancel_restores_available(api):
    """PRD §3.4: "each line's requested_yards is added to the corresponding lot's
    reserved_yards with available_yards recomputed"
    PRD §3.5: "releasing the reservation the submission created."

    Design: Difficulty/compensating_invariant/inventory_yards_conserved_across_submit_then_cancel
    """
    customer = create_customer()
    product, lot = create_product_with_lot(
        on_hand_yards=10, sell_mode="BY_YARD", unit_price_cents=250, min_cut_increment_yards=1
    )
    order, _ = create_order_with_line(customer["id"], product["id"], requested_yards=4)
    submit_order(order["id"], customer["id"])
    after_submit = validate_success(
        api.get_inventory_lot(lot["id"], TEST_USERS["store_manager_headers"])
    )
    assert after_submit["reserved_yards"] == 4
    assert after_submit["available_yards"] == 6
    api.cancel_order(order["id"], make_customer_headers(customer["id"]))
    after_cancel = validate_success(
        api.get_inventory_lot(lot["id"], TEST_USERS["store_manager_headers"])
    )
    assert after_cancel["available_yards"] == 10


def test_loyalty_points_conserved_across_redeem_then_cancel(api):
    """PRD §3.5: "If any points had been redeemed on the order, that redemption is
    compensated: points_redeemed is decreased by points_redeemed_on_order and
    points_balance is recomputed."

    Design: Difficulty/compensating_invariant/loyalty_points_balance_conserved_across_redeem_then_cancel
    """
    set_clock("2026-04-01T00:00:00Z")
    customer = create_customer()
    product, _ = create_product_with_lot(on_hand_yards=10, sell_mode="UNIT", unit_price_cents=30000)
    # First order: PICKED_UP for 30000c -> 300 points earned.
    complete_picked_up_order(customer["id"], product["id"], requested_yards=1)
    # Second order: submit, pay redeeming 200, then cancel.
    order2, _ = create_order_with_line(customer["id"], product["id"], requested_yards=1)
    submit_order(order2["id"], customer["id"])
    pay_order(order2["id"], customer["id"], points_redeemed_on_order=200)
    api.cancel_order(order2["id"], make_customer_headers(customer["id"]))
    account = get_loyalty_account(customer["id"])
    assert account["points_balance"] == 300
    assert account["points_redeemed"] == 0


def test_redeem_then_cancel_restores_redeemed_counter(api):
    """PRD §3.5: "If any points had been redeemed on the order, that redemption is
    compensated: points_redeemed is decreased by points_redeemed_on_order and
    points_balance is recomputed."

    Design: Difficulty/compensating_invariant/loyalty_points_balance_conserved_across_redeem_then_cancel
    """
    set_clock("2026-04-01T00:00:00Z")
    customer = create_customer()
    product, _ = create_product_with_lot(on_hand_yards=10, sell_mode="UNIT", unit_price_cents=30000)
    complete_picked_up_order(customer["id"], product["id"], requested_yards=1)
    account_before = get_loyalty_account(customer["id"])
    assert account_before["points_redeemed"] == 0
    order2, _ = create_order_with_line(customer["id"], product["id"], requested_yards=1)
    submit_order(order2["id"], customer["id"])
    pay_order(order2["id"], customer["id"], points_redeemed_on_order=150)
    mid = get_loyalty_account(customer["id"])
    assert mid["points_redeemed"] == 150
    api.cancel_order(order2["id"], make_customer_headers(customer["id"]))
    after = get_loyalty_account(customer["id"])
    assert after["points_redeemed"] == 0


def test_pickup_decrements_on_hand_and_accrues_points(api):
    """PRD §3.4: "the account's points_earned increases by the whole-number result
    of dividing final_total_cents by 100 and discarding any remainder,
    spend_ytd_cents increases by final_total_cents"
    PRD §3.4: "for each line the lot's on_hand_yards is decreased by
    actual_cut_yards for by-the-yard goods (or by requested_yards for unit and
    bulk goods)"

    Design: Corner/consistency_model/pickup_decrements_on_hand_and_accrues_points
    """
    customer = create_customer()
    product, lot = create_product_with_lot(
        on_hand_yards=10, sell_mode="BY_YARD", unit_price_cents=2500, min_cut_increment_yards=1
    )
    complete_picked_up_order(customer["id"], product["id"], requested_yards=2, actual_cut_yards=2)
    lot_data = validate_success(
        api.get_inventory_lot(lot["id"], TEST_USERS["store_manager_headers"])
    )
    assert lot_data["on_hand_yards"] == 8
    account = get_loyalty_account(customer["id"])
    # final total 2500*2=5000 -> floor(5000/100)=50 points.
    assert account["points_earned"] == 50
