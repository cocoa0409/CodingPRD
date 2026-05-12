"""Property fees and energy fees: calculation, capping, lifecycle, disputes.

PRD §3.7.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    assert_audit_event,
    assert_fee_bill,
    create_energy_fee_bill_payload,
    create_lease,
    create_property_fee_bill_payload,
    create_property_fee_bill,
    create_energy_fee_bill,
    dispute_fee_bill,
    dispute_fee_bill_payload,
    list_audit_events,
    make_tenant_headers,
    pay_fee_bill,
    resolve_dispute,
    resolve_dispute_payload,
    setup_active_lease,
    setup_signed_lease,
    setup_two_active_leases_for_energy_allocation,
    sign_lease,
    void_fee_bill,
    validate_error,
    validate_success,
    FO, LA,
)


# ===========================================================================
# PROPERTY_FEE in BY_AREA mode
# ===========================================================================
class TestPropertyFeeByArea:
    """PRD §3.7: 'In BY_AREA mode the request must include
    rate_per_sqm_per_month_cents, and the bill amount before capping is
    the round-half-up of unit.area_sqm × rate_per_sqm_per_month_cents ×
    months_in_period.'
    """

    def test_by_area_uncapped_amount(self, api):
        """PRD §3.7: 'the bill amount before capping is the
        round-half-up of unit.area_sqm × rate_per_sqm_per_month_cents
        × months_in_period.'"""
        ctx = setup_active_lease()
        # area_sqm default = 100; rate = 3000 cents/sqm/month; 1 month.
        # raw = 100 * 3000 * 1 = 300000; cap = 5000 * 100 * 1 = 500000.
        # → 300000 wins.
        res = api.create_fee_bill(
            create_property_fee_bill_payload(
                lease_id=ctx["lease"]["id"],
                period_start="2026-01-01T00:00:00.000Z",
                period_end="2026-02-01T00:00:00.000Z",
                property_fee_mode="BY_AREA",
                rate_per_sqm_per_month_cents=3000,
            ),
            FO,
        )
        data = validate_success(res, expected_status=201)
        assert_fee_bill(data)
        assert data["amount_cents"] == 300000

    def test_by_area_cap_applies_at_high_rate(self, api):
        """PRD §3.7: 'the computed amount is then capped at the
        round-half-up of 5000 cents (50.00 currency units) per square
        metre per month, multiplied by the unit's area_sqm and by
        months_in_period; the bill's final amount_cents is the minimum
        of the computed amount and that cap.'"""
        ctx = setup_active_lease()
        # area_sqm = 100; rate = 6000 → raw 600000; cap = 500000.
        res = api.create_fee_bill(
            create_property_fee_bill_payload(
                lease_id=ctx["lease"]["id"],
                period_start="2026-01-01T00:00:00.000Z",
                period_end="2026-02-01T00:00:00.000Z",
                property_fee_mode="BY_AREA",
                rate_per_sqm_per_month_cents=6000,
            ),
            FO,
        )
        data = validate_success(res, expected_status=201)
        assert data["amount_cents"] == 500000


class TestPropertyFeeFixedRate:
    """PRD §3.7: 'In FIXED_RATE mode the request must include
    fixed_rate_cents_per_month, and the bill amount before capping is
    fixed_rate_cents_per_month × months_in_period.'
    """

    def test_fixed_rate_multi_month(self, api):
        """PRD §3.7: 'fixed_rate_cents_per_month × months_in_period.'"""
        ctx = setup_active_lease()
        res = api.create_fee_bill(
            create_property_fee_bill_payload(
                lease_id=ctx["lease"]["id"],
                period_start="2026-01-01T00:00:00.000Z",
                period_end="2026-04-01T00:00:00.000Z",  # 3 months
                property_fee_mode="FIXED_RATE",
                fixed_rate_cents_per_month=50000,
            ),
            FO,
        )
        data = validate_success(res, expected_status=201)
        assert_fee_bill(data)
        # 50000 * 3 = 150000; cap = 5000 * 100 * 3 = 1500000 (not binding).
        assert data["amount_cents"] == 150000


