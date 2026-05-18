"""Lease origination, approval, activation, and lease-specific rules.

PRD §3.4 — tier eligibility, money-factor table, lease minimum down
payments, half-open window overlap rule, per-component rounding for
monthly payment.
"""
from __future__ import annotations

import math

import pytest

from test_helpers import (
    DAYS_PER_PERIOD,
    LEASE_TAX_BPS,
    LEASE_TERM_MONTHS_ALLOWED,
    MILEAGE_ALLOWANCE_MAX,
    MILEAGE_ALLOWANCE_MIN,
    TIER_1_DP_BPS_LEASE,
    TIER_1_MF_MICRO,
    TIER_2_DP_BPS_LEASE,
    TIER_2_MF_MICRO,
    TIER_3_DP_BPS_LEASE,
    TIER_3_MF_MICRO,
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    api_client,
    approve_lease_contract,
    create_approve_activate_lease,
    create_customer,
    create_lease_contract,
    create_vehicle,
    get_lease_contract,
    list_payments_full,
    pay_n_lease_payments,
    setup_two_overlapping_lease_originations,
    validate_error,
)


# ===========================================================================
# Lease creation — happy + term + mileage validation
# ===========================================================================
class TestLeaseCreate:

    def test_create_lease_pending_approval(self, api):
        """PRD §3.4: "On creation, capitalized_cost_cents is computed
        as the vehicle's msrp_cents minus the down_payment_cents, and
        the contract enters PENDING_APPROVAL".

        Claim: capitalized_cost_cents = msrp - down_payment;
        status=PENDING_APPROVAL.
        """
        cust = create_customer(fico_score=700)
        veh = create_vehicle(
            msrp_cents=3_275_000, residual_factor_bps=5800,
        )
        lease = create_lease_contract(
            cust, veh,
            down_payment_cents=393_000,
            term_months=36,
            mileage_allowance=36_000,
        )
        assert lease["status"] == "PENDING_APPROVAL"
        assert lease["capitalized_cost_cents"] == 3_275_000 - 393_000

    @pytest.mark.parametrize("bad_term", [1, 12, 18, 25, 35, 49, 60])
    def test_invalid_lease_term_months_rejected(self, api, bad_term):
        """PRD §3.4: "The term_months for a lease must be one of 24,
        36, or 48 months."

        Claim: term outside {24,36,48} -> ERR_INVALID_REQUEST.
        """
        if bad_term in LEASE_TERM_MONTHS_ALLOWED:
            pytest.skip("term is valid")
        cust = create_customer(fico_score=700)
        veh = create_vehicle()
        resp = api_client.create_lease_contract(
            cust["id"],
            {"vehicle_id": veh["id"],
             "down_payment_cents": 200_000,
             "term_months": bad_term,
             "mileage_allowance": 36_000},
            TEST_USERS["loan_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    @pytest.mark.parametrize(
        "bad_mileage", [MILEAGE_ALLOWANCE_MIN - 1, 0, -1,
                        MILEAGE_ALLOWANCE_MAX + 1, 100_000],
    )
    def test_invalid_mileage_allowance_rejected(self, api, bad_mileage):
        """PRD §3.4: "constrained to lie between 10000 and 75000
        inclusive (so a typical 36-month lease at 12k miles per year
        is 36000)."

        Claim: mileage_allowance outside [10000,75000] -> ERR_INVALID_REQUEST.
        """
        cust = create_customer(fico_score=700)
        veh = create_vehicle()
        resp = api_client.create_lease_contract(
            cust["id"],
            {"vehicle_id": veh["id"],
             "down_payment_cents": 393_000,
             "term_months": 36,
             "mileage_allowance": bad_mileage},
            TEST_USERS["loan_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Lease approval — tier eligibility / minimum down / vehicle / customer
# ===========================================================================
class TestLeaseApproval:

    @pytest.mark.parametrize("fico", [580, 500])
    def test_lease_tier_ineligible_rejected(self, api, fico):
        """PRD §3.4: "leases are restricted to higher-quality credit
        tiers: only TIER_1, TIER_2, and TIER_3 are eligible. A
        customer in TIER_4 or TIER_5_DECLINED is rejected with
        ERR_LEASE_TIER_INELIGIBLE, even if the down payment exceeds
        the minimum."

        Claim: TIER_4 / TIER_5_DECLINED -> ERR_LEASE_TIER_INELIGIBLE,
        regardless of down payment size.
        """
        cust = create_customer(fico_score=fico)
        veh = create_vehicle(msrp_cents=3_000_000)
        # Generous down payment so down-payment check would pass.
        lease = create_lease_contract(
            cust, veh, down_payment_cents=2_000_000,
            term_months=36, mileage_allowance=36_000,
        )
        resp = api_client.approve_lease_contract(
            cust["id"], lease["id"],
            TEST_USERS["loan_officer_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_LEASE_TIER_INELIGIBLE.value,
        )

    @pytest.mark.parametrize("fico,bps", [
        (750, TIER_1_DP_BPS_LEASE),
        (700, TIER_2_DP_BPS_LEASE),
        (620, TIER_3_DP_BPS_LEASE),
    ])
    def test_lease_down_payment_below_minimum_rejected(self, api,
                                                       fico, bps):
        """PRD §3.4: "the lease minimum down payment uses a different
        schedule than the loan: TIER_1 requires 8% (800 basis
        points), TIER_2 requires 12% (1200 basis points), and TIER_3
        requires 18% (1800 basis points). Insufficient down payment
        is rejected with ERR_DOWN_PAYMENT_BELOW_MINIMUM."

        Claim: lease down payment one cent below tier minimum ->
        ERR_DOWN_PAYMENT_BELOW_MINIMUM.
        """
        msrp = 3_000_000
        cust = create_customer(fico_score=fico)
        veh = create_vehicle(msrp_cents=msrp)
        min_dp = math.ceil(msrp * bps / 10000)
        lease = create_lease_contract(
            cust, veh, down_payment_cents=min_dp - 1,
            term_months=36, mileage_allowance=36_000,
        )
        resp = api_client.approve_lease_contract(
            cust["id"], lease["id"],
            TEST_USERS["loan_officer_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_DOWN_PAYMENT_BELOW_MINIMUM.value,
        )

    @pytest.mark.parametrize("fico,mf", [
        (750, TIER_1_MF_MICRO),
        (700, TIER_2_MF_MICRO),
        (620, TIER_3_MF_MICRO),
    ])
    def test_money_factor_from_tier(self, api, fico, mf):
        """PRD §3.4: "TIER_1 carries 2000 (a money factor of 0.00200),
        TIER_2 carries 2800 (0.00280), and TIER_3 carries 4000
        (0.00400)".

        Claim: APPROVED lease.money_factor_micro == tier value.
        """
        cust = create_customer(fico_score=fico)
        veh = create_vehicle(msrp_cents=3_000_000)
        lease = create_lease_contract(
            cust, veh,
            down_payment_cents=2_000_000,  # over every minimum
            term_months=36, mileage_allowance=36_000,
        )
        approved = approve_lease_contract(cust, lease)
        assert approved["money_factor_micro"] == mf

    def test_residual_value_is_floor_msrp_times_rf_over_10000(self, api):
        """PRD §3.4: "The residual_value_cents is computed as the
        floor of the vehicle's msrp_cents multiplied by the vehicle's
        residual_factor_bps, divided by 10000".

        Claim: residual_value_cents == floor(msrp * rf / 10000).
        """
        cust = create_customer(fico_score=700)
        veh = create_vehicle(
            msrp_cents=3_275_000, residual_factor_bps=5800,
        )
        lease = create_lease_contract(
            cust, veh, down_payment_cents=393_000,
            term_months=36, mileage_allowance=36_000,
        )
        approved = approve_lease_contract(cust, lease)
        expected = math.floor(3_275_000 * 5800 / 10000)
        assert approved["residual_value_cents"] == expected

    def test_lease_monthly_payment_per_component_rounding(self, api):
        """PRD §3.4: "Depreciation cents is the floor of the
        difference of capitalized_cost_cents minus residual_value_cents,
        divided by term_months. Finance cents is the floor of the sum
        of capitalized_cost_cents plus residual_value_cents,
        multiplied by money_factor_micro, divided by one million.
        Those two integer components are summed to produce a base
        cents. The tax cents is the ceiling of base cents multiplied
        by 800 — the local lease tax of 8%, expressed as basis points
        — divided by 10000. The final monthly_payment_cents is base
        cents plus tax cents."

        Claim: TIER_2 (mf=2800), msrp=3_275_000, rf=5800, dp=393_000,
        term=36 -> per-component rounding yields 43934 (not 43935 that
        round-once-at-end would produce).
        """
        cust = create_customer(fico_score=700)
        veh = create_vehicle(
            msrp_cents=3_275_000, residual_factor_bps=5800,
        )
        lease = create_approve_activate_lease(
            cust, veh, down_payment_cents=393_000,
            term_months=36, mileage_allowance=36_000,
        )
        lease = get_lease_contract(cust, lease["id"])
        # Recompute per spec.
        cap = 3_275_000 - 393_000
        residual = math.floor(3_275_000 * 5800 / 10000)
        dep = math.floor((cap - residual) / 36)
        fin = math.floor((cap + residual) * 2800 / 1_000_000)
        base = dep + fin
        tax = math.ceil(base * LEASE_TAX_BPS / 10000)
        expected = base + tax
        assert lease["monthly_payment_cents"] == expected
        assert lease["monthly_payment_cents"] == 43934

    def test_activate_creates_lease_payment_schedule(self, api):
        """PRD §3.4: "Activation of an APPROVED lease mirrors loan
        activation: the system generates term_months child Payment
        rows with period_index 1 through term_months, due_day_index
        set to origination_day_index plus period_index multiplied by
        30, amount_due_cents snapshotted from monthly_payment_cents,
        contract_type set to LEASE".

        Claim: lease activation generates term_months Payment rows
        marked LEASE with correct period_index / due_day_index.
        """
        cust = create_customer(fico_score=700)
        veh = create_vehicle(
            msrp_cents=3_275_000, residual_factor_bps=5800,
        )
        lease = create_approve_activate_lease(
            cust, veh, down_payment_cents=393_000,
            term_months=36, mileage_allowance=36_000,
        )
        payments = list_payments_full(cust, contract_id=lease["id"])
        assert len(payments) == 36
        for p in payments:
            assert p["contract_type"] == "LEASE"
        payments.sort(key=lambda p: p["period_index"])
        for i, p in enumerate(payments, start=1):
            assert p["period_index"] == i
            assert p["due_day_index"] == (
                lease["origination_day_index"] + i * DAYS_PER_PERIOD
            )


# ===========================================================================
# Lease window overlap — half-open semantics (PRD §3.4)
# ===========================================================================
class TestLeaseWindowOverlap:

    def test_overlapping_lease_window_rejected(self, api):
        """PRD §3.4: "no two non-terminal LeaseContract rows owned by
        the same customer may have overlapping term windows. The
        window for a lease is the half-open interval from its
        origination_day_index to its maturity_day_index. Half-open
        semantics mean that exact adjacency — where one lease's
        maturity_day_index equals another's origination_day_index —
        is allowed, but a one-day overlap is not. A new lease whose
        term window collides with an existing non-terminal lease for
        the same customer is rejected with ERR_LEASE_WINDOW_OVERLAP."

        Claim: approve a second lease whose window overlaps an
        existing ACTIVE one -> ERR_LEASE_WINDOW_OVERLAP.
        """
        cust = create_customer(fico_score=700)
        _v1, _L1, L2 = setup_two_overlapping_lease_originations(cust)
        resp = api_client.approve_lease_contract(
            cust["id"], L2["id"],
            TEST_USERS["loan_officer_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_LEASE_WINDOW_OVERLAP.value,
        )

    def test_adjacent_lease_window_allowed(self, api):
        """PRD §3.4: "exact adjacency — where one lease's
        maturity_day_index equals another's origination_day_index —
        is allowed".

        Claim: with L1 matured but still on-record, originating a
        second lease whose origination_day_index == L1.maturity_day_index
        is APPROVED. (Adjacency must be allowed under half-open
        semantics.)
        """
        cust = create_customer(fico_score=750)
        v1 = create_vehicle(
            msrp_cents=3_275_000, residual_factor_bps=5800,
        )
        v2 = create_vehicle(
            msrp_cents=3_275_000, residual_factor_bps=5800,
        )
        L1 = create_approve_activate_lease(
            cust, v1, down_payment_cents=393_000,
            term_months=24, mileage_allowance=36_000,
        )
        # Pay all payments, then advance one tick so L1 matures.
        pay_n_lease_payments(cust, L1, 24)
        advance_clock(cust, 1)
        # Now clock_day_index >= L1.maturity_day_index. Originate L2;
        # its origination_day_index will land at the customer's clock,
        # which is == L1.maturity_day_index (or one day later — both
        # are PRD-faithful: a one-day gap is also non-overlapping).
        L2 = create_lease_contract(
            cust, v2, down_payment_cents=393_000,
            term_months=24, mileage_allowance=36_000,
        )
        resp = api_client.approve_lease_contract(
            cust["id"], L2["id"],
            TEST_USERS["loan_officer_headers"],
        )
        # Adjacency is allowed; the call must succeed.
        assert resp.status_code == 200, (
            f"adjacency must succeed; got {resp.status_code} "
            f"{getattr(resp, 'text', '')}"
        )
