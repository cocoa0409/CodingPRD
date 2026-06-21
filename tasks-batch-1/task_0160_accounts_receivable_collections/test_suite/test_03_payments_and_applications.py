"""Cash application: waterfall, short-pay, reversal compensation, validation
precedence, and the full-settle posture cascade.

Queue A (Difficulty): compensating invariant on reversal, transitive cascade on
full settle, two validation-precedence pairs. Queue B (Corner): waterfall,
short-pay, reverse-reverts-status, terminal lockdown, over-application,
immediate consistency, auto-apply with no invoices.
"""
from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    create_customer,
    create_invoice,
    create_payment,
    apply_payment,
    setup_applied_payment,
    setup_written_off_invoice,
    create_payment_application_payload,
)


# --------------------------------------------------------------------------- #
# Queue A — compensating invariant (payment apply then reverse)
# --------------------------------------------------------------------------- #
def test_reverse_restores_total_open_balance(api, ar_manager_headers, ar_clerk_headers):
    """PRD §2.6: "reversing an application must return `total_open_balance_cents`
    to exactly the value it held before the application."
    PRD §3.3: "The governing invariant is that `total_open_balance_cents` returns
    to exactly its pre-application value."

    Design: Difficulty/compensating_invariant/payment_apply_then_reverse_conserves_total_open_balance
    """
    customer = create_customer(name="INV1")
    create_invoice(customer["id"], face_amount_cents=20_000)
    inv_y = create_invoice(customer["id"], face_amount_cents=20_000)
    payment = create_payment(customer["id"], amount_cents=15_000)
    application = apply_payment(payment["id"], inv_y["id"], 15_000)

    validate_success(
        api.reverse_payment_application(payment["id"], application["id"], ar_clerk_headers), 200
    )
    customer_after = validate_success(api.get_customer(customer["id"], ar_manager_headers), 200)
    assert customer_after["total_open_balance_cents"] == 40_000, "restored exactly, no drift"


def test_reverse_restores_invoice_balance(api, ar_manager_headers, ar_clerk_headers):
    """PRD §3.3: "Reversal marks the application `reversed`, restores the
    invoice's `balance_cents` by the application's `applied_cents`, reverts the
    invoice's status if the application had driven it to `PAID` or `PARTIAL`".

    Design: Difficulty/compensating_invariant/payment_apply_then_reverse_conserves_total_open_balance
    """
    customer = create_customer(name="INV1b")
    create_invoice(customer["id"], face_amount_cents=20_000)
    inv_y = create_invoice(customer["id"], face_amount_cents=20_000)
    payment = create_payment(customer["id"], amount_cents=15_000)
    application = apply_payment(payment["id"], inv_y["id"], 15_000)

    validate_success(
        api.reverse_payment_application(payment["id"], application["id"], ar_clerk_headers), 200
    )
    inv_after = validate_success(api.get_invoice(inv_y["id"], ar_manager_headers), 200)
    assert inv_after["balance_cents"] == 20_000


# --------------------------------------------------------------------------- #
# Queue A — transitive cascade (full settle -> PAID -> GOOD -> CURRENT)
# --------------------------------------------------------------------------- #
def test_full_settle_marks_invoice_paid_and_zeroes_exposure(api, ar_manager_headers, ar_clerk_headers):
    """PRD §3.3: "Applying an amount equal to the invoice's `balance_cents`
    settles it: the invoice moves to `PAID` and its `balance_cents` is set to
    zero, whether it started `OPEN` or `PARTIAL`."
    PRD §2.6: "A customer's `exposure_cents` is the sum, over that customer's
    `OPEN` and `PARTIAL` invoices, of each invoice's dunnable balance".

    Design: Difficulty/transitive_cascade/payment_full_settle_cascades_invoice_paid_then_customer_posture
    """
    set_clock("2026-05-01T00:00:00Z")
    customer = create_customer(name="CAS", credit_limit_cents=100_000)
    invoice = create_invoice(
        customer["id"], face_amount_cents=100_000,
        invoice_date="2026-01-15T00:00:00Z", due_date="2026-03-01T00:00:00Z",
    )
    payment = create_payment(customer["id"], amount_cents=100_000, received_at="2026-05-01T00:00:00Z")
    apply_payment(payment["id"], invoice["id"], 100_000)

    inv_after = validate_success(api.get_invoice(invoice["id"], ar_manager_headers), 200)
    customer_after = validate_success(api.get_customer(customer["id"], ar_manager_headers), 200)
    assert inv_after["status"] == "PAID"
    assert customer_after["exposure_cents"] == 0


