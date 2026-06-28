"""Walk-in queue, checkout side effects, and voiding (PRD §3.5, §3.6, §3.9).

Covers FIFO front enforcement, position recompute + queue-done, void reverting
the source appointment/queue ticket, the void stock-conservation invariant, and
the isolated insufficient-stock guard.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    assert_ticket,
    setup_shop_with_active_barber,
    setup_shop_with_barber_chair_shift,
    served_walkin_ticket,
    checked_in_ticket,
    enqueue,
    serve,
    set_lines,
    NON_EXISTENT_UUID,
    TEST_USERS,
)

OWNER = TEST_USERS["shop_owner_headers"]
RECEPTION = TEST_USERS["receptionist_headers"]


def test_serve_non_front_queue_ticket_rejected(api):
    """PRD §3.5: "The ticket being served must be the front `WAITING` ticket:
    either `queue_position` equal to 1 overall, or — when the ticket names a
    `requested_barber_id` — the earliest-created `WAITING` ticket among those
    requesting that same barber. Serving anything other than the front is refused
    with `ERR_NOT_QUEUE_FRONT`."

    Design: Corner/state_machines/serve_non_front_queue_ticket_returns_not_queue_front
    """
    ctx = setup_shop_with_active_barber(shop_overrides={"name": "S", "tax_rate_pct": 0})
    cust2 = get_success_data(api.create_customer(
        {"shop_id": ctx["shop"]["id"], "full_name": "C2", "email": "c2@x.com"}, OWNER))
    enqueue(ctx["shop"]["id"], ctx["customer"]["id"])  # q1, next-available
    q2 = enqueue(ctx["shop"]["id"], cust2["id"])        # q2, position 2
    res = api.serve_queue_ticket(q2["id"], RECEPTION)
    validate_error(res, "ERR_NOT_QUEUE_FRONT")


def test_serve_recomputes_positions_and_checkout_completes_queue(api):
    """PRD §3.5: "Queue positions are 1-based and ordered by `created_at` ascending
    among the shop's `WAITING` tickets, and they are recomputed every time a
    ticket is enqueued, served, or abandoned."
    PRD §3.6: "if it was opened from a queue ticket that is `SERVING`, that queue
    ticket moves `SERVING → DONE`."

    Design: Corner/state_machines/queue_serve_recomputes_positions_and_completes_on_checkout
    """
    ctx = setup_shop_with_active_barber(shop_overrides={"name": "S", "tax_rate_pct": 0})
    cust2 = get_success_data(api.create_customer(
        {"shop_id": ctx["shop"]["id"], "full_name": "C2", "email": "c2@x.com"}, OWNER))
    q1 = enqueue(ctx["shop"]["id"], ctx["customer"]["id"])
    q2 = enqueue(ctx["shop"]["id"], cust2["id"])
    served = serve(q1["id"])
    after = validate_success(api.get_queue_ticket(q2["id"], RECEPTION), 200)
    assert after["queue_position"] == 1, after
    validate_success(api.checkout_ticket(served["ticket_id"], RECEPTION), 200)
    q1_after = validate_success(api.get_queue_ticket(q1["id"], RECEPTION), 200)
    assert q1_after["status"] == "DONE", q1_after


def test_void_open_ticket_reverts_appointment_to_booked(api):
    """PRD §3.9: "Voiding moves the ticket `OPEN → VOIDED` and restores the
    upstream resource it came from: if the linked appointment is `CHECKED_IN`, it
    reverts `CHECKED_IN → BOOKED` and its `ticket_id` is cleared".

    Design: Corner/endpoints/void_open_ticket_reverts_appointment_to_booked
    """
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={"name": "S", "tax_rate_pct": 0},
        service_overrides={"name": "Haircut", "price_cents": 3000, "duration_minutes": 30},
    )
    checked, ticket = checked_in_ticket(ctx, start_utc="2026-06-10T10:00:00Z")
    voided = validate_success(api.void_ticket(ticket["id"], OWNER), 200)
    assert voided["status"] == "VOIDED", voided
    appt = validate_success(api.get_appointment(checked["id"], OWNER), 200)
    assert appt["status"] == "BOOKED", appt
    assert appt["ticket_id"] is None, appt


def test_void_conserves_product_stock(api):
    """PRD §3.9: "Because a void acts on an `OPEN` ticket — one whose revenue
    cascade has not yet run — voiding does not reverse settlement figures; it
    simply releases the source appointment or queue ticket for another attempt."
    PRD §3.9: "if the linked queue ticket is `SERVING`, it reverts
    `SERVING → WAITING` and is placed at the back of the line".

    Design: Difficulty/compensating_invariant/void_ticket_conserves_product_stock
    """
    ctx = setup_shop_with_active_barber(shop_overrides={"name": "Conserve Shop", "tax_rate_pct": 0})
    product = get_success_data(api.create_product(
        {"shop_id": ctx["shop"]["id"], "name": "Pomade", "price_cents": 1200,
         "stock_qty": 5}, OWNER))
    queue, ticket = served_walkin_ticket(ctx)
    set_lines(ticket["id"], product_lines=[{"product_sku_id": product["id"], "qty": 2}])
    voided = validate_success(api.void_ticket(ticket["id"], OWNER), 200)
    assert voided["status"] == "VOIDED"
    prod_after = validate_success(api.get_product(product["id"], OWNER), 200)
    # Decrement only happens at PAID; OPEN->VOIDED leaves stock untouched.
    assert prod_after["stock_qty"] == 5, prod_after
    q_after = validate_success(api.get_queue_ticket(queue["id"], OWNER), 200)
    assert q_after["status"] == "WAITING", q_after


def test_void_open_ticket_does_not_decrement_stock_vs_paid(api):
    """PRD §3.6: "Each product line decrements the matching product's `stock_qty`
    by its `qty`." (cascade runs only at checkout)
    PRD §3.9: "voiding does not reverse settlement figures; it simply releases the
    source appointment or queue ticket for another attempt."

    Design: Difficulty/compensating_invariant/void_ticket_conserves_product_stock
    """
    ctx = setup_shop_with_active_barber(shop_overrides={"name": "Conserve Shop", "tax_rate_pct": 0})
    product = get_success_data(api.create_product(
        {"shop_id": ctx["shop"]["id"], "name": "Pomade", "price_cents": 1200,
         "stock_qty": 3}, OWNER))
    _, ticket = served_walkin_ticket(ctx)
    set_lines(ticket["id"], product_lines=[{"product_sku_id": product["id"], "qty": 1}])
    validate_success(api.void_ticket(ticket["id"], OWNER), 200)
    prod_after = validate_success(api.get_product(product["id"], OWNER), 200)
    assert prod_after["stock_qty"] == 3, prod_after


def test_insufficient_stock_isolated_rejected(api):
    """PRD §2.9: "a checkout whose product quantity exceeds available stock is
    refused."
    PRD §3.6: "every product line must have `stock_qty` at least its `qty`
    (`ERR_INSUFFICIENT_STOCK`)".

    Design: Corner/validations/insufficient_stock_isolated_returns_error
    """
    ctx = setup_shop_with_active_barber(shop_overrides={"name": "S", "tax_rate_pct": 0})
    product = get_success_data(api.create_product(
        {"shop_id": ctx["shop"]["id"], "name": "Pomade", "price_cents": 1200,
         "stock_qty": 1}, OWNER))
    _, ticket = served_walkin_ticket(ctx)
    set_lines(ticket["id"], product_lines=[{"product_sku_id": product["id"], "qty": 3}])
    res = api.checkout_ticket(ticket["id"], RECEPTION)
    validate_error(res, "ERR_INSUFFICIENT_STOCK")
    prod_after = validate_success(api.get_product(product["id"], OWNER), 200)
    assert prod_after["stock_qty"] == 1, prod_after


def test_get_ticket_nonexistent_returns_not_found(api):
    """PRD §2.8: "returning that identifier's specific not-found error —
    `ERR_SHOP_NOT_FOUND`, `ERR_BARBER_NOT_FOUND`, `ERR_CHAIR_NOT_FOUND`,
    `ERR_SHIFT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`,
    `ERR_QUEUE_TICKET_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, or
    `ERR_SETTLEMENT_NOT_FOUND`, as applicable."

    Design: Corner/errors/get_ticket_nonexistent_returns_ticket_not_found
    """
    res = api.get_ticket(NON_EXISTENT_UUID, OWNER)
    validate_error(res, "ERR_TICKET_NOT_FOUND")


def test_get_queue_ticket_nonexistent_returns_not_found(api):
    """PRD §2.8: "returning that identifier's specific not-found error —
    `ERR_SHOP_NOT_FOUND`, `ERR_BARBER_NOT_FOUND`, `ERR_CHAIR_NOT_FOUND`,
    `ERR_SHIFT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`,
    `ERR_QUEUE_TICKET_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, or
    `ERR_SETTLEMENT_NOT_FOUND`, as applicable."

    Design: Corner/errors/get_queue_ticket_nonexistent_returns_queue_ticket_not_found
    """
    res = api.get_queue_ticket(NON_EXISTENT_UUID, OWNER)
    validate_error(res, "ERR_QUEUE_TICKET_NOT_FOUND")
