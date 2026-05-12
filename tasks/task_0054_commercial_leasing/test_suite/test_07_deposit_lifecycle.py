"""Deposit lifecycle: top-up, freeze on move-out, propose/approve/reject
deductions, ledger aggregation.

PRD §3.6, §2.9.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    approve_deductions,
    assert_deposit,
    assert_tenant_ledger_invariant,
    confirm_restoration,
    create_approved_tenant,
    finalize_move_out,
    get_deposit,
    get_tenant,
    make_deduction_item,
    make_tenant_headers,
    move_out_request,
    propose_deductions,
    propose_deductions_payload,
    record_inspection,
    reject_deductions,
    setup_active_lease,
    setup_deduction_approved,
    setup_finalized_lease,
    setup_restoration_confirmed,
    setup_signed_lease,
    setup_terminating_lease,
    top_up_deposit,
    top_up_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# Deposit top-up
# ===========================================================================
class TestDepositTopUp:
    """PRD §3.6: 'A tenant tops up their deposit by supplying an
    amount_cents integer.'
    """

    def test_top_up_increments_collected_cents(self, api):
        """PRD §3.6: 'On success, collected_cents is incremented by
        amount_cents.'"""
        ctx = setup_signed_lease(
            deposit_months=1, base_monthly_rent_cents=100000,
        )
        deposit = ctx["deposit"]
        tenant = ctx["tenant"]
        res = api.top_up_deposit(
            deposit["id"], top_up_payload(amount_cents=40000),
            make_tenant_headers(tenant["id"]),
        )
        data = validate_success(res)
        assert data["collected_cents"] == 40000

    def test_top_up_overpay_rejected(self, api):
        """PRD §3.6: 'The top-up is rejected with ERR_DEPOSIT_OVERPAY
        if collected_cents + amount_cents would exceed required_cents
        (the boundary is inclusive — equality is acceptable, strictly
        greater is rejected).'"""
        ctx = setup_signed_lease(
            deposit_months=1, base_monthly_rent_cents=100000,
        )  # required_cents = 100000
        tenant = ctx["tenant"]
        deposit = ctx["deposit"]
        res = api.top_up_deposit(
            deposit["id"], top_up_payload(amount_cents=100001),
            make_tenant_headers(tenant["id"]),
        )
        validate_error(res, ApiErrorId.ERR_DEPOSIT_OVERPAY.value)

    def test_top_up_exact_equality_accepted(self, api):
        """PRD §3.6: 'the boundary is inclusive — equality is
        acceptable.'"""
        ctx = setup_signed_lease(
            deposit_months=1, base_monthly_rent_cents=100000,
        )
        tenant = ctx["tenant"]
        deposit = ctx["deposit"]
        res = api.top_up_deposit(
            deposit["id"], top_up_payload(amount_cents=100000),
            make_tenant_headers(tenant["id"]),
        )
        data = validate_success(res)
        assert data["collected_cents"] == 100000


# ===========================================================================
# Tenant deposit ledger aggregation (PRD §2.9)
# ===========================================================================
class TestTenantDepositLedger:
    """PRD §2.9: 'After every collection, refund, or retention against
    any single Deposit for the tenant, the live held-by-landlord
    balance for the tenant — total_deposit_paid_cents −
    total_deposit_refunded_cents − total_deposit_retained_cents — must
    equal the sum across that tenant's deposit rows of collected_cents
    − refunded_cents − retained_cents.'
    """

    def test_tenant_paid_total_reflects_top_up(self, api):
        """PRD §2.9: 'total_deposit_paid_cents (the sum of
        collected_cents across every Deposit whose owning Lease lists
        this tenant)'."""
        ctx = setup_signed_lease(
            deposit_months=1, base_monthly_rent_cents=100000,
        )
        tenant = ctx["tenant"]
        deposit = ctx["deposit"]
        top_up_deposit(
            deposit["id"], tenant_id=tenant["id"], amount_cents=100000,
        )
        refreshed = get_tenant(tenant["id"])
        assert refreshed["total_deposit_paid_cents"] == 100000
        assert refreshed["total_deposit_refunded_cents"] == 0
        assert refreshed["total_deposit_retained_cents"] == 0
        assert_tenant_ledger_invariant(refreshed)


# ===========================================================================
# Move-out freeze
# ===========================================================================
class TestDepositFreezeOnMoveOut:
    """PRD §3.8: 'On success, the lease's status moves from ACTIVE to
    TERMINATING ... and the deposit's frozen_status moves to FROZEN.'
    """

    def test_deposit_freezes_when_move_out_submitted(self, api):
        """PRD §3.8: 'the deposit's frozen_status moves to FROZEN.'"""
        ctx = setup_terminating_lease()
        assert ctx["deposit"]["frozen_status"] == "FROZEN"

    def test_move_out_rejection_unfreezes_deposit(self, api):
        """PRD §3.8: 'rejecting it moves its status to REJECTED, reverts
        the owning lease's status from TERMINATING back to ACTIVE, and
        moves the deposit's frozen_status back to UNFROZEN.'"""
        ctx = setup_terminating_lease()
        from test_helpers import reject_move_out, get_lease
        reject_move_out(ctx["move_out_request"]["id"])
        dep = get_deposit(ctx["deposit"]["id"])
        assert dep["frozen_status"] == "UNFROZEN"
        lease = get_lease(ctx["lease"]["id"])
        assert lease["status"] == "ACTIVE"


