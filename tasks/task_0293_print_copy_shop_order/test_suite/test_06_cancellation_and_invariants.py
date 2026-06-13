"""Cancellation cascade (depth-3) and compensating invariants (capacity, lifetime spend)."""
import pytest
from test_helpers import (
    api_client, get_success_data,
    validate_success,
    create_shop, create_customer, create_product, create_order, add_line,
    upload_and_pass_preflight, add_pickup_fulfillment, read_order_version, confirm_order,
    pin_clock, setup_banner_line, book_press, setup_confirmable_copies_order,
    TEST_USERS, make_customer_headers,
)

STAFF = TEST_USERS["shop_staff_headers"]
OPERATOR = TEST_USERS["production_operator_headers"]


def _confirmed_banner_with_booking(name):
    """A CONFIRMED BANNER order holding a CONFIRMED press booking and a HELD capacity
    reservation. Returns dict {shop, customer, order, line, press, booking_id}."""
    ctx = setup_banner_line(shop_overrides={"name": name}, unit_size=2,
                            cleanup_buffer_minutes=30, quantity=1, with_press=True)
    cust = ctx["customer"]
    booking = get_success_data(book_press(ctx["press"]["id"], ctx["line"]["id"],
                                          "2026-06-02T10:00:00Z", "2026-06-02T11:00:00Z"))
    add_pickup_fulfillment(ctx["order"]["id"], cust["id"])
    v = read_order_version(ctx["order"]["id"], cust["id"])
    validate_success(confirm_order(ctx["order"]["id"], cust["id"], v), 200)
    ctx["booking_id"] = booking["id"]
    return ctx


# ─── Difficulty: transitive_cascade (cancel depth-3) ─────────────────────────
def test_cancel_releases_press_booking(api):
    """PRD §3.8: "A successful cancel moves `production_status` to `CANCELLED` and cascades
    two releases: every `HELD` capacity reservation for the order's lines moves to
    `RELEASED` ... and every `CONFIRMED` press booking for the order's lines moves to
    `RELEASED`, freeing each slot and its trailing buffer on the press."

    Design: Difficulty/transitive_cascade/cancel_releases_capacity_and_press_depth3
    """
    ctx = _confirmed_banner_with_booking("Cascade Shop")
    cust = ctx["customer"]
    cust_headers = make_customer_headers(cust["id"])
    v = read_order_version(ctx["order"]["id"], cust["id"])
    cancelled = validate_success(
        api.cancel_order(ctx["order"]["id"], {"expected_order_version": v}, cust_headers), 200)
    assert cancelled["production_status"] == "CANCELLED"
    booking = get_success_data(api.get_press_booking(ctx["booking_id"], STAFF))
    assert booking["status"] == "RELEASED"


def test_cancel_releases_capacity_reservations(api):
    """PRD §3.8: "every `HELD` capacity reservation for the order's lines moves to
    `RELEASED`, returning its units to the shop's daily pool for that production date".

    Design: Difficulty/transitive_cascade/cancel_releases_capacity_and_press_depth3
    """
    ctx = _confirmed_banner_with_booking("Cascade Shop 2")
    cust = ctx["customer"]
    cust_headers = make_customer_headers(cust["id"])
    v = read_order_version(ctx["order"]["id"], cust["id"])
    validate_success(
        api.cancel_order(ctx["order"]["id"], {"expected_order_version": v}, cust_headers), 200)
    reservations = get_success_data(
        api.list_capacity_reservations(STAFF, params={"order_line_id": ctx["line"]["id"]}))
    assert len(reservations) >= 1, "confirm created at least one reservation for the line"
    assert all(r["status"] == "RELEASED" for r in reservations), \
        "all reservations for the cancelled order's line are RELEASED"


# ─── Difficulty: compensating_invariant (capacity conserved) ─────────────────
def test_capacity_units_released_to_zero_after_cancel(api):
    """PRD §3.8: "every `HELD` capacity reservation for the order's lines moves to
    `RELEASED`, returning its units to the shop's daily pool for that production date".

    Design: Difficulty/compensating_invariant/capacity_units_conserved_under_confirm_then_cancel
    """
    ctx = setup_confirmable_copies_order(
        shop_overrides={"name": "Conserve Shop", "daily_unit_capacity": 10}, quantity=10)
    cust = ctx["customer"]
    cust_headers = make_customer_headers(cust["id"])
    order_id = ctx["order"]["id"]
    validate_success(confirm_order(order_id, cust["id"], ctx["version"]), 200)
    v2 = read_order_version(order_id, cust["id"])
    validate_success(
        api.cancel_order(order_id, {"expected_order_version": v2}, cust_headers), 200)
    reservations = get_success_data(
        api.list_capacity_reservations(STAFF, params={"order_line_id": ctx["line"]["id"]}))
    held_units = sum(r["units"] for r in reservations if r["status"] == "HELD")
    assert held_units == 0, "all HELD units released; full day available again"


