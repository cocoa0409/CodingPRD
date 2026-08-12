"""Invoicing, payments, void/dispute escapes, and the billing-ledger invariant."""
import pytest
from test_helpers import (
    validate_success, validate_error, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS, assert_invoice, assert_invoice_line_item,
    create_case, create_draft_invoice, add_invoice_line, setup_draft_invoice,
    setup_sent_invoice, send_invoice, record_payment, set_clock, get_case,
    case_version,
)

IC = TEST_USERS["intake_coordinator_headers"]
BC = TEST_USERS["billing_coordinator_headers"]
CLIENT = TEST_USERS["client_headers"]


# ---------------------------------------------------------------------------
# Difficulty: send/void conserves the case billing ledger
# ---------------------------------------------------------------------------

def _setup_sent_20000(api):
    set_clock()
    case, inv = setup_sent_invoice(unit_price_cents=20000, quantity=1,
                                   invoice_type="INSTALLATION",
                                   due_date="2026-06-01T00:00:00Z")
    return case, inv


def test_invoice_send_adds_to_case_billing_totals(api):
    """PRD §3.7: "Sending moves the invoice from `DRAFT` to `SENT`, stamps
    `issue_date`, adds the invoice's `total_cents` into the case's
    `total_billed_cents`, and recomputes the case's `balance_due_cents`."
    PRD §2.8: "`balance_due_cents` is the billed total minus the paid total and is
    never allowed to go negative."

    Design: Difficulty/compensating_invariant/invoice_send_void_conserves_case_billing_ledger
    """
    case, inv = _setup_sent_20000(api)
    assert inv["status"] == "SENT"
    c = get_case(case["id"])
    assert c["total_billed_cents"] == 20000
    assert c["balance_due_cents"] == 20000


def test_invoice_void_exactly_compensates_the_ledger(api):
    """PRD §3.7: "A `BillingCoordinator` may void an invoice in `DRAFT`, `SENT`,
    `PARTIALLY_PAID`, or `OVERDUE` provided nothing has been paid against it —
    `amount_paid_cents` must be zero — which moves it to `VOID` and subtracts its
    total back out of the case's `total_billed_cents`, recomputing the balance
    due."

    Design: Difficulty/compensating_invariant/invoice_send_void_conserves_case_billing_ledger
    """
    case, inv = _setup_sent_20000(api)
    voided = validate_success(api.void_invoice(case["id"], inv["id"], BC), 200)
    assert voided["status"] == "VOID"
    c = get_case(case["id"])
    assert c["total_billed_cents"] == 0, "send's +20000 must be exactly compensated"
    assert c["balance_due_cents"] == 0
    assert c["total_paid_cents"] == 0


# ---------------------------------------------------------------------------
# Corner: per-line tax arithmetic, void guard, dispute, overdue, payment guard
# ---------------------------------------------------------------------------

def test_invoice_line_tax_rounded_per_line(api):
    """PRD §3.7: "Each line's `extended_price_cents` is its quantity multiplied by
    its unit price, rounded half up to whole cents; its `tax_cents` is the
    extended price multiplied by the supplied tax rate and divided by 100, rounded
    half up to whole cents; and its `line_total_cents` is the extended price plus
    the tax. The invoice's `subtotal_cents` is the sum of all extended prices, its
    `tax_cents` the sum of all line taxes, and its `total_cents` the subtotal plus
    the tax."

    Design: Corner/calculations/invoice_line_tax_rounded_per_line
    """
    set_clock()
    case = create_case(client_name="Ott Rhea", client_address="41 Tax Rd",
                       client_phone="555-0308")
    inv = create_draft_invoice(case["id"])
    line = validate_success(api.add_invoice_line_item(
        case["id"], inv["id"],
        {"description": "Service visit", "quantity": 2, "unit_price_cents": 5050,
         "tax_rate_pct": 10.0}, BC), 201)
    assert line["extended_price_cents"] == 10100
    assert line["tax_cents"] == 1010, "round_half_up(10100 * 10 / 100)"
    assert line["line_total_cents"] == 11110
    inv_after = validate_success(api.get_invoice(case["id"], inv["id"], IC), 200)
    assert inv_after["subtotal_cents"] == 10100
    assert inv_after["tax_cents"] == 1010
    assert inv_after["total_cents"] == 11110


def test_invoice_void_after_partial_payment_rejected(api):
    """PRD §3.7: "A `BillingCoordinator` may void an invoice in `DRAFT`, `SENT`,
    `PARTIALLY_PAID`, or `OVERDUE` provided nothing has been paid against it —
    `amount_paid_cents` must be zero". With 4000 already paid the void is not
    available.
    PRD §2.6: "5. **Target resource state.** The resource being acted on must be
    in a state from which the requested transition exists; failure is one of
    `ERR_INVALID_STATE_TRANSITION`, `ERR_QUOTE_NOT_DRAFT`,
    `ERR_ASSESSMENT_NOT_SCHEDULED`, or `ERR_JOB_NOT_IN_PROGRESS` (HTTP 409)."

    Design: Corner/state_machines/invoice_void_after_partial_payment_rejected
    """
    set_clock()
    case, inv = setup_sent_invoice(unit_price_cents=8000)
    paid = record_payment(case["id"], inv["id"], 4000)
    assert paid["status"] == "PARTIALLY_PAID"
    res = api.void_invoice(case["id"], inv["id"], BC)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)
    after = validate_success(api.get_invoice(case["id"], inv["id"], IC), 200)
    assert after["status"] == "PARTIALLY_PAID"
    assert after["amount_paid_cents"] == 4000


