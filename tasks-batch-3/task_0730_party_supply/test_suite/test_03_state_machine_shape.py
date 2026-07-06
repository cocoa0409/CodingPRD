"""Difficulty rule 3 — non-linear state-machine shape on different entities.

Instance A: Order parallel dimensions (fulfillment × payment).
Instance B: CustomPrintOrder cyclic PROOF_SENT <-> REVISION_REQUESTED.
"""
from test_helpers import (
    validate_success, api_client, make_store_clerk_headers,
    make_customer_headers,
)
from test_helpers.fixtures import (
    set_clock, create_customer, create_sku_with_stock, create_event_package,
    setup_draft_order, create_event_booking, reserve_order, pay_order,
    attach_custom_print, do_request_revision_and_proof,
)


# =====================================================================
# Instance A — order_parallel_fulfillment_and_payment_dimensions
# =====================================================================

def test_order_reserve_moves_fulfillment_without_touching_payment():
    """PRD §2.7: "An Order maintains two independent status axes on the
    same row. fulfillment_status tracks the movement of goods through
    the store — the values are DRAFT, RESERVED, PICKING,
    READY_FOR_PICKUP, PICKED_UP, DELIVERED, RETURNED, and CANCELLED.
    payment_status tracks the money — the values are UNPAID,
    DEPOSIT_HELD, PAID, PARTIALLY_REFUNDED, and REFUNDED."
    PRD §2.7: "Every new order is created with fulfillment_status set to
    DRAFT and payment_status set to UNPAID."
    PRD §2.7: "The two axes evolve independently and are never collapsed
    into a single status field, though some transitions on one axis have
    preconditions that read the other axis."

    Design: Difficulty/non_linear_state_machine/order_parallel_fulfillment_and_payment_dimensions
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=300, on_hand=100)
    pkg = create_event_package(base_price_cents=20000, deposit_pct=0.30,
                                min_lead_days=7)
    order = setup_draft_order(cust["id"], sku["id"], qty=1)
    # Attach event booking to make DEPOSIT mode applicable later.
    create_event_booking(order["id"], pkg["id"], "2026-07-30T18:00:00Z")
    resp = api_client.reserve_order(
        order["id"], order["version"], make_store_clerk_headers(),
    )
    reserved = validate_success(resp)
    assert reserved["fulfillment_status"] == "RESERVED", (
        f"After reserve, fulfillment_status must be RESERVED; "
        f"got {reserved['fulfillment_status']}"
    )
    assert reserved["payment_status"] == "UNPAID", (
        f"Reserve must NOT touch payment_status; still UNPAID; "
        f"got {reserved['payment_status']}"
    )


def test_order_pay_deposit_moves_payment_without_touching_fulfillment():
    """PRD §2.7: "The two axes evolve independently and are never
    collapsed into a single status field, though some transitions on one
    axis have preconditions that read the other axis (for example,
    starting to pick an order requires the payment axis to be in either
    DEPOSIT_HELD or PAID, and picking the order up requires the payment
    axis to be PAID)."
    PRD §3.5: "When mode is DEPOSIT, the request records a partial
    payment: it is accepted only while the order is RESERVED and the
    order has either an attached EventBooking or an attached
    RentalContract; otherwise the request is rejected with
    ERR_DEPOSIT_NOT_APPLICABLE. On acceptance, payment_status moves from
    UNPAID to DEPOSIT_HELD and version increments."

    Design: Difficulty/non_linear_state_machine/order_parallel_fulfillment_and_payment_dimensions
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=300, on_hand=100)
    pkg = create_event_package(base_price_cents=20000, deposit_pct=0.30,
                                min_lead_days=7)
    order = setup_draft_order(cust["id"], sku["id"], qty=1)
    create_event_booking(order["id"], pkg["id"], "2026-07-30T18:00:00Z")
    reserved = reserve_order(order["id"], order["version"])
    # Now pay DEPOSIT.
    resp = api_client.pay_order(
        reserved["id"], "DEPOSIT", make_store_clerk_headers(),
    )
    paid = validate_success(resp)
    assert paid["payment_status"] == "DEPOSIT_HELD", (
        f"pay DEPOSIT must move payment_status UNPAID→DEPOSIT_HELD; "
        f"got {paid['payment_status']}"
    )
    assert paid["fulfillment_status"] == "RESERVED", (
        f"pay must NOT touch fulfillment_status; still RESERVED; "
        f"got {paid['fulfillment_status']}"
    )


# =====================================================================
# Instance B — custom_print_cyclic_proof_revision_loop
# =====================================================================

def test_custom_print_request_revision_increments_and_flips_status():
    """PRD §3.7: "A revision request transitions PROOF_SENT to
    REVISION_REQUESTED, increments revision_count by one, and is
    permitted only when revision_count is currently less than 3 — a
    fourth revision attempt is rejected with ERR_REVISION_LIMIT."

    Design: Difficulty/non_linear_state_machine/custom_print_cyclic_proof_revision_loop
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=200, on_hand=100)
    order = setup_draft_order(cust["id"], sku["id"], qty=1)
    cpo = attach_custom_print(order["id"], banner_length_ft=8)
    reserved = reserve_order(order["id"], order["version"])
    pay_order(reserved["id"], "FULL")
    r_sp = api_client.send_proof(cpo["id"], make_store_clerk_headers())
    ps = validate_success(r_sp)
    assert ps["status"] == "PROOF_SENT"
    assert ps["revision_count"] == 0
    # Request revision.
    r_rr = api_client.request_revision(
        cpo["id"], make_customer_headers(cust["id"])
    )
    rr = validate_success(r_rr)
    assert rr["status"] == "REVISION_REQUESTED"
    assert rr["revision_count"] == 1


def test_custom_print_send_proof_from_revision_requested_reenters_proof_sent():
    """PRD §3.7: "A subsequent proof send by the clerk takes
    REVISION_REQUESTED back to PROOF_SENT, and the loop continues until
    the customer either approves or the revision cap is hit."

    Design: Difficulty/non_linear_state_machine/custom_print_cyclic_proof_revision_loop
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=200, on_hand=100)
    order = setup_draft_order(cust["id"], sku["id"], qty=1)
    cpo = attach_custom_print(order["id"], banner_length_ft=8)
    reserved = reserve_order(order["id"], order["version"])
    pay_order(reserved["id"], "FULL")
    api_client.send_proof(cpo["id"], make_store_clerk_headers())
    api_client.request_revision(cpo["id"], make_customer_headers(cust["id"]))
    # Second send-proof.
    resp = api_client.send_proof(cpo["id"], make_store_clerk_headers())
    after = validate_success(resp)
    assert after["status"] == "PROOF_SENT"
    assert after["revision_count"] == 1, (
        f"revision_count must remain 1 after re-entering PROOF_SENT; "
        f"got {after['revision_count']}"
    )
