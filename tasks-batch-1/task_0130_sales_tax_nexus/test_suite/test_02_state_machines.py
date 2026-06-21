"""State machines: valid transitions, invalid-from rejections, idempotency,
terminal lockdown, the parallel settlement/audit dimensions, and the
certificate revoke/reinstate cycle.

Queue A: non_linear_state_machine (≥2 tests per instance).
Queue B: state_machines section.
"""
import pytest

from test_helpers import (
    make_seller_headers,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    make_approver_headers,
    make_auditor_headers,
    make_preparer_headers,
)


# ===========================================================================
# Queue A — non_linear_state_machine
# ===========================================================================

def test_flag_pending_transaction_audit_independent_of_settlement(api):
    """PRD §3.6: "Flagging is allowed whether the transaction is still `PENDING` or already `SETTLED`, because the audit dimension evolves independently of settlement."

    Design: Difficulty/non_linear_state_machine/transaction_parallel_settlement_and_audit_dimensions
    """
    jur, seller = fx.setup_ca_seller(with_category=True)
    txn = fx.create_pending_transaction(seller["id"], jur["id"], customer_ref="b1",
                                        customer_exempt_requested=False)
    fx.add_line_item(seller["id"], txn["id"], "TANGIBLE", quantity=1, unit_price=7.95)
    res = api.flag_transaction(txn["id"], make_auditor_headers())
    flagged = validate_success(res, 200)
    assert flagged["audit_status"] == "FLAGGED", f"got {flagged['audit_status']}"
    assert flagged["settlement_status"] == "PENDING", \
        f"settlement must remain PENDING while flagging, got {flagged['settlement_status']}"


def test_flag_then_clear_audit_dimension_progresses_independently(api):
    """PRD §3.6: "An auditor may flag a transaction, advancing `UNREVIEWED → FLAGGED`; this is permitted only from `UNREVIEWED` and is otherwise rejected with `ERR_INVALID_STATE`."
    PRD §3.6: "An auditor may then clear a flagged transaction, advancing `FLAGGED → CLEARED`; this is permitted only from `FLAGGED` and is otherwise rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/non_linear_state_machine/transaction_parallel_settlement_and_audit_dimensions
    """
    jur, seller = fx.setup_ca_seller(with_category=True)
    txn = fx.create_pending_transaction(seller["id"], jur["id"], customer_ref="b1",
                                        customer_exempt_requested=False)
    fx.add_line_item(seller["id"], txn["id"], "TANGIBLE", quantity=1, unit_price=7.95)
    flagged = validate_success(api.flag_transaction(txn["id"], make_auditor_headers()), 200)
    assert flagged["audit_status"] == "FLAGGED"
    cleared = validate_success(api.clear_transaction(txn["id"], make_auditor_headers()), 200)
    assert cleared["audit_status"] == "CLEARED", f"got {cleared['audit_status']}"
    assert cleared["settlement_status"] == "PENDING", \
        f"settlement still PENDING after audit cycle, got {cleared['settlement_status']}"


def test_certificate_revoke_then_reinstate_returns_to_active(api):
    """PRD §3.7: "A seller may revoke an `ACTIVE` certificate, advancing its `status` `ACTIVE → REVOKED`; this is permitted only from `ACTIVE` and is otherwise rejected with `ERR_INVALID_STATE`."
    PRD §3.7: "A seller may reinstate a `REVOKED` certificate, advancing its `status` `REVOKED → ACTIVE`, but only while the certificate is still within its window — the current clock must be strictly before `valid_to`."

    Design: Difficulty/non_linear_state_machine/exemption_certificate_revoke_reinstate_cycle
    """
    fx.set_clock("2026-01-01T00:00:00Z")
    jur = fx.create_ca_jurisdiction()
    seller = fx.create_seller(origin_state_code="CA")
    cert = fx.create_certificate(seller["id"], jur["id"], customer_ref="b1",
                                 exempt_category_code="TANGIBLE",
                                 valid_from="2026-01-01T00:00:00Z",
                                 valid_to="2027-01-01T00:00:00Z")
    revoked = fx.revoke_certificate(seller["id"], cert["id"])
    assert revoked["status"] == "REVOKED", f"got {revoked['status']}"
    res = api.reinstate_exemption_certificate(cert["id"], make_seller_headers(seller["id"]))
    reinstated = validate_success(res, 200)
    assert reinstated["status"] == "ACTIVE", f"expected ACTIVE after reinstate, got {reinstated['status']}"