def test_full_settle_cascades_credit_status_back_to_good(api, ar_manager_headers, ar_clerk_headers):
    """PRD §2.7: "if `exposure_cents` is greater than or equal to
    `credit_limit_cents`, the status is `HOLD`... Otherwise the status is
    `GOOD`."
    PRD §3.3: "Every settlement or partial cascades into the customer:
    `exposure_cents`, `total_open_balance_cents`, `credit_status`, and where an
    invoice reaches a terminal state, `collection_stage` are recomputed."

    Once the only invoice is PAID, exposure is 0, so credit_status returns to
    GOOD (down from the HOLD that exposure==limit had forced).

    Design: Difficulty/transitive_cascade/payment_full_settle_cascades_invoice_paid_then_customer_posture
    """
    set_clock("2026-05-01T00:00:00Z")
    customer = create_customer(name="CASb", credit_limit_cents=100_000)
    invoice = create_invoice(
        customer["id"], face_amount_cents=100_000,
        invoice_date="2026-01-15T00:00:00Z", due_date="2026-03-01T00:00:00Z",
    )
    before = validate_success(api.get_customer(customer["id"], ar_manager_headers), 200)
    assert before["credit_status"] == "HOLD"
    payment = create_payment(customer["id"], amount_cents=100_000, received_at="2026-05-01T00:00:00Z")
    apply_payment(payment["id"], invoice["id"], 100_000)
    after = validate_success(api.get_customer(customer["id"], ar_manager_headers), 200)
    assert after["credit_status"] == "GOOD"


# --------------------------------------------------------------------------- #
# Queue A — validation precedence pairs
# --------------------------------------------------------------------------- #
def test_apply_to_written_off_invoice_returns_invalid_state(api, ar_manager_headers, ar_clerk_headers):
    """PRD §3.10: "Only then are state and business rules evaluated: the generic
    transition guard `ERR_INVALID_STATE`... the over-application and
    over-invoice ceilings `ERR_OVER_APPLICATION` and `ERR_APPLY_EXCEEDS_INVOICE`".

    A WRITTEN_OFF invoice (terminal) accepts no application, and the state guard
    precedes the over-invoice ceiling, so an over-balance apply reports
    ERR_INVALID_STATE rather than ERR_APPLY_EXCEEDS_INVOICE.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_constraint_on_apply_to_writtenoff_invoice_overpay
    """
    customer, invoice, _ = setup_written_off_invoice(
        invoice_face=80_000, credit_limit_cents=500_000, name="PV1"
    )
    payment = create_payment(customer["id"], amount_cents=99_999, received_at="2026-03-01T00:00:00Z")
    res = api.create_payment_application(
        payment["id"],
        create_payment_application_payload(invoice["id"], 99_999),
        ar_clerk_headers,
    )
    validate_error(res, "ERR_INVALID_STATE")


def test_over_apply_to_open_invoice_surfaces_constraint_error(api, ar_manager_headers, ar_clerk_headers):
    """PRD §3.3: "Outside the settle-in-full path, an `applied_cents` that
    exceeds the invoice's dunnable balance is rejected with
    `ERR_APPLY_EXCEEDS_INVOICE` (HTTP 422)."

    When the invoice is in a valid (OPEN) state the over-invoice constraint is
    the one that fires, confirming that the WRITTEN_OFF case reports
    ERR_INVALID_STATE only because the higher-priority state guard pre-empts this
    same constraint.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_constraint_on_apply_to_writtenoff_invoice_overpay
    """
    customer = create_customer(name="PV1b", credit_limit_cents=500_000)
    invoice = create_invoice(customer["id"], face_amount_cents=1000)
    payment = create_payment(customer["id"], amount_cents=5000, received_at="2026-03-01T00:00:00Z")
    res = api.create_payment_application(
        payment["id"],
        create_payment_application_payload(invoice["id"], 2000),
        ar_clerk_headers,
    )
    validate_error(res, "ERR_APPLY_EXCEEDS_INVOICE")


