"""Lease activation, amendment cycle, and renewal.

PRD §3.5.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    amend_cancel,
    amend_confirm,
    amend_lease,
    amend_lease_payload,
    advance_clock,
    activate_lease,
    create_approved_tenant,
    create_lease,
    get_lease,
    get_deposit,
    get_rent_schedule,
    list_audit_events,
    make_stepped_entry,
    renew_lease,
    renew_lease_payload,
    setup_active_lease,
    setup_signed_lease,
    sign_lease,
    setup_building_with_unit,
    top_up_deposit,
    validate_error,
    validate_success,
    LA, FO,
)


# ===========================================================================
# Activation
# ===========================================================================
class TestLeaseActivation:
    """PRD §3.5: 'Once signed, a lease is brought live by activating it.
    Activation is rejected with ERR_DEPOSIT_INCOMPLETE unless the
    owning Deposit has collected_cents exactly equal to required_cents,
    and with ERR_LEASE_NOT_YET_STARTED unless the current server date
    is on or after the lease's start_date. On success, the lease's
    status becomes ACTIVE.'
    """

    def test_activate_signed_lease_succeeds(self, api):
        """PRD §3.5: 'On success, the lease's status becomes ACTIVE.'"""
        ctx = setup_active_lease()
        assert ctx["lease"]["status"] == "ACTIVE"

    def test_activate_without_full_deposit_rejected(self, api):
        """PRD §3.5: 'rejected with ERR_DEPOSIT_INCOMPLETE unless the
        owning Deposit has collected_cents exactly equal to
        required_cents'."""
        ctx = setup_signed_lease(
            deposit_months=1, base_monthly_rent_cents=100000,
            start_date="2026-01-01T00:00:00.000Z",
            end_date="2026-12-01T00:00:00.000Z",
        )
        # Deposit collected = 0; required = 100000.
        advance_clock("2026-01-01T00:00:00.000Z")
        res = api.activate_lease(ctx["lease"]["id"], LA)
        validate_error(res, ApiErrorId.ERR_DEPOSIT_INCOMPLETE.value)

    def test_activate_before_start_date_rejected(self, api):
        """PRD §3.5: 'with ERR_LEASE_NOT_YET_STARTED unless the current
        server date is on or after the lease's start_date.'"""
        ctx = setup_signed_lease(
            deposit_months=1, base_monthly_rent_cents=100000,
            start_date="2099-01-01T00:00:00.000Z",
            end_date="2099-12-01T00:00:00.000Z",
        )
        top_up_deposit(
            ctx["deposit"]["id"], tenant_id=ctx["tenant"]["id"],
            amount_cents=100000,
        )
        advance_clock("2026-01-01T00:00:00.000Z")
        res = api.activate_lease(ctx["lease"]["id"], LA)
        validate_error(res, ApiErrorId.ERR_LEASE_NOT_YET_STARTED.value)


# ===========================================================================
# Amendment cycle
# ===========================================================================
class TestAmendmentCycle:
    """PRD §3.5: 'An ACTIVE lease can be amended by a LeasingAgent. ...
    Initiating an amendment moves the lease's status to
    AMENDMENT_PENDING and simultaneously moves the owning
    Deposit.adjustment_status to ADJUSTMENT_PENDING.'
    """

    def test_amend_moves_to_amendment_pending(self, api):
        """PRD §3.5: 'Initiating an amendment moves the lease's status
        to AMENDMENT_PENDING and simultaneously moves the owning
        Deposit.adjustment_status to ADJUSTMENT_PENDING.'"""
        ctx = setup_active_lease()
        res = api.amend_lease(
            ctx["lease"]["id"],
            amend_lease_payload(
                effective_from="2026-06-01T00:00:00.000Z",
                new_base_monthly_rent_cents=110000,
            ),
            LA,
        )
        data = validate_success(res)
        assert data["status"] == "AMENDMENT_PENDING"
        dep = get_deposit(ctx["deposit"]["id"])
        assert dep["adjustment_status"] == "ADJUSTMENT_PENDING"

    def test_amend_confirm_returns_to_active_and_increments_count(self, api):
        """PRD §3.5: 'On success, the lease's status returns to ACTIVE,
        the amendment_count is incremented by one ...'"""
        ctx = setup_active_lease()
        amend_lease(
            ctx["lease"]["id"],
            effective_from="2026-06-01T00:00:00.000Z",
            new_base_monthly_rent_cents=120000,
        )
        res = api.amend_confirm_lease(ctx["lease"]["id"], FO)
        data = validate_success(res)
        assert data["status"] == "ACTIVE"
        assert data["amendment_count"] == 1
        assert data["base_monthly_rent_cents"] == 120000

    def test_amend_confirm_emits_contract_amended_audit(self, api):
        """PRD §3.5: 'An AuditEvent with action CONTRACT_AMENDED is
        recorded.'"""
        ctx = setup_active_lease()
        amend_lease(
            ctx["lease"]["id"],
            effective_from="2026-06-01T00:00:00.000Z",
            new_base_monthly_rent_cents=120000,
        )
        amend_confirm(ctx["lease"]["id"])
        rows = list_audit_events(
            subject_kind="LEASE", subject_id=ctx["lease"]["id"],
            action="CONTRACT_AMENDED",
        )
        assert len(rows) >= 1

    def test_amend_cancel_returns_to_active_with_no_change(self, api):
        """PRD §3.5: 'Cancellation simply restores the lease's status to
        ACTIVE and the deposit's adjustment_status to AT_REST without
        other field changes.'"""
        ctx = setup_active_lease(base_monthly_rent_cents=100000)
        amend_lease(
            ctx["lease"]["id"],
            effective_from="2026-06-01T00:00:00.000Z",
            new_base_monthly_rent_cents=110000,
        )
        res = api.amend_cancel_lease(ctx["lease"]["id"], LA)
        data = validate_success(res)
        assert data["status"] == "ACTIVE"
        assert data["base_monthly_rent_cents"] == 100000
        # amendment_count NOT incremented
        assert data["amendment_count"] == 0
        # Deposit goes back to AT_REST
        dep = get_deposit(ctx["deposit"]["id"])
        assert dep["adjustment_status"] == "AT_REST"

    def test_amend_confirm_regenerates_post_effective_rent_rows(self, api):
        """PRD §3.5: 'the rent-schedule rows whose period_start is on
        or after the amendment's effective_from are regenerated per
        §3.4'.

        PRD §3.4: 'When an amendment is confirmed, only those rows
        whose period_start is on or after the amendment's effective_from
        are regenerated; rows for earlier months are preserved
        unchanged.'
        """
        ctx = setup_active_lease(
            base_monthly_rent_cents=100000,
            start_date="2026-01-01T00:00:00.000Z",
            end_date="2026-07-01T00:00:00.000Z",
            clock_to="2026-01-01T00:00:00.000Z",
        )
        amend_lease(
            ctx["lease"]["id"],
            effective_from="2026-04-01T00:00:00.000Z",
            new_base_monthly_rent_cents=120000,
        )
        amend_confirm(ctx["lease"]["id"])
        rows = sorted(get_rent_schedule(ctx["lease"]["id"]),
                      key=lambda r: r["period_start"])
        # 6 months Jan..Jun
        assert len(rows) == 6
        # Pre-effective (Jan/Feb/Mar) preserved at 100000.
        for r in rows[:3]:
            assert r["gross_rent_cents"] == 100000
        # Post-effective (Apr/May/Jun) regenerated at 120000.
        for r in rows[3:]:
            assert r["gross_rent_cents"] == 120000