def test_full_capacity_reclaimable_after_cancel(api):
    """PRD §3.8: "returning its units to the shop's daily pool for that production date".
    PRD §3.6: "The boundary is strict-greater: a day filled exactly to capacity is allowed".

    Design: Difficulty/compensating_invariant/capacity_units_conserved_under_confirm_then_cancel
    """
    pin_clock("2026-06-01T09:00:00Z")
    shop = create_shop(name="Reclaim Shop", daily_unit_capacity=10)
    prod = create_product(shop["id"], name="BW Copy", category="COPIES",
                          base_unit_price_cents=500, unit_size=1,
                          requires_proof=False, requires_press=False)
    # First customer fills the day, then cancels.
    cust1 = create_customer(shop["id"], email="c1@x.com")
    order1 = create_order(shop["id"], cust1["id"])
    line1 = add_line(order1["id"], prod["id"], 10, cust1["id"])
    upload_and_pass_preflight(line1["id"], cust1["id"])
    add_pickup_fulfillment(order1["id"], cust1["id"])
    v1 = read_order_version(order1["id"], cust1["id"])
    validate_success(confirm_order(order1["id"], cust1["id"], v1), 200)
    v1b = read_order_version(order1["id"], cust1["id"])
    validate_success(api.cancel_order(order1["id"], {"expected_order_version": v1b},
                                      make_customer_headers(cust1["id"])), 200)
    # A fresh order can re-claim the full 10 units on the same date.
    cust2 = create_customer(shop["id"], email="c2@x.com")
    order2 = create_order(shop["id"], cust2["id"])
    line2 = add_line(order2["id"], prod["id"], 10, cust2["id"])
    upload_and_pass_preflight(line2["id"], cust2["id"])
    add_pickup_fulfillment(order2["id"], cust2["id"])
    v2 = read_order_version(order2["id"], cust2["id"])
    confirmed2 = validate_success(confirm_order(order2["id"], cust2["id"], v2), 200)
    assert confirmed2["production_status"] == "CONFIRMED", "full capacity reclaimed"


# ─── Difficulty: compensating_invariant (lifetime spend conserved) ───────────
def _pay_then_cancel_order(name, email):
    """Confirm -> invoice -> pay -> cancel an order. Returns (customer, order_id, total)."""
    ctx = setup_confirmable_copies_order(shop_overrides={"name": name}, quantity=10)
    cust = ctx["customer"]
    cust_headers = make_customer_headers(cust["id"])
    order_id = ctx["order"]["id"]
    confirmed = validate_success(confirm_order(order_id, cust["id"], ctx["version"]), 200)
    total = confirmed["total_cents"]
    get_success_data(api_client.invoice_order(order_id, STAFF))
    get_success_data(api_client.pay_order(order_id, {"amount_cents": total}, cust_headers))
    v = read_order_version(order_id, cust["id"])
    get_success_data(api_client.cancel_order(order_id, {"expected_order_version": v}, cust_headers))
    return cust, order_id, total


def test_lifetime_paid_restored_to_zero_after_refund(api):
    """PRD §3.8: "It moves `payment_status` from `PAID` to `REFUNDED` and, as a compensating
    action, reduces the customer's `lifetime_paid_cents` by the order's `total_cents`,
    restoring it to its pre-payment value."

    Design: Difficulty/compensating_invariant/lifetime_paid_conserved_under_pay_then_refund
    """
    cust, order_id, total = _pay_then_cancel_order("Refund Shop", "r@x.com")
    refunded = validate_success(api.refund_order(order_id, STAFF), 200)
    assert refunded["payment_status"] == "REFUNDED"
    cust_after = get_success_data(api.get_customer(cust["id"], STAFF))
    assert cust_after["lifetime_paid_cents"] == 0, "pay +total then refund -total conserves 0"


def test_lifetime_paid_bumped_by_total_on_payment(api):
    """PRD §3.7: "A successful payment moves `payment_status` from `INVOICED` to `PAID` and
    adds the order's `total_cents` to the customer's `lifetime_paid_cents`."

    Design: Difficulty/compensating_invariant/lifetime_paid_conserved_under_pay_then_refund
    """
    ctx = setup_confirmable_copies_order(shop_overrides={"name": "Pay Shop"}, quantity=10)
    cust = ctx["customer"]
    cust_headers = make_customer_headers(cust["id"])
    order_id = ctx["order"]["id"]
    confirmed = validate_success(confirm_order(order_id, cust["id"], ctx["version"]), 200)
    total = confirmed["total_cents"]
    get_success_data(api.invoice_order(order_id, STAFF))
    get_success_data(api.pay_order(order_id, {"amount_cents": total}, cust_headers))
    cust_after = get_success_data(api.get_customer(cust["id"], STAFF))
    assert cust_after["lifetime_paid_cents"] == total, "payment adds total_cents to lifetime"
