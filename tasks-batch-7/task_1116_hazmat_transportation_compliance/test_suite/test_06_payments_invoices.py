"""Payments, credits, the payment waterfall, invoice lifecycle, and the
outstanding-balance invariant."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    create_carrier, submit_registration, approve_registration,
    create_approved_carrier_paid, pay_outstanding, list_invoices, set_clock,
)
from test_helpers.fixtures import ADMIN, OFFICER_A, REGULATOR, _ok


# ---------------------------------------------------------------------------
# compensating_invariant / invoice_void_restores_outstanding
# ---------------------------------------------------------------------------

def _setup_reinstated_carrier(api):
    """Carrier APPROVED_ACTIVE, INITIAL invoice PAID (outstanding 0), then
    suspended + reinstated so an OPEN REINSTATEMENT invoice of 75000 exists."""
    carrier = create_approved_carrier_paid(hazmat_categories=["FLAMMABLE_LIQUID"])
    after_pay = validate_success(api.get_carrier(carrier["id"], REGULATOR))
    assert after_pay["outstanding_balance_cents"] == 0
    _ok(api.suspend_carrier(carrier["id"], REGULATOR), "suspend")
    reinstated = validate_success(api.reinstate_carrier(carrier["id"], REGULATOR))
    assert reinstated["registration_status"] == "APPROVED_ACTIVE"
    return reinstated


def test_reinstatement_invoice_is_flat_75000_and_raises_balance(api):
    """PRD §3.1: "Reinstatement requires `SUSPENDED`, else
    `ERR_CARRIER_NOT_SUSPENDED`, creates an invoice whose `kind` is
    `REINSTATEMENT` with a flat `total_due_cents` of 75000 cents — no tiered
    calculation, no processing fee, no discount".
    PRD §3.2: "the carrier's `outstanding_balance_cents` is always the sum, over
    exactly its `OPEN` invoices, of each invoice's `total_due_cents` minus its
    `paid_cents`".

    Design: Difficulty/compensating_invariant/invoice_void_restores_outstanding
    """
    carrier = _setup_reinstated_carrier(api)
    invoices = list_invoices(carrier["id"])
    reinstatement = invoices[1]
    assert reinstatement["kind"] == "REINSTATEMENT"
    assert reinstatement["total_due_cents"] == 75000
    fresh = validate_success(api.get_carrier(carrier["id"], REGULATOR))
    assert fresh["outstanding_balance_cents"] == 75000


def test_invoice_void_restores_outstanding_balance(api):
    """PRD §3.2: "A `Regulator` may also void an `OPEN` invoice as a
    compensating action — any other status yields `ERR_INVOICE_NOT_VOIDABLE` —
    which moves the invoice to `VOID` and recomputes the balance with the
    voided invoice excluded."
    PRD §3.2: "`PAID` and `VOID` invoices contribute nothing."

    Design: Difficulty/compensating_invariant/invoice_void_restores_outstanding
    """
    carrier = _setup_reinstated_carrier(api)
    reinstatement = list_invoices(carrier["id"])[1]

    voided = validate_success(api.void_invoice(reinstatement["id"], REGULATOR))
    assert voided["status"] == "VOID"
    fresh = validate_success(api.get_carrier(carrier["id"], REGULATOR))
    assert fresh["outstanding_balance_cents"] == 0, (
        "voiding the only OPEN invoice restores the pre-action balance")


# ---------------------------------------------------------------------------
# Corner/calculations/payment_waterfall_order_and_credit
# ---------------------------------------------------------------------------

def _setup_two_open_invoices(api):
    """EXPLOSIVE carrier: INITIAL PAID (38750); REINSTATEMENT OPEN 75000
    (year 2026); early-renewal RENEWAL submitted in 2027, OPEN provisional
    40000 (year 2027)."""
    carrier = create_approved_carrier_paid(hazmat_categories=["EXPLOSIVE"])
    _ok(api.suspend_carrier(carrier["id"], REGULATOR), "suspend")
    _ok(api.reinstate_carrier(carrier["id"], REGULATOR), "reinstate")
    set_clock("2027-04-15T00:00:00Z")  # inside early-renewal window
    fresh = validate_success(api.get_carrier(carrier["id"], REGULATOR))
    invoice = submit_registration(fresh)
    # renewal provisional: (25000 + 12500 surcharge, months_late 0) subtotal
    # 37500 < 100000 => flat 2500 => 40000
    assert invoice["kind"] == "RENEWAL"
    assert invoice["provisional_total_cents"] == 40000
    return fresh


def test_payment_waterfall_fills_oldest_year_first(api):
    """PRD §3.2: "The targets are the carrier's `OPEN` invoices ordered by
    `assessment_year` ascending, ties broken by `created_at` ascending — never
    by id. Each invoice in turn receives the lesser of its remaining due and the
    remaining pool; an invoice whose `paid_cents` reaches its `total_due_cents`
    flips from `OPEN` to `PAID`."

    Design: Corner/calculations/payment_waterfall_order_and_credit
    """
    carrier = _setup_two_open_invoices(api)
    paid = validate_success(api.pay_carrier(carrier["id"], {"amount_cents": 50000}, ADMIN))
    # 50000 fills the 2026 REINSTATEMENT first: 75000 -> 25000 remaining;
    # RENEWAL (2027) untouched at 40000
    assert paid["outstanding_balance_cents"] == 65000
    assert paid["credit_balance_cents"] == 0


def test_payment_waterfall_overflow_becomes_credit(api):
    """PRD §3.2: "The pool begins as the payment amount plus the carrier's
    `credit_balance_cents`, so previously overpaid credit is consumed first."
    PRD §3.2: "Any pool remainder after all open invoices are satisfied is held
    as the carrier's new `credit_balance_cents`, and the carrier's
    `outstanding_balance_cents` is recomputed."
    PRD §2.3: "Unless an endpoint states otherwise, list results are ordered by
    `created_at` ascending."

    Design: Corner/calculations/payment_waterfall_order_and_credit
    """
    carrier = _setup_two_open_invoices(api)
    _ok(api.pay_carrier(carrier["id"], {"amount_cents": 50000}, ADMIN), "pay 50000")
    paid = validate_success(api.pay_carrier(carrier["id"], {"amount_cents": 100000}, ADMIN))
    # 100000: 25000 closes REINSTATEMENT, 40000 closes RENEWAL, 35000 overflows
    assert paid["outstanding_balance_cents"] == 0
    assert paid["credit_balance_cents"] == 35000

    invoices = list_invoices(carrier["id"])
    assert [inv["status"] for inv in invoices] == ["PAID", "PAID", "PAID"]
    assert invoices[1]["paid_cents"] == 75000
    assert invoices[2]["paid_cents"] == 40000


# ---------------------------------------------------------------------------
# Corner/state_machines/invoice_auto_paid_on_exact_payment
# ---------------------------------------------------------------------------

def test_invoice_auto_paid_on_exact_payment(api):
    """PRD §3.2: "Each invoice in turn receives the lesser of its remaining due
    and the remaining pool; an invoice whose `paid_cents` reaches its
    `total_due_cents` flips from `OPEN` to `PAID`."
    PRD §3.2: "the carrier's `outstanding_balance_cents` is always the sum, over
    exactly its `OPEN` invoices, of each invoice's `total_due_cents` minus its
    `paid_cents`".

    Design: Corner/state_machines/invoice_auto_paid_on_exact_payment
    """
    carrier = create_carrier(fleet_size_declared=5, hazmat_categories=["FLAMMABLE_LIQUID"])
    submit_registration(carrier)
    approve_registration(carrier, verified_fleet_size=5)

    paid = validate_success(api.pay_carrier(carrier["id"], {"amount_cents": 26250}, ADMIN))
    assert paid["outstanding_balance_cents"] == 0, "payment response reflects the new balance immediately"
    invoice = list_invoices(carrier["id"])[0]
    assert invoice["status"] == "PAID"
    assert invoice["paid_cents"] == 26250


# ---------------------------------------------------------------------------
# Corner/consistency_model/payment_response_shows_updated_balance_immediately
# ---------------------------------------------------------------------------

def test_payment_response_shows_updated_balance_immediately(api):
    """PRD §3.2: "Any pool remainder after all open invoices are satisfied is
    held as the carrier's new `credit_balance_cents`, and the carrier's
    `outstanding_balance_cents` is recomputed."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/consistency_model/payment_response_shows_updated_balance_immediately
    """
    carrier = create_carrier(fleet_size_declared=5, hazmat_categories=["FLAMMABLE_LIQUID"])
    submit_registration(carrier)
    approve_registration(carrier, verified_fleet_size=5)

    paid = validate_success(api.pay_carrier(carrier["id"], {"amount_cents": 30000}, ADMIN))
    # 30000 - 26250 = 3750 overage becomes credit in the same response
    assert paid["outstanding_balance_cents"] == 0
    assert paid["credit_balance_cents"] == 3750


# ---------------------------------------------------------------------------
# Corner/errors/invoice_not_voidable_when_paid
# ---------------------------------------------------------------------------

def test_invoice_not_voidable_when_paid(api):
    """PRD §3.2: "A `Regulator` may also void an `OPEN` invoice as a
    compensating action — any other status yields `ERR_INVOICE_NOT_VOIDABLE`".

    Design: Corner/errors/invoice_not_voidable_when_paid
    """
    carrier = create_approved_carrier_paid(hazmat_categories=["FLAMMABLE_LIQUID"])
    invoice = list_invoices(carrier["id"])[0]
    assert invoice["status"] == "PAID"

    resp = api.void_invoice(invoice["id"], REGULATOR)
    validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_VOIDABLE)