# ===========================================================================
# ENERGY_FEE SUB_METER
# ===========================================================================
class TestEnergyFeeSubMeter:
    """PRD §3.7: 'In SUB_METER mode the request must include
    sub_meter_kwh ..., and the bill amount is the round-half-up of
    sub_meter_kwh × tariff_per_kwh_cents — this charge ignores area
    entirely.'
    """

    def test_sub_meter_amount_is_kwh_times_tariff(self, api):
        """PRD §3.7: 'the bill amount is the round-half-up of
        sub_meter_kwh × tariff_per_kwh_cents'."""
        ctx = setup_active_lease()
        res = api.create_fee_bill(
            create_energy_fee_bill_payload(
                lease_id=ctx["lease"]["id"],
                period_start="2026-01-01T00:00:00.000Z",
                period_end="2026-02-01T00:00:00.000Z",
                energy_mode="SUB_METER",
                tariff_per_kwh_cents=50,
                sub_meter_kwh=200,
            ),
            FO,
        )
        data = validate_success(res, expected_status=201)
        # 200 × 50 = 10000
        assert data["amount_cents"] == 10000


# ===========================================================================
# Fee bill state machine
# ===========================================================================
class TestFeeBillLifecycle:
    """PRD §3.7: 'A FeeBill flows through a small lifecycle. A tenant
    paying a bill moves its status from ISSUED to PAID; ... A tenant
    disputing a bill moves its status from ISSUED to DISPUTED and
    stores the supplied dispute_reason on the bill. A finance officer
    resolves a dispute by submitting a resolution_keeps_bill
    boolean.'
    """

    def test_pay_transitions_to_paid(self, api):
        """PRD §3.7: 'A tenant paying a bill moves its status from
        ISSUED to PAID.'"""
        ctx = setup_active_lease()
        bill = create_property_fee_bill(
            lease_id=ctx["lease"]["id"],
            period_start="2026-01-01T00:00:00.000Z",
            period_end="2026-02-01T00:00:00.000Z",
            property_fee_mode="FIXED_RATE",
            fixed_rate_cents_per_month=20000,
        )
        res = api.pay_fee_bill(
            bill["id"], make_tenant_headers(ctx["tenant"]["id"]),
        )
        data = validate_success(res)
        assert data["status"] == "PAID"

    def test_dispute_stores_reason_and_transitions_to_disputed(self, api):
        """PRD §3.7: 'A tenant disputing a bill moves its status from
        ISSUED to DISPUTED and stores the supplied dispute_reason on
        the bill.'"""
        ctx = setup_active_lease()
        bill = create_property_fee_bill(
            lease_id=ctx["lease"]["id"],
            period_start="2026-01-01T00:00:00.000Z",
            period_end="2026-02-01T00:00:00.000Z",
            property_fee_mode="FIXED_RATE",
            fixed_rate_cents_per_month=20000,
        )
        res = api.dispute_fee_bill(
            bill["id"],
            dispute_fee_bill_payload(dispute_reason="Unjustified"),
            make_tenant_headers(ctx["tenant"]["id"]),
        )
        data = validate_success(res)
        assert data["status"] == "DISPUTED"
        assert data["dispute_reason"] == "Unjustified"

    def test_resolve_dispute_keep_returns_to_issued(self, api):
        """PRD §3.7: 'when true the bill cycles back to ISSUED and an
        AuditEvent with action FEE_DISPUTED is recorded.'"""
        ctx = setup_active_lease()
        bill = create_property_fee_bill(
            lease_id=ctx["lease"]["id"],
            period_start="2026-01-01T00:00:00.000Z",
            period_end="2026-02-01T00:00:00.000Z",
            property_fee_mode="FIXED_RATE",
            fixed_rate_cents_per_month=20000,
        )
        dispute_fee_bill(
            bill["id"], tenant_id=ctx["tenant"]["id"],
            dispute_reason="dispute",
        )
        res = api.resolve_dispute_fee_bill(
            bill["id"],
            resolve_dispute_payload(resolution_keeps_bill=True),
            FO,
        )
        data = validate_success(res)
        assert data["status"] == "ISSUED"
        rows = list_audit_events(
            subject_kind="FEE_BILL", subject_id=bill["id"],
            action="FEE_DISPUTED",
        )
        assert len(rows) >= 1

    def test_resolve_dispute_void_moves_to_voided(self, api):
        """PRD §3.7: 'and when false the bill moves to VOIDED and an
        AuditEvent with action FEE_ADJUSTED is recorded.'"""
        ctx = setup_active_lease()
        bill = create_property_fee_bill(
            lease_id=ctx["lease"]["id"],
            period_start="2026-01-01T00:00:00.000Z",
            period_end="2026-02-01T00:00:00.000Z",
            property_fee_mode="FIXED_RATE",
            fixed_rate_cents_per_month=20000,
        )
        dispute_fee_bill(
            bill["id"], tenant_id=ctx["tenant"]["id"],
            dispute_reason="dispute",
        )
        res = api.resolve_dispute_fee_bill(
            bill["id"],
            resolve_dispute_payload(resolution_keeps_bill=False),
            FO,
        )
        data = validate_success(res)
        assert data["status"] == "VOIDED"
        rows = list_audit_events(
            subject_kind="FEE_BILL", subject_id=bill["id"],
            action="FEE_ADJUSTED",
        )
        assert len(rows) >= 1

    def test_void_issued_moves_to_voided(self, api):
        """PRD §3.7: 'A finance officer may also void a bill outright
        from ISSUED to VOIDED, which similarly records FEE_ADJUSTED.'"""
        ctx = setup_active_lease()
        bill = create_property_fee_bill(
            lease_id=ctx["lease"]["id"],
            period_start="2026-01-01T00:00:00.000Z",
            period_end="2026-02-01T00:00:00.000Z",
            property_fee_mode="FIXED_RATE",
            fixed_rate_cents_per_month=20000,
        )
        res = api.void_fee_bill(bill["id"], FO)
        data = validate_success(res)
        assert data["status"] == "VOIDED"
        rows = list_audit_events(
            subject_kind="FEE_BILL", subject_id=bill["id"],
            action="FEE_ADJUSTED",
        )
        assert len(rows) >= 1


