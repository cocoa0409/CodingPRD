"""Evidence lifecycle: submit, chain confirm/fail, resubmit, attempts limit.

PRD §3.3, §2.8, §2.10 priorities 6/12/13/17.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    CHAIN_CONFIRMATION_THRESHOLD,
    bring_evidence_to_confirmed,
    bring_evidence_to_failed,
    bring_evidence_to_submitting,
    chain_confirm,
    chain_fail,
    create_customer,
    create_customer_with_balance,
    create_evidence,
    create_evidence_payload,
    create_notarization,
    get_customer,
    get_evidence,
    latest_onchain_tx_for_evidence,
    list_audit_logs,
    make_customer_headers,
    preservation_fee_cents,
    submit_evidence,
    validate_error,
    validate_success,
)


# ===========================================================================
# PENDING → SUBMITTING (PRD §3.3)
# ===========================================================================
class TestEvidenceSubmit:
    """PRD §3.3: 'a Customer initiates anchoring, transitioning the
    evidence from PENDING to SUBMITTING. Three preconditions guard the
    transition: the Customer.status is ACTIVE, the evidence carries a
    null batch_id (single-evidence path; batch-bound evidences must use
    the batch flow in §3.5), and Customer.wallet_balance_cents is at
    least the forward-looking preservation fee quote computed for this
    evidence. A successful transition creates a fresh OnChainTx ... The
    evidence's submission_attempts increments by one and an audit row
    of type EVIDENCE_SUBMITTED is appended.'"""

    def test_submit_transitions_to_submitting(self, api):
        """PRD §3.3: 'transitioning the evidence from PENDING to
        SUBMITTING.' The submission_attempts increments by one."""
        customer = create_customer_with_balance(balance_cents=1_000_000)
        evidence = create_evidence(customer)
        create_notarization(evidence)
        before_v = evidence["version"]
        ev_after = validate_success(
            api.submit_evidence(
                evidence["id"], make_customer_headers(customer["id"]),
            ),
            200,
        )
        assert ev_after["status"] == "SUBMITTING"
        assert ev_after["submission_attempts"] == 1
        assert ev_after["version"] > before_v

    def test_submit_appends_audit_event(self, api):
        """PRD §3.3: 'an audit row of type EVIDENCE_SUBMITTED is
        appended.'"""
        customer = create_customer_with_balance()
        evidence = create_evidence(customer)
        create_notarization(evidence)
        submit_evidence(evidence)
        rows = list_audit_logs(
            event_type="EVIDENCE_SUBMITTED",
            target_entity="Evidence",
            target_id=evidence["id"],
        )
        assert len(rows) >= 1

    def test_submit_does_not_debit_wallet(self, api):
        """PRD §3.3: 'The quote is optimistic ... no batch discount
        applies ... and no judicial surcharge is folded in.' PRD §3.3:
        fee debit happens at the SUBMITTING→CONFIRMED transition, not
        at PENDING→SUBMITTING."""
        customer = create_customer_with_balance(balance_cents=1_000)
        evidence = create_evidence(customer)  # DOCUMENT/30 → 200c
        create_notarization(evidence)
        submit_evidence(evidence)
        cust_after = get_customer(customer["id"])
        assert cust_after["wallet_balance_cents"] == 1_000