def test_cross_customer_overpay_returns_customer_mismatch(api, ar_manager_headers, ar_clerk_headers):
    """PRD §3.10: "the payment customer-match `ERR_CUSTOMER_MISMATCH`, the
    dispute ceiling `ERR_DISPUTE_EXCEEDS_BALANCE`... the over-application and
    over-invoice ceilings `ERR_OVER_APPLICATION` and `ERR_APPLY_EXCEEDS_INVOICE`".
    PRD §3.3: "if the payment's `customer_id` differs from the invoice's
    `customer_id`, the application is rejected with `ERR_CUSTOMER_MISMATCH`".

    The customer-match check precedes the over-invoice ceiling, so a foreign
    payment over-applied to another customer's invoice reports
    ERR_CUSTOMER_MISMATCH.

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_constraint_on_cross_customer_overpay
    """
    cust_x = create_customer(name="X", credit_limit_cents=500_000)
    cust_y = create_customer(name="Y", credit_limit_cents=500_000)
    inv_y = create_invoice(cust_y["id"], face_amount_cents=1000)
    pay_x = create_payment(cust_x["id"], amount_cents=99_999, received_at="2026-03-01T00:00:00Z")
    res = api.create_payment_application(
        pay_x["id"],
        create_payment_application_payload(inv_y["id"], 5000),
        ar_clerk_headers,
    )
    validate_error(res, "ERR_CUSTOMER_MISMATCH")


def test_cross_customer_in_range_apply_still_mismatch(api, ar_manager_headers, ar_clerk_headers):
    """PRD §3.3: "The payment and the invoice it pays must belong to the same
    account: if the payment's `customer_id` differs from the invoice's
    `customer_id`, the application is rejected with `ERR_CUSTOMER_MISMATCH`
    (HTTP 409)."

    Even when the allocated amount is within the target invoice's balance, a
    foreign payment is refused with ERR_CUSTOMER_MISMATCH — the referential check
    is independent of the over-invoice ceiling it out-ranks.

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_constraint_on_cross_customer_overpay
    """
    cust_x = create_customer(name="Xb", credit_limit_cents=500_000)
    cust_y = create_customer(name="Yb", credit_limit_cents=500_000)
    inv_y = create_invoice(cust_y["id"], face_amount_cents=10_000)
    pay_x = create_payment(cust_x["id"], amount_cents=10_000, received_at="2026-03-01T00:00:00Z")
    res = api.create_payment_application(
        pay_x["id"],
        create_payment_application_payload(inv_y["id"], 3000),  # well within balance
        ar_clerk_headers,
    )
    validate_error(res, "ERR_CUSTOMER_MISMATCH")


# --------------------------------------------------------------------------- #
# Queue B — waterfall, short-pay, reverse, lockdown, over-application
# --------------------------------------------------------------------------- #
def test_waterfall_auto_apply_oldest_aging_first(api, ar_manager_headers, ar_clerk_headers):
    """PRD §3.3: "Auto-apply walks the customer's `OPEN` and `PARTIAL` invoices
    oldest-aging first: ordered by `aging_bucket` with the most overdue bucket
    (`B91_PLUS`) first, then by `due_date` ascending, then by `created_at`
    ascending as the final deterministic tie-break".
    PRD §3.3: "each invoice in turn takes the smaller of the pool remaining and
    that invoice's dunnable balance".

    Design: Corner/calculations/waterfall_auto_apply_oldest_aging_first
    """
    set_clock("2026-06-05T00:00:00Z")
    customer = create_customer(name="WF")
    inv_x = create_invoice(
        customer["id"], face_amount_cents=20_000,
        invoice_date="2026-01-01T00:00:00Z", due_date="2026-02-01T00:00:00Z",
    )  # B91_PLUS
    inv_y = create_invoice(
        customer["id"], face_amount_cents=20_000,
        invoice_date="2026-05-01T00:00:00Z", due_date="2026-05-20T00:00:00Z",
    )  # B1_30
    payment = create_payment(customer["id"], amount_cents=30_000, received_at="2026-06-05T00:00:00Z")
    pay_after = validate_success(api.auto_apply_payment(payment["id"], ar_clerk_headers), 200)
    assert pay_after["unapplied_cents"] == 0

    x_after = validate_success(api.get_invoice(inv_x["id"], ar_manager_headers), 200)
    y_after = validate_success(api.get_invoice(inv_y["id"], ar_manager_headers), 200)
    assert x_after["status"] == "PAID"
    assert y_after["balance_cents"] == 10_000


def test_short_pay_settles_in_full_books_shortfall(api, ar_manager_headers, ar_clerk_headers):
    """PRD §3.3: "when that flag is set and the allocated amount is at most the
    invoice balance, the invoice is settled to `PAID`, its `balance_cents` set to
    zero, and the gap between the prior balance and the amount applied is booked
    on the application as `short_pay_cents`."

    Design: Corner/validations/short_pay_settles_invoice_in_full_books_shortfall
    """
    customer = create_customer(name="SP")
    invoice = create_invoice(customer["id"], face_amount_cents=20_000)
    payment = create_payment(customer["id"], amount_cents=18_000)
    res = api.create_payment_application(
        payment["id"],
        create_payment_application_payload(invoice["id"], 18_000, settle_in_full=True),
        ar_clerk_headers,
    )
    application = validate_success(res, 201)
    assert application["short_pay_cents"] == 2000
    inv_after = validate_success(api.get_invoice(invoice["id"], ar_manager_headers), 200)
    assert inv_after["status"] == "PAID"


