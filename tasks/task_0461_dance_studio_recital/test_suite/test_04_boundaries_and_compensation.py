"""Boundary-precision checks (costume rush close-date, recital last-seat sold-out) and
compensating-action invariants (costume cancel conserves family money, seat release conserves
recital inventory).

Queue A (Difficulty): boundary_precision_check, compensating_invariant.
"""
import pytest
from test_helpers import validate_success, validate_error, get_success_data, TEST_USERS, ApiErrorId
from test_helpers import fixtures as fx
from test_helpers import factories as f

ADMIN_H = TEST_USERS["admin_headers"]


# =========================================================================
# Rule 6 — boundary_precision_check
# =========================================================================
def test_costume_no_rush_surcharge_on_close_date(api):
    """PRD §3.6: "if the clock's date is strictly after the costume's `size_window_close_date`,
    the price is `unit_price_cents` plus `rush_surcharge_cents`; otherwise it is just
    `unit_price_cents`. The boundary is strict — on the close date itself there is no surcharge;
    only a clock date past it triggers the rush price."

    Clock set to exactly the close date (2026-03-15): no surcharge -> price 4500, not 6000.

    Design: Difficulty/boundary_precision_check/costume_rush_boundary_on_close_date
    """
    env = fx.setup_costume_draft_order(unit_price_cents=4500, rush_surcharge_cents=1500,
                                       size_window_close_date="2026-03-15")
    # Set clock to exactly the close date.
    get_success_data(api.set_clock("2026-03-15T00:00:00Z", ADMIN_H))
    validate_success(api.submit_costume_order(env["costume"]["id"], ADMIN_H))
    order_after = validate_success(api.get_costume_order(env["order"]["id"], ADMIN_H))
    assert order_after["price_cents"] == 4500, "no rush surcharge on the close date itself"
    assert order_after["status"] == "SUBMITTED"


def test_recital_flips_sold_out_on_last_seat(api):
    """PRD §3.8: "when `seats_sold` reaches `total_seats` the system flips it to `SOLD_OUT`."
    PRD §3.8: "A successful hold increments `seats_sold` by one and the recital's `version` by
    one, and may flip the recital to `SOLD_OUT`."

    Recital total_seats=1: holding the first (and only) seat makes seats_sold == total_seats and
    flips status to SOLD_OUT (boundary equality on a count metric).

    Design: Difficulty/boundary_precision_check/recital_last_seat_sold_out_boundary
    """
    base = fx.setup_recital_on_sale(recital_overrides={
        "total_seats": 1, "ticket_price_cents": 2000, "free_tickets_per_family": 0})
    family = fx.create_family()
    seat = validate_success(api.hold_seat(
        base["recital"]["id"],
        f.hold_seat_payload(family["id"], "A-1", base["recital_version"]),
        ADMIN_H), expected_status=201)
    recital_after = validate_success(api.get_recital(base["recital"]["id"], ADMIN_H))
    assert recital_after["seats_sold"] == 1
    assert recital_after["status"] == "SOLD_OUT"
    assert seat["status"] == "HELD"


# =========================================================================
# Rule 9 — compensating_invariant
# =========================================================================
def test_costume_order_cancel_conserves_family_money(api):
    """PRD §3.6: "A `SUBMITTED` order (cancellable by a `StudioAdmin`) becomes `CANCELLED` with
    compensation: its `price_cents` is removed from the family's open invoice fees, or, if that
    invoice has already been paid, credited to the family's `account_credit_cents` instead. The
    conserved quantity — invoice fees plus family credit — returns to its pre-order value."

    Submitting a 4500 costume order folds 4500 into the OPEN invoice fees; cancelling it removes
    4500 from those fees, so fees_cents returns to 0 and account_credit_cents stays 0.

    Design: Difficulty/compensating_invariant/costume_order_cancel_conserves_family_money
    """
    # Build CONFIRMED enrollment, an OPEN invoice, then a costume + SUBMITTED order.
    env = fx.setup_confirmed_enrollment(section_overrides={"discipline": "BALLET",
                                                           "monthly_tuition_cents": 9000})
    invoice = fx.generate_invoice(env["family"]["id"], env["term"]["id"], "2026-02")
    costume = get_success_data(api.create_costume(
        env["section"]["id"],
        f.create_costume_payload(unit_price_cents=4500, rush_surcharge_cents=1500,
                                 size_window_close_date="2026-05-01"), ADMIN_H))
    order = get_success_data(api.create_costume_order(
        f.create_costume_order_payload(costume["id"], env["enrollment"]["id"]), ADMIN_H))
    get_success_data(api.submit_costume_order(costume["id"], ADMIN_H))
    invoice_with_fee = validate_success(api.get_invoice(invoice["id"], ADMIN_H))
    assert invoice_with_fee["fees_cents"] == 4500, "submit should fold 4500 into invoice fees"

    # Trigger: cancel the SUBMITTED order.
    order_after = validate_success(api.cancel_costume_order(order["id"], ADMIN_H))
    assert order_after["status"] == "CANCELLED"
    invoice_after = validate_success(api.get_invoice(invoice["id"], ADMIN_H))
    family_after = validate_success(api.get_family(env["family"]["id"], ADMIN_H))
    assert invoice_after["fees_cents"] == 0
    assert family_after["account_credit_cents"] == 0


def test_purchased_seat_release_conserves_recital_inventory_and_refunds(api):
    """PRD §3.8: "A purchased seat may be released by a `StudioAdmin`: this decrements
    `seats_sold`, refunds the seat's `price_cents` to the family's `account_credit_cents`, and
    returns a `SOLD_OUT` recital to `ON_SALE` — the seat inventory and the family's
    paid-plus-credit balance both reconcile to their pre-purchase totals."

    total_seats=1: hold+purchase a paid seat -> seats_sold 1, recital SOLD_OUT; releasing returns
    seats_sold to 0, recital to ON_SALE, and refunds 2000 to family credit.

    Design: Difficulty/compensating_invariant/seat_release_conserves_recital_inventory
    """
    base = fx.setup_recital_on_sale(recital_overrides={
        "total_seats": 1, "ticket_price_cents": 2000, "free_tickets_per_family": 0})
    family = fx.create_family()
    seat = get_success_data(api.hold_seat(
        base["recital"]["id"],
        f.hold_seat_payload(family["id"], "A-1", base["recital_version"]), ADMIN_H))
    get_success_data(api.purchase_seat(seat["id"], ADMIN_H))
    recital_sold = validate_success(api.get_recital(base["recital"]["id"], ADMIN_H))
    assert recital_sold["status"] == "SOLD_OUT"

    # Trigger: release the purchased seat.
    seat_after = validate_success(api.release_seat(seat["id"], ADMIN_H))
    assert seat_after["status"] == "RELEASED"
    recital_after = validate_success(api.get_recital(base["recital"]["id"], ADMIN_H))
    family_after = validate_success(api.get_family(family["id"], ADMIN_H))
    assert recital_after["seats_sold"] == 0
    assert recital_after["status"] == "ON_SALE"
    assert family_after["account_credit_cents"] == 2000
