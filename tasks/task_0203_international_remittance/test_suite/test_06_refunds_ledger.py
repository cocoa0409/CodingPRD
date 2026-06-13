"""Refunds, cancellations, and the corridor-reservation conservation.

Covers the dual fee variant (sender-cancel grace window vs fault refund), the
DELIVERY_FAILED attempts-exhausted gate, the reservation-conservation invariant,
and the refund-reason / delivery-state compatibility check.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    setup_funded_transfer, setup_transfer_with_failed_attempts,
    create_refund_payload, advance_clock_payload,
    get_corridor, ledger_entries_for, ledger_net,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
AGENT = TEST_USERS["remittance_agent_headers"]
OPERATOR = TEST_USERS["payout_operator_headers"]


# ─── dual-variant: sender-cancel outside grace vs compliance-reject ─────────

def test_sender_cancel_outside_grace_retains_fee(api):
    """PRD §3.7: "if the current clock is within 3600 seconds of that funded instant
    (at or below the grace window), `fee_refunded_minor` equals the transfer's
    `fee_minor`; if the clock is past the grace window, `fee_refunded_minor` is 0 and
    the provider retains the fee."

    Design: Difficulty/dual_variant_calc/refund_fee_variant_diverges_sender_cancel_vs_compliance_reject
    """
    corridor, sender, recipient, quote, transfer = setup_funded_transfer(
        send_principal_minor=50000, recipient_verified=True)
    # Advance well past the 3600s grace window before cancelling.
    api.advance_clock(advance_clock_payload(seconds=4000), ADMIN)
    refund = validate_success(api.create_refund(
        create_refund_payload(transfer["id"], "SENDER_CANCEL"), AGENT), 201)
    assert refund["principal_refunded_minor"] == 50000, refund["principal_refunded_minor"]
    assert refund["fee_refunded_minor"] == 0, refund["fee_refunded_minor"]
    assert refund["total_refunded_minor"] == 50000, refund["total_refunded_minor"]
    after = validate_success(api.get_transfer(transfer["id"], AGENT), 200)
    assert after["delivery_status"] == "REFUNDED", after["delivery_status"]


def test_compliance_reject_fully_reverses_fee_on_same_shape(api):
    """PRD §3.7: "For a `COMPLIANCE_REJECT` or a `DELIVERY_FAILED` — neither of which
    is the sender's fault — the fee is always fully reversed when it was charged:
    `fee_refunded_minor` equals `fee_minor` when `funding_status` is `FUNDED`, and 0
    otherwise, with no grace-window dependence."

    Design: Difficulty/dual_variant_calc/refund_fee_variant_diverges_sender_cancel_vs_compliance_reject
    """
    from test_helpers import setup_held_transfer_with_case, decide_case_payload, validate_paginated
    corridor, sender, recipient, transfer, case = setup_held_transfer_with_case(
        send_principal_minor=50000)
    # Same funded shape (P=50000, fee=799); reject drives the COMPLIANCE_REJECT refund.
    validate_success(api.decide_compliance_case(
        case["id"], decide_case_payload("REJECT", case["version"]), TEST_USERS["compliance_officer_headers"]), 200)
    data, _meta = validate_paginated(api.list_refunds(AGENT, params={"transfer_id": transfer["id"]}))
    assert data, "expected a compliance-reject refund"
    refund = data[0]
    assert refund["reason"] == "COMPLIANCE_REJECT", refund["reason"]
    assert refund["principal_refunded_minor"] == 50000, refund["principal_refunded_minor"]
    assert refund["fee_refunded_minor"] == 799, refund["fee_refunded_minor"]
    assert refund["total_refunded_minor"] == 50799, refund["total_refunded_minor"]


# ─── sender-cancel within grace refunds fee (corner: calculations) ──────────

def test_sender_cancel_within_grace_refunds_full_fee(api):
    """PRD §3.7: "if the current clock is within 3600 seconds of that funded instant
    (at or below the grace window), `fee_refunded_minor` equals the transfer's
    `fee_minor`."

    Design: Corner/calculations/sender_cancel_within_grace_refunds_fee
    """
    corridor, sender, recipient, quote, transfer = setup_funded_transfer(
        send_principal_minor=50000, recipient_verified=True)
    # No clock advance -> well inside the grace window.
    refund = validate_success(api.create_refund(
        create_refund_payload(transfer["id"], "SENDER_CANCEL"), AGENT), 201)
    assert refund["principal_refunded_minor"] == 50000, refund["principal_refunded_minor"]
    assert refund["fee_refunded_minor"] == 799, refund["fee_refunded_minor"]
    assert refund["total_refunded_minor"] == 50799, refund["total_refunded_minor"]


# ─── reservation-conservation on DELIVERY_FAILED refund (invariant) ─────────

def test_delivery_failed_refund_restores_reservation(api):
    """PRD §3.7: "When a refund actually moves money for a funded transfer, it restores
    the corridor: `reserved_minor` is decreased by `send_principal_minor`."

    Design: Difficulty/compensating_invariant/refund_conserves_corridor_reservation_quantity
    """
    corridor, transfer = setup_transfer_with_failed_attempts(num_failed=2, send_principal_minor=50000)
    before = get_corridor(corridor["id"])
    assert before["reserved_minor"] == 50000, before["reserved_minor"]
    refund = validate_success(api.create_refund(
        create_refund_payload(transfer["id"], "DELIVERY_FAILED"), OPERATOR), 201)
    assert refund["principal_refunded_minor"] == 50000, refund["principal_refunded_minor"]
    assert refund["fee_refunded_minor"] == 799, refund["fee_refunded_minor"]
    after = get_corridor(corridor["id"])
    assert after["reserved_minor"] == 0, after["reserved_minor"]


def test_delivery_failed_refund_marks_transfer_refunded(api):
    """PRD §3.7: "A `PayoutOperator` may refund a delivery that has exhausted its
    attempts with reason `DELIVERY_FAILED`, allowed only while `delivery_status` is
    `FAILED` and only once the count of `FAILED` attempts has reached the maximum of 2."

    Design: Difficulty/compensating_invariant/refund_conserves_corridor_reservation_quantity
    """
    corridor, transfer = setup_transfer_with_failed_attempts(num_failed=2, send_principal_minor=50000)
    refund = validate_success(api.create_refund(
        create_refund_payload(transfer["id"], "DELIVERY_FAILED"), OPERATOR), 201)
    after = validate_success(api.get_transfer(transfer["id"], AGENT), 200)
    assert after["delivery_status"] == "REFUNDED", after["delivery_status"]


# ─── attempts-not-exhausted gate (corner: validations) ──────────────────────

def test_delivery_failed_refund_before_exhaustion_rejected(api):
    """PRD §3.7: "a refund attempted before attempts are exhausted is rejected with
    `ERR_ATTEMPTS_NOT_EXHAUSTED`."

    Design: Corner/validations/delivery_failed_refund_before_attempts_exhausted_rejected
    """
    corridor, transfer = setup_transfer_with_failed_attempts(num_failed=1, send_principal_minor=50000)
    assert transfer["delivery_status"] == "FAILED"
    res = api.create_refund(create_refund_payload(transfer["id"], "DELIVERY_FAILED"), OPERATOR)
    validate_error(res, "ERR_ATTEMPTS_NOT_EXHAUSTED")
    after = validate_success(api.get_transfer(transfer["id"], AGENT), 200)
    assert after["delivery_status"] == "FAILED", after["delivery_status"]


# ─── refund reason / delivery-state mismatch (corner: errors) ───────────────

def test_delivery_failed_refund_on_pending_transfer_rejected(api):
    """PRD §3.7: "A refund whose reason does not fit the transfer's current
    `delivery_status` is rejected with `ERR_REFUND_NOT_ALLOWED`."

    Design: Corner/errors/refund_wrong_reason_for_delivery_state_returns_not_allowed
    """
    corridor, sender, recipient, quote, transfer = setup_funded_transfer(
        send_principal_minor=50000, recipient_verified=True)
    assert transfer["delivery_status"] == "PENDING"
    res = api.create_refund(create_refund_payload(transfer["id"], "DELIVERY_FAILED"), OPERATOR)
    validate_error(res, "ERR_REFUND_NOT_ALLOWED")
    after = validate_success(api.get_transfer(transfer["id"], AGENT), 200)
    assert after["delivery_status"] == "PENDING", after["delivery_status"]