def test_reverse_application_reverts_partial_invoice_to_open(api, ar_manager_headers, ar_clerk_headers):
    """PRD §3.3: "Reversal marks the application `reversed`, restores the
    invoice's `balance_cents` by the application's `applied_cents`, reverts the
    invoice's status if the application had driven it to `PAID` or `PARTIAL`".

    Design: Corner/state_machines/reverse_payment_reverts_partial_invoice_status
    """
    customer, invoice, payment, application = setup_applied_payment(
        invoice_face=10_000, applied=4000
    )
    validate_success(
        api.reverse_payment_application(payment["id"], application["id"], ar_clerk_headers), 200
    )
    inv_after = validate_success(api.get_invoice(invoice["id"], ar_manager_headers), 200)
    assert inv_after["status"] == "OPEN"
    assert inv_after["balance_cents"] == 10_000


def test_paid_invoice_rejects_further_application(api, ar_manager_headers, ar_clerk_headers):
    """PRD §3.1: "The `status` of an invoice is one of `OPEN`, `PARTIAL`,
    `DISPUTED`, `PAID`, or `WRITTEN_OFF`, with `PAID` and `WRITTEN_OFF`
    terminal."
    PRD §3.10: "the generic transition guard `ERR_INVALID_STATE`".

    Design: Corner/state_machines/terminal_paid_invoice_rejects_further_application
    """
    customer = create_customer(name="TL")
    invoice = create_invoice(customer["id"], face_amount_cents=4000)
    payment = create_payment(customer["id"], amount_cents=8000)
    apply_payment(payment["id"], invoice["id"], 4000)  # settles -> PAID
    res = api.create_payment_application(
        payment["id"],
        create_payment_application_payload(invoice["id"], 1000),
        ar_clerk_headers,
    )
    validate_error(res, "ERR_INVALID_STATE")


def test_over_application_exceeds_unapplied_rejected(api, ar_manager_headers, ar_clerk_headers):
    """PRD §3.3: "the amount allocated must not exceed the payment's
    `unapplied_cents` — an over-allocation is rejected with
    `ERR_OVER_APPLICATION` (HTTP 422)."

    Design: Corner/validations/over_application_exceeds_unapplied_rejected
    """
    customer = create_customer(name="OA")
    invoice = create_invoice(customer["id"], face_amount_cents=20_000)
    payment = create_payment(customer["id"], amount_cents=5000)
    res = api.create_payment_application(
        payment["id"],
        create_payment_application_payload(invoice["id"], 9000),
        ar_clerk_headers,
    )
    validate_error(res, "ERR_OVER_APPLICATION")


def test_immediate_consistency_exposure_visible_after_apply(api, ar_manager_headers, ar_clerk_headers):
    """PRD §2.6: "Whenever an operation changes what a customer owes, the system
    recomputes the affected derived fields atomically within the same request,
    before the response is returned, so a caller never observes a half-updated
    ledger."

    Design: Corner/consistency_model/immediate_consistency_cascade_visible_in_same_response
    """
    customer = create_customer(name="IM")
    invoice = create_invoice(customer["id"], face_amount_cents=30_000)
    payment = create_payment(customer["id"], amount_cents=12_000)
    apply_payment(payment["id"], invoice["id"], 12_000)
    after = validate_success(api.get_customer(customer["id"], ar_manager_headers), 200)
    assert after["exposure_cents"] == 18_000


def test_auto_apply_no_open_invoices_leaves_payment_unapplied(api, ar_manager_headers, ar_clerk_headers):
    """PRD §3.3: "any pool left over remains on account as `unapplied_cents`."
    PRD §3.3: "A new payment is `UNAPPLIED`, with `applied_cents` zero and
    `unapplied_cents` equal to `amount_cents`."

    With no OPEN/PARTIAL invoices the waterfall allocates nothing, so the entire
    amount stays on account and the payment remains UNAPPLIED.

    Design: Corner/endpoints/auto_apply_no_open_invoices_leaves_payment_unapplied
    """
    customer = create_customer(name="AA0")
    payment = create_payment(customer["id"], amount_cents=5000)
    after = validate_success(api.auto_apply_payment(payment["id"], ar_clerk_headers), 200)
    assert after["unapplied_cents"] == 5000
    assert after["status"] == "UNAPPLIED"
