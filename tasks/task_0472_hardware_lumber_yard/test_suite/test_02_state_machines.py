"""State machines: parallel SalesOrder dimensions, the cyclic SpecialOrder
revision loop, initial states, invalid transitions, terminal lockdown, and
precondition enforcement.

Covers Difficulty queue rule non_linear_state_machine, plus the Corner queue
state_machines and consistency_model sections.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_vendor, create_product, create_account,
    create_order_with_line, place_order, setup_placed_order,
    setup_fulfilled_order, create_special_order, setup_quoted_special_order,
    setup_confirmed_special_order, create_rental_asset, create_reservation,
    setup_checked_out_rental, set_clock,
    api_client, SALES, INVENTORY, ACCOUNTS, RENTAL,
    make_contractor_headers,
)


# ─── Difficulty: non_linear_state_machine ───────────────────────────────────

def test_parallel_fulfillment_and_payment_dimensions(api):
    """PRD 3.6: "Payment evolves on an axis independent of fulfillment, and only
    an `AccountsManager` drives it. Issuing an invoice advances `payment_status`
    from `UNBILLED` to `INVOICED`."

    Design: Difficulty/non_linear_state_machine/sales_order_parallel_payment_and_fulfillment_dimensions
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=1000, on_hand=100)
    account = create_account(credit_limit_cents=1000000, net_terms_days=30)
    fulfilled = setup_fulfilled_order(product["id"], qty=10,
                                      contractor_account_id=account["id"])
    api.invoice_order(fulfilled["id"], ACCOUNTS)

    order = validate_success(api.get_sales_order(fulfilled["id"], ACCOUNTS), 200)
    assert order["fulfillment_status"] == "FULFILLED"
    assert order["payment_status"] == "INVOICED"


def test_invoiced_order_keeps_fulfilled_fulfillment_status(api):
    """PRD 3.6: "Issuing the invoice creates an Invoice whose amount_cents is
    copied from the order's total_cents."
    PRD 3.6: "the order's fulfillment_status must be FULFILLED, since an
    unfulfilled order cannot be invoiced."

    Design: Difficulty/non_linear_state_machine/sales_order_parallel_payment_and_fulfillment_dimensions
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=1000, on_hand=100)
    account = create_account(credit_limit_cents=1000000, net_terms_days=30)
    fulfilled = setup_fulfilled_order(product["id"], qty=10,
                                      contractor_account_id=account["id"])
    invoiced = validate_success(api.invoice_order(fulfilled["id"], ACCOUNTS), 201)
    order = validate_success(api.get_sales_order(fulfilled["id"], ACCOUNTS), 200)
    # The fulfillment axis is untouched by the invoice action.
    assert order["fulfillment_status"] == "FULFILLED"


def test_special_order_revision_loop_cycles_back_to_quoted(api):
    """PRD 3.9: "a subsequent quote moves it from `REVISION_REQUESTED` back to
    `QUOTED`, increments `revision_count` by one, and stores the new
    `quoted_unit_cents`."

    Design: Difficulty/non_linear_state_machine/special_order_cyclic_revision_loop
    """
    quoted, vendor, account = setup_quoted_special_order(
        qty=2, quoted_unit_cents=30000)
    ch = make_contractor_headers(account["id"])
    validate_success(api.request_revision(quoted["id"], ch), 200)
    re_quoted = validate_success(api.quote_special_order(
        quoted["id"], {"quoted_unit_cents": 28000}, SALES), 200)
    assert re_quoted["status"] == "QUOTED"
    assert re_quoted["revision_count"] == 1


def test_request_revision_moves_quoted_to_revision_requested(api):
    """PRD 3.9: "A Contractor who is not satisfied can request a revision,
    moving a QUOTED order to REVISION_REQUESTED with no charge."

    Design: Difficulty/non_linear_state_machine/special_order_cyclic_revision_loop
    """
    quoted, vendor, account = setup_quoted_special_order(
        qty=2, quoted_unit_cents=30000)
    ch = make_contractor_headers(account["id"])
    revised = validate_success(api.request_revision(quoted["id"], ch), 200)
    assert revised["status"] == "REVISION_REQUESTED"
    assert revised["revision_count"] == 0, "the request itself does not increment"


# ─── Corner: state_machines ─────────────────────────────────────────────────

def test_new_sales_order_starts_draft_unbilled_provisional(api):
    """PRD 3.2: "A fresh order begins with fulfillment_status of DRAFT,
    payment_status of UNBILLED, and pricing_mode of PROVISIONAL."

    Design: Corner/state_machines/new_sales_order_starts_in_draft_unbilled
    """
    order = validate_success(api.create_sales_order({}, SALES), 201)
    assert order["fulfillment_status"] == "DRAFT"
    assert order["payment_status"] == "UNBILLED"
    assert order["pricing_mode"] == "PROVISIONAL"


def test_place_already_placed_order_rejected(api):
    """PRD 3.2: "an attempt to add a line to an order that has already advanced
    to PLACED or beyond is rejected with ERR_INVALID_STATE."
    PRD 3.11: "the general guard that a requested transition must be defined
    from the resource's current state yields ERR_INVALID_STATE."

    Design: Corner/state_machines/place_already_placed_order_returns_invalid_state
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=1000, on_hand=100)
    placed = setup_placed_order(product["id"], qty=5)
    res = api.place_order(
        placed["id"], {"expected_sales_order_version": placed["version"]}, SALES)
    validate_error(res, "ERR_INVALID_STATE")