# ===========================================================================
# Billability gate
# ===========================================================================
class TestLeaseBillabilityGate:
    """PRD §3.7: 'The bill request is rejected with ERR_LEASE_NOT_BILLABLE
    unless the owning lease's status is ACTIVE, AMENDMENT_PENDING, or
    TERMINATING — bills against leases in DRAFT, SIGNED, or TERMINATED
    cannot be issued.'
    """

    def test_issue_against_draft_lease_rejected(self, api):
        """PRD §3.7: 'bills against leases in DRAFT, SIGNED, or
        TERMINATED cannot be issued.'"""
        from test_helpers import setup_draft_lease
        ctx = setup_draft_lease()
        res = api.create_fee_bill(
            create_property_fee_bill_payload(
                lease_id=ctx["lease"]["id"],
                period_start="2026-01-01T00:00:00.000Z",
                period_end="2026-02-01T00:00:00.000Z",
                property_fee_mode="FIXED_RATE",
                fixed_rate_cents_per_month=50000,
            ),
            FO,
        )
        validate_error(res, ApiErrorId.ERR_LEASE_NOT_BILLABLE.value)

    def test_issue_against_signed_lease_rejected(self, api):
        """PRD §3.7: 'bills against leases in DRAFT, SIGNED, or
        TERMINATED cannot be issued.'"""
        ctx = setup_signed_lease()
        res = api.create_fee_bill(
            create_property_fee_bill_payload(
                lease_id=ctx["lease"]["id"],
                period_start="2026-01-01T00:00:00.000Z",
                period_end="2026-02-01T00:00:00.000Z",
                property_fee_mode="FIXED_RATE",
                fixed_rate_cents_per_month=50000,
            ),
            FO,
        )
        validate_error(res, ApiErrorId.ERR_LEASE_NOT_BILLABLE.value)