def test_invoice_dispute_from_draft_rejected(api):
    """PRD §3.7: "And the `Client` may dispute a `SENT` invoice, moving it to
    `DISPUTED`." From DRAFT that transition does not exist.
    PRD §2.6: "5. **Target resource state.** The resource being acted on must be
    in a state from which the requested transition exists; failure is one of
    `ERR_INVALID_STATE_TRANSITION`, `ERR_QUOTE_NOT_DRAFT`,
    `ERR_ASSESSMENT_NOT_SCHEDULED`, or `ERR_JOB_NOT_IN_PROGRESS` (HTTP 409)."

    Design: Corner/state_machines/invoice_dispute_from_draft_rejected
    """
    set_clock()
    case, inv = setup_draft_invoice(unit_price_cents=3000)
    res = api.dispute_invoice(case["id"], inv["id"], CLIENT)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)
    after = validate_success(api.get_invoice(case["id"], inv["id"], IC), 200)
    assert after["status"] == "DRAFT"


def test_invoice_overdue_when_past_due_with_balance(api):
    """PRD §2.9: "The time-driven transitions are: a quote in DRAFT, SUBMITTED, or
    UNDER_REVIEW whose `valid_until` has passed becomes EXPIRED; an invoice in
    SENT or PARTIALLY_PAID whose `due_date` has passed with a positive balance
    becomes OVERDUE; an OT consultation still SCHEDULED once its `scheduled_date`
    has passed becomes NO_SHOW; a reassessment schedule in PENDING or SCHEDULED
    whose `due_date` has passed becomes OVERDUE; and an installed rental ramp
    becomes IN_USE automatically while its rental period is active."

    Design: Corner/state_machines/invoice_overdue_when_past_due_with_balance
    """
    set_clock()
    case, inv = setup_sent_invoice(unit_price_cents=8000, invoice_type="INSTALLATION",
                                   due_date="2026-06-01T00:00:00Z")
    set_clock("2026-06-02T00:00:00Z")
    after = validate_success(api.get_invoice(case["id"], inv["id"], IC), 200)
    assert after["status"] == "OVERDUE"
    assert after["balance_cents"] == 8000


def test_client_dispute_sent_invoice_succeeds(api):
    """PRD §3.7: "And the `Client` may dispute a `SENT` invoice, moving it to
    `DISPUTED`."

    Design: Corner/endpoints/client_dispute_sent_invoice_succeeds
    """
    set_clock()
    case, inv = setup_sent_invoice(unit_price_cents=3000)
    disputed = validate_success(api.dispute_invoice(case["id"], inv["id"], CLIENT), 200)
    assert disputed["status"] == "DISPUTED"


def test_payment_above_balance_returns_422(api):
    """PRD §3.7: "A `BillingCoordinator` records a payment of `amount_cents`
    against a `SENT` or `PARTIALLY_PAID` invoice. A payment larger than the
    outstanding balance is rejected with `ERR_PAYMENT_EXCEEDS_BALANCE`."

    Design: Corner/errors/payment_above_balance_returns_422
    """
    set_clock()
    case, inv = setup_sent_invoice(unit_price_cents=8000)
    res = api.record_payment(case["id"], inv["id"], {"amount_cents": 8001}, BC)
    validate_error(res, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE, expected_status=422)
    after = validate_success(api.get_invoice(case["id"], inv["id"], IC), 200)
    assert after["status"] == "SENT"
    assert after["amount_paid_cents"] == 0


def test_invoice_not_found_returns_404(api):
    """PRD §2.7: "The not-found errors are: `ERR_CASE_NOT_FOUND` for a case,
    `ERR_ASSESSMENT_NOT_FOUND` for an assessment, `ERR_QUOTE_NOT_FOUND` for a
    quote, `ERR_FUNDING_SOURCE_NOT_FOUND` for a funding source, `ERR_JOB_NOT_FOUND`
    for an installation job, `ERR_RAMP_NOT_FOUND` for a rental ramp,
    `ERR_UNIT_NOT_FOUND` for an inventory unit, `ERR_INSPECTION_NOT_FOUND` for an
    inspection, `ERR_INVOICE_NOT_FOUND` for an invoice, `ERR_CLAIM_NOT_FOUND` for
    a warranty claim, `ERR_CONSULT_NOT_FOUND` for an OT consultation, and
    `ERR_SCHEDULE_NOT_FOUND` for a reassessment schedule — each with HTTP 404."

    Design: Corner/errors/invoice_not_found_returns_404
    """
    case = create_case(client_name="NF Inv", client_address="57 NF Rd",
                       client_phone="555-0607")
    res = api.get_invoice(case["id"], NON_EXISTENT_UUID, IC)
    validate_error(res, ApiErrorId.ERR_INVOICE_NOT_FOUND, expected_status=404)
