"""Concurrency and serialization (PRD §2.5, §2.11).

The PRD explicitly defines outcomes for these races:
- Two lease-sign requests on the same unit with overlapping windows →
  exactly one succeeds, the loser gets ERR_LEASE_OVERLAP.
- Two reservation attempts on the same VACANT unit → exactly one wins,
  loser gets ERR_UNIT_NOT_AVAILABLE.
- Two top-ups whose cumulative > required → loser gets ERR_DEPOSIT_OVERPAY.
- Dispute racing pay on the same bill → exactly one wins, loser gets
  ERR_INVALID_STATE.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    create_approved_tenant,
    create_lease,
    create_property_fee_bill,
    create_property_fee_bill_payload,
    dispute_fee_bill_payload,
    make_tenant_headers,
    run_race,
    setup_active_lease,
    setup_building_with_unit,
    setup_signed_lease,
    sign_lease,
    top_up_payload,
    validate_error_is_one_of,
    LA,
)


# ===========================================================================
# Lease sign race
# ===========================================================================
class TestLeaseSignRace:
    """PRD §2.11: 'Two Lease sign requests for the same Unit whose
    [start_date, end_date) windows overlap are serialised on the pair
    (unit_id, overlapping window); the first to commit transitions its
    lease from DRAFT to SIGNED, and the second is rejected with
    ERR_LEASE_OVERLAP (HTTP 409).'
    """

    def test_concurrent_signs_yield_exactly_one_signed(self, api):
        """PRD §2.11: 'the first to commit transitions its lease from
        DRAFT to SIGNED, and the second is rejected with
        ERR_LEASE_OVERLAP'."""
        b, u = setup_building_with_unit()
        t1 = create_approved_tenant()
        t2 = create_approved_tenant()
        l1 = create_lease(
            unit_id=u["id"], tenant_id=t1["id"],
            start_date="2026-01-01T00:00:00.000Z",
            end_date="2026-12-01T00:00:00.000Z",
            base_monthly_rent_cents=100000, deposit_months=1,
        )
        l2 = create_lease(
            unit_id=u["id"], tenant_id=t2["id"],
            start_date="2026-06-01T00:00:00.000Z",
            end_date="2027-01-01T00:00:00.000Z",
            base_monthly_rent_cents=100000, deposit_months=1,
        )
        results = run_race(
            lambda: api.sign_lease(l1["id"], LA),
            lambda: api.sign_lease(l2["id"], LA),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # Loser is rejected with ERR_LEASE_OVERLAP.
        for fail in outcome["failures"]:
            body = fail.json()
            assert body["data"]["error_id"] == ApiErrorId.ERR_LEASE_OVERLAP.value


# ===========================================================================
# Reservation race
# ===========================================================================
class TestReservationRace:
    """PRD §2.11: 'Two reservation attempts on the same VACANT unit are
    serialised on the unit row; the first wins, and the second is
    rejected with ERR_UNIT_NOT_AVAILABLE (HTTP 409).'
    """

    def test_concurrent_reserve_yields_exactly_one_winner(self, api):
        """PRD §2.11: 'the first wins, and the second is rejected with
        ERR_UNIT_NOT_AVAILABLE'.

        Note on error precedence: PRD §3.3 says reservation rejects
        with `ERR_INVALID_STATE` unless the unit is presently `VACANT`,
        and with `ERR_UNIT_NOT_AVAILABLE` for an overlapping lease.
        Once the race winner commits, the loser observes the unit as
        `RESERVED` (no longer VACANT), so a faithful implementation
        could report either ERR_UNIT_NOT_AVAILABLE (per §2.11 race
        prose) or ERR_INVALID_STATE (per §3.3 state-precedence). PRD
        does not state that race semantics pre-empt the state-check
        path, so we accept either via validate_error_is_one_of per the
        error-precedence silence pattern.
        """
        b, u = setup_building_with_unit()
        t1 = create_approved_tenant()
        t2 = create_approved_tenant()
        results = run_race(
            lambda: api.reserve_unit(
                b["id"], u["id"], {"tenant_id": t1["id"]}, LA,
            ),
            lambda: api.reserve_unit(
                b["id"], u["id"], {"tenant_id": t2["id"]}, LA,
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        for fail in outcome["failures"]:
            body = fail.json()
            assert body["data"]["error_id"] in (
                ApiErrorId.ERR_UNIT_NOT_AVAILABLE.value,
                ApiErrorId.ERR_INVALID_STATE.value,
            )


# ===========================================================================
# Top-up race
# ===========================================================================
class TestTopUpRace:
    """PRD §2.11: 'Two simultaneous top-ups on the same Deposit are
    serialised on the deposit row; both succeed only if the cumulative
    collected_cents after both does not exceed required_cents,
    otherwise the loser is rejected with ERR_DEPOSIT_OVERPAY (HTTP
    409).'
    """

    def test_concurrent_top_ups_overpay_loser_rejected(self, api):
        """PRD §2.11: 'otherwise the loser is rejected with
        ERR_DEPOSIT_OVERPAY'."""
        ctx = setup_signed_lease(
            deposit_months=1, base_monthly_rent_cents=100000,
        )
        deposit = ctx["deposit"]
        tenant = ctx["tenant"]
        headers = make_tenant_headers(tenant["id"])

        # Each top-up alone is 60000 cents (well within required=100000),
        # but cumulative 120000 > 100000 so exactly one must lose.
        results = run_race(
            lambda: api.top_up_deposit(
                deposit["id"], top_up_payload(amount_cents=60000), headers,
            ),
            lambda: api.top_up_deposit(
                deposit["id"], top_up_payload(amount_cents=60000), headers,
            ),
        )
        outcome = assert_race_outcome(
            results, expected_successes=1, expected_failures=1,
        )
        for fail in outcome["failures"]:
            body = fail.json()
            assert body["data"]["error_id"] == (
                ApiErrorId.ERR_DEPOSIT_OVERPAY.value
            )


# ===========================================================================
# Dispute racing pay
# ===========================================================================
class TestDisputeRacingPay:
    """PRD §2.11: 'When a tenant disputes a FeeBill while a finance
    officer marks it PAID at the same time, the system serialises on
    FeeBill.status and exactly one wins; the loser is rejected with
    ERR_INVALID_STATE (HTTP 409).'
    """

    def test_dispute_and_pay_serialised(self, api):
        """PRD §2.11: 'exactly one wins; the loser is rejected with
        ERR_INVALID_STATE'."""
        ctx = setup_active_lease()
        bill = create_property_fee_bill(
            lease_id=ctx["lease"]["id"],
            period_start="2026-01-01T00:00:00.000Z",
            period_end="2026-02-01T00:00:00.000Z",
            property_fee_mode="FIXED_RATE",
            fixed_rate_cents_per_month=20000,
        )
        tenant_headers = make_tenant_headers(ctx["tenant"]["id"])
        results = run_race(
            lambda: api.pay_fee_bill(bill["id"], tenant_headers),
            lambda: api.dispute_fee_bill(
                bill["id"],
                dispute_fee_bill_payload(dispute_reason="dispute"),
                tenant_headers,
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        for fail in outcome["failures"]:
            body = fail.json()
            assert body["data"]["error_id"] == (
                ApiErrorId.ERR_INVALID_STATE.value
            )