def test_certificate_revoke_reinstate_version_increments_each_transition(api):
    """PRD §2.4: "`version` is an integer that begins at its initial value and increases by exactly one on every mutation of the resource".
    PRD §3.7: "Each revoke appends an `AuditLogEntry` recording the certificate revocation and each reinstatement appends one recording the reinstatement, and each action increments the certificate's `version`."

    Design: Difficulty/non_linear_state_machine/exemption_certificate_revoke_reinstate_cycle
    """
    fx.set_clock("2026-01-01T00:00:00Z")
    jur = fx.create_ca_jurisdiction()
    seller = fx.create_seller(origin_state_code="CA")
    cert = fx.create_certificate(seller["id"], jur["id"], customer_ref="b1",
                                 exempt_category_code="TANGIBLE",
                                 valid_from="2026-01-01T00:00:00Z",
                                 valid_to="2027-01-01T00:00:00Z")
    assert cert["version"] == 1, f"created certificate version must be 1, got {cert['version']}"
    fx.revoke_certificate(seller["id"], cert["id"])  # version -> 2
    res = api.reinstate_exemption_certificate(cert["id"], make_seller_headers(seller["id"]))
    reinstated = validate_success(res, 200)  # version -> 3
    assert reinstated["version"] == 3, \
        f"create(1) -> revoke(2) -> reinstate(3); got version {reinstated['version']}"


# ===========================================================================
# Queue B — state_machines section
# ===========================================================================

def test_settle_pending_transaction_moves_to_settled(api):
    """PRD §3.4: "On success the settlement advances `PENDING → SETTLED`, appends an `AuditLogEntry` recording the settle, and increments the transaction's `version` by one."

    Design: Corner/state_machines/settle_pending_transaction_moves_to_settled
    """
    jur, seller = fx.setup_ca_seller(with_category=True)
    txn = fx.create_transaction_with_lines(
        seller["id"], jur["id"],
        [{"category_code": "TANGIBLE", "quantity": 1, "unit_price": 10.00}],
        customer_ref="b1", customer_exempt_requested=False)
    res = api.settle_transaction(txn["id"], make_seller_headers(seller["id"]))
    settled = validate_success(res, 200)
    assert settled["settlement_status"] == "SETTLED", f"got {settled['settlement_status']}"
    # FULL line 10.00 @ 0.0825 -> round_half_up(0.825) == 0.83.
    assert settled["tax_collected"] == 0.83, f"expected tax_collected 0.83, got {settled['tax_collected']}"