def test_returned_rental_cannot_be_cancelled(api):
    """PRD 3.7: "a checked-out rental cannot be cancelled, and the attempt is
    rejected with ERR_INVALID_STATE."
    PRD 3.11: "the general guard that a requested transition must be defined
    from the resource's current state yields ERR_INVALID_STATE."

    Design: Corner/state_machines/cancel_returned_rental_terminal_lockdown
    """
    checked_out, asset = setup_checked_out_rental(
        start_at="2026-05-01T08:00:00Z", due_at="2026-05-02T08:00:00Z",
        checkout_clock="2026-05-01T09:00:00Z")
    set_clock("2026-05-02T10:00:00Z")
    validate_success(api.return_rental(checked_out["id"], RENTAL), 200)
    res = api.cancel_rental(checked_out["id"], RENTAL)
    validate_error(res, "ERR_INVALID_STATE")


def test_confirmed_special_order_cannot_be_cancelled(api):
    """PRD 3.9: "a CONFIRMED order can no longer be cancelled, and the attempt
    is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/confirmed_special_order_cannot_be_cancelled
    """
    confirmed, vendor, account = setup_confirmed_special_order(
        qty=10, quoted_unit_cents=6000)  # goods 60000, free ship
    ch = make_contractor_headers(account["id"])
    res = api.cancel_special_order(confirmed["id"], ch)
    validate_error(res, "ERR_INVALID_STATE")


def test_invoice_before_fulfill_rejected(api):
    """PRD 3.6: "the order's fulfillment_status must be FULFILLED, since an
    unfulfilled order cannot be invoiced (rejected ERR_ORDER_NOT_FULFILLED)."

    Design: Corner/state_machines/invoice_before_fulfill_returns_order_not_fulfilled
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=1000, on_hand=100)
    account = create_account(credit_limit_cents=1000000, net_terms_days=30)
    placed = setup_placed_order(product["id"], qty=5,
                                contractor_account_id=account["id"])
    res = api.invoice_order(placed["id"], ACCOUNTS)
    validate_error(res, "ERR_ORDER_NOT_FULFILLED")


def test_invoice_cash_order_rejected(api):
    """PRD 3.6: "the order must name a contractor account, since cash sales are
    never invoiced (rejected ERR_NOT_NET_TERM_ORDER)."

    Design: Corner/state_machines/invoice_cash_order_returns_not_net_term
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=1000, on_hand=100)
    fulfilled = setup_fulfilled_order(product["id"], qty=5)  # cash sale
    res = api.invoice_order(fulfilled["id"], ACCOUNTS)
    validate_error(res, "ERR_NOT_NET_TERM_ORDER")


def test_pay_without_issued_invoice_rejected(api):
    """PRD 3.11: "the general guard that a requested transition must be defined
    from the resource's current state yields ERR_INVALID_STATE."
    PRD 3.6: "Marking an invoiced order paid advances payment_status from
    INVOICED to PAID."

    Design: Corner/state_machines/pay_without_issued_invoice_returns_invoice_not_found
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=1000, on_hand=100)
    account = create_account(credit_limit_cents=1000000, net_terms_days=30)
    fulfilled = setup_fulfilled_order(product["id"], qty=5,
                                      contractor_account_id=account["id"])
    # payment_status is still UNBILLED; pay (INVOICED->PAID) is undefined here.
    res = api.pay_order(fulfilled["id"], ACCOUNTS)
    validate_error(res, "ERR_INVALID_STATE")


def test_rental_checkout_before_start_rejected(api):
    """PRD 3.7: "the clock must have reached the reservation's start_at, or it
    is rejected with ERR_RENTAL_NOT_STARTED."
    PRD 3.11: "The server's clock starts at a fixed default of midnight UTC on
    the first of January 2026."

    Design: Corner/state_machines/rental_checkout_before_start_returns_not_started
    """
    asset = create_rental_asset()
    agreement = create_reservation(
        asset["id"], "2026-06-01T08:00:00Z", "2026-06-02T08:00:00Z")
    # Default clock 2026-01-01 is before start_at; no clock set call here.
    res = api.check_out_rental(agreement["id"], RENTAL)
    validate_error(res, "ERR_RENTAL_NOT_STARTED")


# ─── Corner: consistency_model ──────────────────────────────────────────────

def test_place_response_carries_recomputed_totals_immediately(api):
    """PRD 3.3: "The provisional total is recomputed at placement."
    PRD 1: "derived balances, loyalty totals, and reorder flags are recomputed
    the moment the events that move them occur, rather than on a deferred
    schedule."

    Design: Corner/consistency_model/place_total_visible_in_same_response
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=1000, on_hand=100)
    order, _ = create_order_with_line(product["id"], qty=10)
    placed = validate_success(api.place_order(
        order["id"], {"expected_sales_order_version": order["version"]}, SALES), 200)
    assert placed["subtotal_cents"] == 10000
    assert placed["total_cents"] == 10000