# ===========================================================================
# Propose deductions
# ===========================================================================
class TestProposeDeductions:
    """PRD §3.8: 'a PropertyManager proposes deductions against the
    deposit by submitting a deduction_items array, where each element
    carries a kind (OVERDUE_RENT, DAMAGE, or CLEANING), an
    amount_cents integer, and an optional note string.'
    """

    def test_propose_moves_status_to_pending_approval(self, api):
        """PRD §3.8: 'the deposit's adjustment_status moves to
        DEDUCTION_PENDING_APPROVAL, the supplied items are stored in
        pending_deduction_items, and the move-out request cascades to
        DEDUCTION_PROPOSED.'"""
        ctx = setup_restoration_confirmed()
        items = [make_deduction_item(kind="CLEANING", amount_cents=1000,
                                     note="touch-up")]
        res = api.propose_deductions(
            ctx["deposit"]["id"],
            propose_deductions_payload(deduction_items=items),
            ctx_pm := __import__("test_helpers").PM,
        )
        data = validate_success(res)
        assert data["adjustment_status"] == "DEDUCTION_PENDING_APPROVAL"
        # Pending items stored.
        pend = data["pending_deduction_items"]
        assert len(pend) == 1 and pend[0]["amount_cents"] == 1000
        # MoveOutRequest cascades to DEDUCTION_PROPOSED.
        from test_helpers import get_move_out_request
        mor = get_move_out_request(ctx["move_out_request"]["id"])
        assert mor["status"] == "DEDUCTION_PROPOSED"

    def test_propose_exceeds_collected_rejected(self, api):
        """PRD §3.8: 'with ERR_DEDUCTION_EXCEEDS_DEPOSIT if the sum of
        amount_cents across the items strictly exceeds the deposit's
        collected_cents — equality is acceptable.'"""
        ctx = setup_restoration_confirmed(
            base_monthly_rent_cents=100000, deposit_months=1,
        )
        # collected_cents = 100000; items sum to 100001 → reject.
        items = [
            make_deduction_item(kind="DAMAGE", amount_cents=100001),
        ]
        res = api.propose_deductions(
            ctx["deposit"]["id"],
            propose_deductions_payload(deduction_items=items),
            __import__("test_helpers").PM,
        )
        validate_error(res, ApiErrorId.ERR_DEDUCTION_EXCEEDS_DEPOSIT.value)

    def test_propose_equals_collected_accepted(self, api):
        """PRD §3.8: '... equality is acceptable.'"""
        ctx = setup_restoration_confirmed(
            base_monthly_rent_cents=100000, deposit_months=1,
        )
        items = [
            make_deduction_item(kind="DAMAGE", amount_cents=100000),
        ]
        res = api.propose_deductions(
            ctx["deposit"]["id"],
            propose_deductions_payload(deduction_items=items),
            __import__("test_helpers").PM,
        )
        data = validate_success(res)
        assert data["adjustment_status"] == "DEDUCTION_PENDING_APPROVAL"


# ===========================================================================
# Approve deductions
# ===========================================================================
class TestApproveDeductions:
    """PRD §3.8: 'Approving ... sets the deposit's retained_cents to
    the sum of pending_deduction_items[].amount_cents, sets its
    refunded_cents to collected_cents − retained_cents, recomputes the
    tenant's total_deposit_retained_cents and
    total_deposit_refunded_cents, moves the deposit's adjustment_status
    to SETTLED, cascades the move-out request to DEDUCTION_APPROVED,
    and records two audit events — one with action DEPOSIT_DEDUCTED and
    one with action DEPOSIT_REFUNDED.'
    """

    def test_approve_settles_deposit_and_computes_refund(self, api):
        """PRD §3.8: 'sets the deposit's retained_cents to the sum of
        pending_deduction_items[].amount_cents, sets its refunded_cents
        to collected_cents − retained_cents'."""
        ctx = setup_deduction_approved(
            deduction_items=[make_deduction_item(
                kind="DAMAGE", amount_cents=20000,
            )],
            base_monthly_rent_cents=100000, deposit_months=1,
        )
        dep = ctx["deposit"]
        assert dep["adjustment_status"] == "SETTLED"
        assert dep["retained_cents"] == 20000
        assert dep["refunded_cents"] == 100000 - 20000

    def test_approve_emits_deposit_deducted_and_refunded_audit_events(
        self, api,
    ):
        """PRD §3.8: 'records two audit events — one with action
        DEPOSIT_DEDUCTED and one with action DEPOSIT_REFUNDED.'"""
        ctx = setup_deduction_approved(
            deduction_items=[make_deduction_item(
                kind="DAMAGE", amount_cents=5000,
            )],
        )
        from test_helpers import list_audit_events
        deducted = list_audit_events(
            subject_kind="DEPOSIT", subject_id=ctx["deposit"]["id"],
            action="DEPOSIT_DEDUCTED",
        )
        refunded = list_audit_events(
            subject_kind="DEPOSIT", subject_id=ctx["deposit"]["id"],
            action="DEPOSIT_REFUNDED",
        )
        assert len(deducted) >= 1
        assert len(refunded) >= 1


class TestRejectDeductions:
    """PRD §3.8: 'Rejecting the deductions instead moves the deposit's
    adjustment_status back to AT_REST and clears
    pending_deduction_items, leaving the move-out request in its
    current state for the property manager to revise.'
    """

    def test_reject_returns_to_at_rest_and_clears_pending(self, api):
        """PRD §3.8: 'moves the deposit's adjustment_status back to
        AT_REST and clears pending_deduction_items'."""
        ctx = setup_restoration_confirmed()
        propose_deductions(
            ctx["deposit"]["id"],
            [make_deduction_item(amount_cents=1000)],
        )
        dep = reject_deductions(ctx["deposit"]["id"])
        assert dep["adjustment_status"] == "AT_REST"
        assert dep["pending_deduction_items"] == []
