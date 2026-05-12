"""Move-out workflow: request submission with 30-day lead time,
inspection, restoration, finalization cascade.

PRD §3.8.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    approve_deductions,
    assert_audit_event,
    assert_move_out_request,
    confirm_restoration,
    confirm_restoration_payload,
    create_property_fee_bill,
    finalize_move_out,
    get_lease,
    get_move_out_request,
    get_rent_schedule,
    get_unit,
    list_audit_events,
    make_deduction_item,
    make_tenant_headers,
    move_out_request,
    move_out_request_payload,
    propose_deductions,
    record_inspection,
    record_inspection_payload,
    reject_move_out,
    setup_active_lease,
    setup_deduction_approved,
    setup_finalized_lease,
    setup_restoration_confirmed,
    setup_terminating_lease,
    validate_error,
    validate_success,
    FO, PM,
)


# ===========================================================================
# Move-out lead time
# ===========================================================================
class TestMoveOutLeadTime:
    """PRD §3.8: 'The move-out request is rejected with
    ERR_MOVE_OUT_LEAD_TIME unless target_move_out_date is at least 30
    days after the current server date — the lead-time check is strict
    at the day granularity, so 29 days from today is rejected while 30
    days from today is accepted.'
    """

    def test_29_days_ahead_rejected(self, api):
        """PRD §3.8: 'the lead-time check is strict at the day
        granularity, so 29 days from today is rejected while 30 days
        from today is accepted.'"""
        ctx = setup_active_lease(
            start_date="2026-01-01T00:00:00.000Z",
            end_date="2026-12-01T00:00:00.000Z",
            clock_to="2026-01-01T00:00:00.000Z",
        )
        # Move clock to 2026-02-01; 29 days ahead is 2026-03-02.
        advance_clock("2026-02-01T00:00:00.000Z")
        res = api.move_out_request(
            ctx["lease"]["id"],
            move_out_request_payload(
                target_move_out_date="2026-03-02T00:00:00.000Z",
            ),
            make_tenant_headers(ctx["tenant"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_MOVE_OUT_LEAD_TIME.value)

    def test_30_days_ahead_accepted(self, api):
        """PRD §3.8: '... 30 days from today is accepted.'"""
        ctx = setup_active_lease(
            start_date="2026-01-01T00:00:00.000Z",
            end_date="2026-12-01T00:00:00.000Z",
            clock_to="2026-01-01T00:00:00.000Z",
        )
        advance_clock("2026-02-01T00:00:00.000Z")
        res = api.move_out_request(
            ctx["lease"]["id"],
            move_out_request_payload(
                target_move_out_date="2026-03-03T00:00:00.000Z",
            ),
            make_tenant_headers(ctx["tenant"]["id"]),
        )
        data = validate_success(res, expected_status=201)
        assert_move_out_request(data)
        assert data["status"] == "SUBMITTED"


# ===========================================================================
# Inspection and restoration
# ===========================================================================
class TestInspectionAndRestoration:
    """PRD §3.8: 'A property manager records the unit inspection on the
    request, supplying inspection_findings ... and moves its status to
    INSPECTION_DONE. The property manager then confirms restoration by
    submitting a restoration_done boolean; if restoration_done is false
    the request is rejected with ERR_RESTORATION_INCOMPLETE.'
    """

    def test_record_inspection_moves_to_inspection_done(self, api):
        """PRD §3.8: 'moves its status to INSPECTION_DONE.'"""
        ctx = setup_terminating_lease()
        res = api.record_inspection(
            ctx["move_out_request"]["id"],
            record_inspection_payload(inspection_findings=[]),
            PM,
        )
        data = validate_success(res)
        assert data["status"] == "INSPECTION_DONE"

    def test_confirm_restoration_true_moves_to_restoration_confirmed(
        self, api,
    ):
        """PRD §3.8: 'if true the request's status moves to
        RESTORATION_CONFIRMED.'"""
        ctx = setup_terminating_lease()
        record_inspection(ctx["move_out_request"]["id"], [])
        res = api.confirm_restoration(
            ctx["move_out_request"]["id"],
            confirm_restoration_payload(restoration_done=True),
            PM,
        )
        data = validate_success(res)
        assert data["status"] == "RESTORATION_CONFIRMED"

    def test_confirm_restoration_false_rejected(self, api):
        """PRD §3.8: 'if restoration_done is false the request is
        rejected with ERR_RESTORATION_INCOMPLETE.'"""
        ctx = setup_terminating_lease()
        record_inspection(ctx["move_out_request"]["id"], [])
        res = api.confirm_restoration(
            ctx["move_out_request"]["id"],
            confirm_restoration_payload(restoration_done=False),
            PM,
        )
        validate_error(res, ApiErrorId.ERR_RESTORATION_INCOMPLETE.value)


# ===========================================================================
# Move-out rejection
# ===========================================================================
class TestMoveOutRejection:
    """PRD §3.8: 'The property manager may, at any point while the
    request is still SUBMITTED, reject the request outright; rejecting
    it moves its status to REJECTED, reverts the owning lease's status
    from TERMINATING back to ACTIVE, and moves the deposit's
    frozen_status back to UNFROZEN.'
    """

    def test_reject_reverts_lease_to_active(self, api):
        """PRD §3.8: 'rejecting it ... reverts the owning lease's
        status from TERMINATING back to ACTIVE.'"""
        ctx = setup_terminating_lease()
        reject_move_out(ctx["move_out_request"]["id"])
        lease = get_lease(ctx["lease"]["id"])
        assert lease["status"] == "ACTIVE"


# ===========================================================================
# Finalization
# ===========================================================================
class TestFinalization:
    """PRD §3.8: 'The lease is finalised by a finance officer once the
    move-out chain has reached DEDUCTION_APPROVED. Finalisation is
    rejected with ERR_INVALID_STATE unless the owning move-out
    request's status is DEDUCTION_APPROVED, with ERR_DEPOSIT_NOT_SETTLED
    unless the deposit's adjustment_status is SETTLED, and with
    ERR_OUTSTANDING_FEE_BILL if any FeeBill for this lease has status
    ISSUED or DISPUTED.'
    """

    def test_finalize_moves_lease_to_terminated(self, api):
        """PRD §3.8: 'On success, the lease's status moves from
        TERMINATING to TERMINATED.'"""
        ctx = setup_finalized_lease()
        assert ctx["lease"]["status"] == "TERMINATED"

    def test_finalize_sets_terminated_on_to_target_date(self, api):
        """PRD §3.8: 'its terminated_on is set to the move-out request's
        target_move_out_date.'"""
        ctx = setup_finalized_lease()
        assert ctx["lease"]["terminated_on"] == (
            ctx["move_out_request"]["target_move_out_date"]
        )

    def test_finalize_cascades_move_out_to_settled(self, api):
        """PRD §3.8: 'the move-out request cascades to SETTLED'."""
        ctx = setup_finalized_lease()
        assert ctx["move_out_request"]["status"] == "SETTLED"

    def test_finalize_cascades_unit_to_vacant(self, api):
        """PRD §3.8: 'the unit cascades back to VACANT (the
        deposit-settled precondition on that cascade is satisfied here
        by construction)'."""
        ctx = setup_finalized_lease()
        assert ctx["unit"]["status"] == "VACANT"

    def test_finalize_emits_contract_terminated_audit(self, api):
        """PRD §3.8: 'an AuditEvent with action CONTRACT_TERMINATED is
        recorded.'"""
        ctx = setup_finalized_lease()
        rows = list_audit_events(
            subject_kind="LEASE", subject_id=ctx["lease"]["id"],
            action="CONTRACT_TERMINATED",
        )
        assert len(rows) >= 1
        for r in rows:
            assert_audit_event(r)

    def test_finalize_voids_future_rent_schedule_rows(self, api):
        """PRD §3.8: 'every RentScheduleItem whose period_start is
        strictly after terminated_on is moved to VOIDED'."""
        # Lease 2026-01-01..2026-12-01, target move-out 2026-04-01.
        ctx = setup_finalized_lease(
            start_date="2026-01-01T00:00:00.000Z",
            end_date="2026-12-01T00:00:00.000Z",
            activate_clock="2026-01-01T00:00:00.000Z",
            move_out_clock="2026-02-01T00:00:00.000Z",
            target_move_out_date="2026-04-01T00:00:00.000Z",
            base_monthly_rent_cents=100000,
        )
        rows = get_rent_schedule(ctx["lease"]["id"])
        terminated_on = ctx["lease"]["terminated_on"]
        for r in rows:
            if r["period_start"] > terminated_on:
                assert r["status"] == "VOIDED", (
                    f"row period_start={r['period_start']} after "
                    f"terminated_on={terminated_on} must be VOIDED, "
                    f"got status={r['status']}"
                )

    def test_finalize_with_outstanding_issued_fee_bill_rejected(self, api):
        """PRD §3.8: 'with ERR_OUTSTANDING_FEE_BILL if any FeeBill for
        this lease has status ISSUED or DISPUTED — every fee bill must
        be either PAID or VOIDED before settlement closes.'"""
        # Build through DEDUCTION_APPROVED, then add an outstanding bill,
        # and try to finalize.
        # Strategy: build a lease ACTIVE first, issue a bill (ISSUED),
        # then proceed through move-out to DEDUCTION_APPROVED.
        ctx = setup_active_lease(
            start_date="2026-01-01T00:00:00.000Z",
            end_date="2026-12-01T00:00:00.000Z",
            clock_to="2026-01-01T00:00:00.000Z",
        )
        # Issue a property-fee bill, leave it ISSUED.
        create_property_fee_bill(
            lease_id=ctx["lease"]["id"],
            period_start="2026-01-01T00:00:00.000Z",
            period_end="2026-02-01T00:00:00.000Z",
            property_fee_mode="FIXED_RATE",
            fixed_rate_cents_per_month=20000,
        )
        # Now walk to DEDUCTION_APPROVED.
        advance_clock("2026-02-01T00:00:00.000Z")
        mor = move_out_request(
            ctx["lease"]["id"], tenant_id=ctx["tenant"]["id"],
            target_move_out_date="2026-03-15T00:00:00.000Z",
        )
        record_inspection(mor["id"], [])
        confirm_restoration(mor["id"], True)
        propose_deductions(ctx["deposit"]["id"], [
            make_deduction_item(amount_cents=1000),
        ])
        approve_deductions(ctx["deposit"]["id"])
        res = api.finalize_move_out(mor["id"], FO)
        validate_error(res, ApiErrorId.ERR_OUTSTANDING_FEE_BILL.value)