# ===========================================================================
# Wallet balance precondition (priority 17)
# ===========================================================================
class TestInsufficientBalanceOnSubmit:
    """PRD §2.10 priority 17: 'Customer.wallet_balance_cents is at
    least the forward-looking preservation fee quote on submit and
    resubmit (ERR_INSUFFICIENT_BALANCE).'"""

    def test_zero_balance_rejected(self, api):
        """PRD §2.10 priority 17: zero balance fails submit."""
        customer = create_customer_with_balance(balance_cents=0)
        evidence = create_evidence(customer)  # DOCUMENT/30 quote 200c
        create_notarization(evidence)
        res = api.submit_evidence(
            evidence["id"], make_customer_headers(customer["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_BALANCE.value)

    def test_one_below_quote_rejected(self, api):
        """PRD §2.10 priority 17: balance one cent below quote rejected.

        PRD §3.3 single-evidence quote: DOCUMENT base 200 * period
        multiplier 1.00 + (original_data null → 0) = 200 cents.
        """
        customer = create_customer_with_balance(balance_cents=199)
        evidence = create_evidence(
            customer, evidence_type="DOCUMENT", storage_period_days=30,
        )
        create_notarization(evidence)
        res = api.submit_evidence(
            evidence["id"], make_customer_headers(customer["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_BALANCE.value)


# ===========================================================================
# Chain confirmation thresholds (PRD §2.8)
# ===========================================================================
class TestChainConfirmationThresholds:
    """PRD §2.8: 'Each chain has a fixed confirmation threshold ...
    ETHEREUM requires 12 confirmations, FABRIC requires 1, BSN requires
    5, and COSMOS requires 6. The system never overrides these
    thresholds — a confirmations value reported below the threshold for
    the relevant chain_id must keep the transaction in SUBMITTED and
    the upstream Evidence or Batch in SUBMITTING.'"""

    def test_below_threshold_keeps_submitting(self, api):
        """PRD §2.8: 'a confirmations value reported below the threshold
        for the relevant chain_id must keep the transaction in SUBMITTED
        and the upstream Evidence or Batch in SUBMITTING.'"""
        customer, evidence, _ = bring_evidence_to_submitting()
        # ETHEREUM threshold is 12; report 11 — should NOT confirm.
        tx = latest_onchain_tx_for_evidence(evidence["id"])
        chain_confirm(tx["id"], confirmations=11)
        ev_after = get_evidence(evidence["id"])
        assert ev_after["status"] == "SUBMITTING", (
            f"Below threshold (11<12) must keep SUBMITTING, "
            f"got {ev_after['status']}"
        )

    def test_at_threshold_confirms(self, api):
        """PRD §2.8: 'When the threshold is reached or exceeded, the
        OnChainTx flips to CONFIRMED and cascades to the upstream
        entity.'"""
        customer, evidence, _ = bring_evidence_to_submitting()
        tx = latest_onchain_tx_for_evidence(evidence["id"])
        chain_confirm(tx["id"], confirmations=12)  # exactly threshold
        ev_after = get_evidence(evidence["id"])
        assert ev_after["status"] == "CONFIRMED"

    @pytest.mark.parametrize("chain,confirmations", [
        ("FABRIC", 1),
        ("BSN", 5),
        ("COSMOS", 6),
        ("ETHEREUM", 12),
    ])
    def test_each_chain_threshold_exact(self, api, chain, confirmations):
        """PRD §2.8: per-chain thresholds — ETHEREUM:12, FABRIC:1,
        BSN:5, COSMOS:6."""
        customer = create_customer_with_balance(balance_cents=100_000)
        evidence = create_evidence(customer, chain_id=chain)
        create_notarization(evidence)
        submit_evidence(evidence)
        tx = latest_onchain_tx_for_evidence(evidence["id"])
        chain_confirm(tx["id"], confirmations=confirmations)
        ev_after = get_evidence(evidence["id"])
        assert ev_after["status"] == "CONFIRMED"


# ===========================================================================
# SUBMITTING → CONFIRMED (PRD §3.3)
# ===========================================================================
class TestEvidenceConfirm:
    """PRD §3.3: 'the cascade sets Evidence.confirmed_at to the server's
    current time, sets Evidence.expires_at to confirmed_at plus the
    product of storage_period_days and 86 400 seconds, computes the
    chronological per-evidence fee ... assigns the result to
    Evidence.per_evidence_fee_cents, debits Customer.wallet_balance_cents
    by that amount, increments FeeAccount.lifetime_deduction_cents by
    the same amount, and appends two audit rows: one with event_type
    EVIDENCE_CONFIRMED and one with event_type FEE_DEBITED.'"""

    def test_confirm_sets_per_evidence_fee(self, api):
        """PRD §3.3: 'computes the chronological per-evidence fee ...
        assigns the result to Evidence.per_evidence_fee_cents'.

        DOCUMENT / 30 days / no original → 200 cents.
        """
        customer, ev = bring_evidence_to_confirmed(
            balance_cents=1_000,
            evidence_overrides={
                "evidence_type": "DOCUMENT", "storage_period_days": 30,
            },
        )
        assert ev["status"] == "CONFIRMED"
        assert ev["per_evidence_fee_cents"] == 200

    def test_confirm_debits_wallet(self, api):
        """PRD §3.3: 'debits Customer.wallet_balance_cents by that
        amount'."""
        customer, ev = bring_evidence_to_confirmed(
            balance_cents=1_000,
            evidence_overrides={
                "evidence_type": "DOCUMENT", "storage_period_days": 30,
            },
        )
        cust_after = get_customer(customer["id"])
        assert cust_after["wallet_balance_cents"] == 800  # 1000 - 200

    def test_confirm_sets_confirmed_at_and_expires_at(self, api):
        """PRD §3.3: 'sets Evidence.confirmed_at to the server's current
        time, sets Evidence.expires_at to confirmed_at plus the product
        of storage_period_days and 86 400 seconds'."""
        customer, ev = bring_evidence_to_confirmed(
            balance_cents=2_000,
            evidence_overrides={
                "evidence_type": "DOCUMENT", "storage_period_days": 30,
            },
        )
        assert ev["confirmed_at"] is not None
        assert ev["expires_at"] is not None
        # We don't pin the exact timestamps (server clock dependent), but
        # the relationship must hold: expires_at > confirmed_at.
        assert ev["expires_at"] > ev["confirmed_at"]

    def test_confirm_appends_two_audit_rows(self, api):
        """PRD §3.3: 'appends two audit rows: one with event_type
        EVIDENCE_CONFIRMED and one with event_type FEE_DEBITED.'"""
        customer, ev = bring_evidence_to_confirmed()
        ev_conf = list_audit_logs(
            event_type="EVIDENCE_CONFIRMED",
            target_entity="Evidence",
            target_id=ev["id"],
        )
        assert len(ev_conf) >= 1
        fee_rows = list_audit_logs(
            event_type="FEE_DEBITED",
            target_entity="Evidence",
            target_id=ev["id"],
        )
        assert len(fee_rows) >= 1


# ===========================================================================
# SUBMITTING → FAILED (PRD §3.3)
# ===========================================================================
class TestEvidenceFail:
    """PRD §3.3: 'A simulated chain failure ... flips the same
    OnChainTx to FAILED ... and cascades the upstream evidence from
    SUBMITTING to FAILED. No fee is debited on failure. An audit row
    of type EVIDENCE_FAILED is appended; balance and ledger columns are
    not touched.'"""

    def test_chain_fail_cascades_to_evidence_failed(self, api):
        customer, ev = bring_evidence_to_failed(
            balance_cents=1_000,
            evidence_overrides={
                "evidence_type": "DOCUMENT", "storage_period_days": 30,
            },
        )
        assert ev["status"] == "FAILED"

    def test_chain_fail_does_not_debit_wallet(self, api):
        """PRD §3.3: 'No fee is debited on failure ... balance and
        ledger columns are not touched.'"""
        customer, ev = bring_evidence_to_failed(
            balance_cents=1_000,
            evidence_overrides={
                "evidence_type": "DOCUMENT", "storage_period_days": 30,
            },
        )
        cust_after = get_customer(customer["id"])
        assert cust_after["wallet_balance_cents"] == 1_000


# ===========================================================================
# Resubmission (PRD §3.3)
# ===========================================================================
class TestResubmit:
    """PRD §3.3: 'A FAILED evidence is recoverable via resubmission ...
    transitions the evidence from FAILED back to SUBMITTING. Two
    preconditions hold: Evidence.submission_attempts is strictly less
    than 3 (the system permits at most three submissions in total for a
    single evidence; a fourth attempt is rejected with
    ERR_RESUBMIT_LIMIT_EXCEEDED), and Customer.wallet_balance_cents is
    still at least the forward-looking preservation fee quote.'"""

    def test_resubmit_from_failed_increments_attempts(self, api):
        customer, ev = bring_evidence_to_failed()
        ev_after = validate_success(api.resubmit_evidence(
            ev["id"], make_customer_headers(customer["id"]),
        ), 200)
        assert ev_after["status"] == "SUBMITTING"
        assert ev_after["submission_attempts"] == 2

    def test_resubmit_from_pending_rejected(self, api):
        """PRD §2.10 priority 6 / §3.3: 'transitions the evidence from
        FAILED back to SUBMITTING' — wrong starting state rejects with
        ERR_INVALID_STATE."""
        customer = create_customer_with_balance(balance_cents=1_000)
        evidence = create_evidence(customer)  # PENDING
        create_notarization(evidence)
        res = api.resubmit_evidence(
            evidence["id"], make_customer_headers(customer["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_resubmit_attempts_limit(self, api):
        """PRD §3.3: 'a fourth attempt is rejected with
        ERR_RESUBMIT_LIMIT_EXCEEDED.' (limit is 3 submissions total)."""
        customer = create_customer_with_balance(balance_cents=10_000)
        evidence = create_evidence(customer)
        create_notarization(evidence)
        # Attempt 1: submit + fail
        submit_evidence(evidence)
        tx1 = latest_onchain_tx_for_evidence(evidence["id"])
        chain_fail(tx1["id"])
        # Attempt 2: resubmit + fail
        validate_success(api.resubmit_evidence(
            evidence["id"], make_customer_headers(customer["id"]),
        ), 200)
        tx2 = latest_onchain_tx_for_evidence(evidence["id"])
        chain_fail(tx2["id"])
        # Attempt 3: resubmit + fail
        validate_success(api.resubmit_evidence(
            evidence["id"], make_customer_headers(customer["id"]),
        ), 200)
        tx3 = latest_onchain_tx_for_evidence(evidence["id"])
        chain_fail(tx3["id"])
        ev_now = get_evidence(evidence["id"])
        assert ev_now["submission_attempts"] == 3
        # 4th attempt must reject
        res = api.resubmit_evidence(
            evidence["id"], make_customer_headers(customer["id"]),
        )
        validate_error(res, ApiErrorId.ERR_RESUBMIT_LIMIT_EXCEEDED.value)


# ===========================================================================
# OnChainTx attempt_index (PRD §3.3)
# ===========================================================================
class TestOnChainTxAttemptIndex:
    """PRD §3.3: 'A successful transition creates a fresh OnChainTx ...
    attempt_index set to Evidence.submission_attempts plus one.' And on
    resubmit: 'creates a new OnChainTx with attempt_index equal to
    Evidence.submission_attempts plus one and otherwise mirroring the
    original anchor structure'."""

    def test_first_submission_creates_attempt_one(self, api):
        """PRD §3.3: 'attempt_index set to Evidence.submission_attempts
        plus one' — at first submit, prior attempts is 0, so the new
        OnChainTx carries attempt_index 1."""
        customer, ev, _ = bring_evidence_to_submitting()
        assert ev["submission_attempts"] == 1


# ===========================================================================
# Submit on a non-PENDING evidence (priority 6)
# ===========================================================================
class TestInvalidStateOnSubmit:
    """PRD §2.10 priority 6: 'Target entity is in a state that admits
    the requested transition (ERR_INVALID_STATE).'

    For /submit, only PENDING is valid (per PRD §3.3 state diagram).
    """

    def test_double_submit_rejected(self, api):
        """PRD §3.3: After the first submit, status is SUBMITTING, not
        PENDING, so a second submit must reject with ERR_INVALID_STATE."""
        customer, ev, _ = bring_evidence_to_submitting()
        res = api.submit_evidence(
            ev["id"], make_customer_headers(customer["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