# ===========================================================================
# Renewal
# ===========================================================================
class TestRenewal:
    """PRD §3.5: 'Renewing an ACTIVE lease lets a leasing agent extend
    the lease's end_date and optionally update its base rent.'
    """

    def test_renew_extends_end_date(self, api):
        """PRD §3.5: 'On success, the lease's end_date is updated.'"""
        ctx = setup_active_lease(
            start_date="2026-01-01T00:00:00.000Z",
            end_date="2026-12-01T00:00:00.000Z",
            clock_to="2026-11-01T00:00:00.000Z",  # inside renewal window
        )
        res = api.renew_lease(
            ctx["lease"]["id"],
            renew_lease_payload(new_end_date="2027-06-01T00:00:00.000Z"),
            LA,
        )
        data = validate_success(res)
        assert data["end_date"] == "2027-06-01T00:00:00.000Z"

    def test_renew_before_window_open_rejected(self, api):
        """PRD §3.5: 'with ERR_RENEWAL_WINDOW_NOT_OPEN if the current
        server date is earlier than the lease's existing end_date minus
        60 days — that is, the renewal window opens exactly 60 days
        before the lease's nominal end.'"""
        ctx = setup_active_lease(
            start_date="2026-01-01T00:00:00.000Z",
            end_date="2026-12-01T00:00:00.000Z",
            clock_to="2026-01-01T00:00:00.000Z",  # far before window
        )
        res = api.renew_lease(
            ctx["lease"]["id"],
            renew_lease_payload(new_end_date="2027-06-01T00:00:00.000Z"),
            LA,
        )
        validate_error(res, ApiErrorId.ERR_RENEWAL_WINDOW_NOT_OPEN.value)

    def test_renew_with_earlier_end_date_rejected(self, api):
        """PRD §3.5: 'Renewal is rejected with ERR_INVALID_DATE_RANGE
        unless new_end_date is strictly after the current end_date.'"""
        ctx = setup_active_lease(
            start_date="2026-01-01T00:00:00.000Z",
            end_date="2026-12-01T00:00:00.000Z",
            clock_to="2026-11-01T00:00:00.000Z",
        )
        res = api.renew_lease(
            ctx["lease"]["id"],
            renew_lease_payload(new_end_date="2026-11-15T00:00:00.000Z"),
            LA,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_DATE_RANGE.value)

    def test_renew_emits_contract_renewed_audit(self, api):
        """PRD §3.5: 'An AuditEvent with action CONTRACT_RENEWED is
        recorded.'"""
        ctx = setup_active_lease(
            start_date="2026-01-01T00:00:00.000Z",
            end_date="2026-12-01T00:00:00.000Z",
            clock_to="2026-11-01T00:00:00.000Z",
        )
        renew_lease(
            ctx["lease"]["id"], new_end_date="2027-06-01T00:00:00.000Z",
        )
        rows = list_audit_events(
            subject_kind="LEASE", subject_id=ctx["lease"]["id"],
            action="CONTRACT_RENEWED",
        )
        assert len(rows) >= 1