def test_settle_transaction_with_no_line_items_returns_invalid_state(api):
    """PRD §3.4: "settling from any other state, or settling a transaction that has no line items, is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/settle_transaction_with_no_line_items_returns_invalid_state
    """
    jur, seller = fx.setup_ca_seller(with_category=False)
    txn = fx.create_pending_transaction(seller["id"], jur["id"], customer_ref="b1",
                                        customer_exempt_requested=False)
    res = api.settle_transaction(txn["id"], make_seller_headers(seller["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_settle_already_settled_transaction_returns_invalid_state(api):
    """PRD §3.4: "A transaction may be settled only from the `PENDING` settlement state; settling from any other state, or settling a transaction that has no line items, is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/settle_already_settled_transaction_idempotency_returns_invalid_state
    """
    jur, seller = fx.setup_ca_seller(with_category=True)
    settled = fx.create_and_settle_transaction(
        seller["id"], jur["id"],
        [{"category_code": "TANGIBLE", "quantity": 1, "unit_price": 10.00}],
        customer_ref="b1", customer_exempt_requested=False)
    res = api.settle_transaction(settled["id"], make_seller_headers(seller["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_void_pending_transaction_returns_invalid_state(api):
    """PRD §3.5: "Voiding from any state other than `SETTLED` is rejected with `ERR_INVALID_STATE`, and voiding a transaction whose `tax_return_id` is already set (it has been swept into a return) is rejected with `ERR_TRANSACTION_LOCKED`."

    Design: Corner/state_machines/void_pending_transaction_invalid_from_returns_invalid_state
    """
    jur, seller = fx.setup_ca_seller(with_category=False)
    txn = fx.create_pending_transaction(seller["id"], jur["id"], customer_ref="b1",
                                        customer_exempt_requested=False)
    res = api.void_transaction(txn["id"], make_seller_headers(seller["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_clear_unflagged_transaction_returns_invalid_state(api):
    """PRD §3.6: "An auditor may then clear a flagged transaction, advancing `FLAGGED → CLEARED`; this is permitted only from `FLAGGED` and is otherwise rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/clear_unflagged_transaction_invalid_from_returns_invalid_state
    """
    jur, seller = fx.setup_ca_seller(with_category=False)
    txn = fx.create_pending_transaction(seller["id"], jur["id"], customer_ref="b1",
                                        customer_exempt_requested=False)
    res = api.clear_transaction(txn["id"], make_auditor_headers())
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_reinstate_certificate_past_validity_window_returns_validation_failed(api):
    """PRD §3.7: "reinstating a certificate whose window has already ended (the current clock is at or after `valid_to`) is rejected with `ERR_VALIDATION_FAILED`."

    Design: Corner/state_machines/reinstate_certificate_past_validity_window_returns_validation_failed
    """
    fx.set_clock("2026-01-01T00:00:00Z")
    jur = fx.create_ca_jurisdiction()
    seller = fx.create_seller(origin_state_code="CA")
    cert = fx.create_certificate(seller["id"], jur["id"], customer_ref="b1",
                                 exempt_category_code="TANGIBLE",
                                 valid_from="2026-01-01T00:00:00Z",
                                 valid_to="2026-02-01T00:00:00Z")
    fx.revoke_certificate(seller["id"], cert["id"])
    fx.set_clock("2026-03-01T00:00:00Z")  # past valid_to
    res = api.reinstate_exemption_certificate(cert["id"], make_seller_headers(seller["id"]))
    validate_error(res, "ERR_VALIDATION_FAILED", expected_status=422)


def test_remit_filed_return_reaches_terminal_remitted(api):
    """PRD §3.10: "On success the system creates a `RemittancePayment` whose `status` is `APPLIED`, advances the return `FILED → REMITTED`, appends an `AuditLogEntry` recording the remittance, and increments the return's `version`."

    Design: Corner/state_machines/remit_filed_return_reaches_terminal_remitted
    """
    ctx = fx.setup_filed_return_ca(small_unit_price=10.00)
    ret = ctx["tax_return"]
    assert ret["tax_due"] == 0.83, f"setup sanity: expected tax_due 0.83, got {ret['tax_due']}"
    payload = {
        "tax_return_id": ret["id"],
        "amount": 0.83,
        "expected_tax_return_version": ctx["filed_version"],
    }
    res = api.create_remittance_payment(payload, make_approver_headers())
    payment = validate_success(res, 201)
    assert payment["amount"] == 0.83, f"got {payment['amount']}"
    refetched = validate_success(api.get_tax_return(ret["id"], make_approver_headers()), 200)
    assert refetched["status"] == "REMITTED", f"expected REMITTED, got {refetched['status']}"


def test_reopen_rejected_return_reverts_to_draft(api):
    """PRD §3.9: "A rejected return is not a dead end: a `TaxPreparer` may reopen it, advancing `REJECTED → DRAFT` so the return can be corrected and resubmitted."

    Design: Corner/state_machines/reopen_rejected_return_reverts_to_draft
    """
    jur, seller = fx.setup_ca_seller(with_category=False)
    ret = fx.create_draft_return(seller["id"], jur["id"])
    validate_success(api.reject_tax_return(ret["id"], make_approver_headers()), 200)
    res = api.reopen_tax_return(ret["id"], make_preparer_headers())
    reopened = validate_success(res, 200)
    assert reopened["status"] == "DRAFT", f"expected DRAFT after reopen, got {reopened['status']}"
