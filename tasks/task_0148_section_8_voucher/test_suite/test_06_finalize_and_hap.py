"""Finalize gates — mobility, rent-reasonableness, rent-burden — TTP
and HAP computations, and the LEASED cascade.

PRD §3.7.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    add_days,
    assert_hap_plus_ttp_equals_gross_rent,
    assert_tenancy,
    current_clock,
    finalize_tenancy,
    get_tenancy,
    get_unit,
    get_voucher,
    iso_utc,
    make_case_worker_headers,
    new_case_worker_id,
    setup_active_tenancy,
    setup_burden_at_boundary,
    setup_eligible_applicant_with_voucher,
    setup_special_mobility_with_zone_b_unit,
    setup_tenancy_pending_rent_reasonable,
    setup_unit_with_payment_standard,
    validate_error,
    validate_success,
    create_pending_tenancy,
    attach_rent_reasonableness,
    schedule_inspection,
    complete_inspection,
)


class TestFinalizeRentBurdenBoundary:

    def test_burden_at_exactly_40pct_passes(self, api):
        """PRD §3.7: "The cap of 0.40 is inclusive — a burden exactly
        equal to 40 percent passes; a burden strictly greater than 40
        percent is rejected with ERR_RENT_BURDEN_EXCEEDED."

        Construction (PRD §3.1, §3.7):
          gross=1_200_000, no deductions → adjusted=1_200_000.
          monthly_adjusted=floor(1_200_000/12)=100_000.
          asking_rent=70_000, utilities=0, gross_rent=70_000.
          PS standard=60_000.
          TTP=max(ceil(100_000*.30), ceil(100_000*.10), 0, 5000)=30_000.
          HAP=min(60_000,70_000)-30_000=30_000.
          tenant_share=70_000-30_000=40_000; burden=0.40 inclusive PASS.
        # difficulty: boundary_precision_check/rent_burden_exactly_40pct_inclusive
        """
        state = setup_burden_at_boundary(over_by_one_cent=False)
        cw = make_case_worker_headers(new_case_worker_id())
        resp = api.finalize_tenancy(state["tenancy"]["id"], {}, cw)
        data = validate_success(resp)
        assert data["status"] == "ACTIVE"
        assert data["initial_total_tenant_payment_cents"] == 30_000
        assert data["initial_hap_cents"] == 30_000

    def test_burden_at_40_001pct_rejected(self, api):
        """PRD §3.7: "a burden strictly greater than 40 percent is
        rejected with ERR_RENT_BURDEN_EXCEEDED."
        # difficulty: boundary_precision_check/rent_burden_exactly_40pct_inclusive
        # difficulty: combinatorial_formula/rent_burden_circular_evaluation_order_mode_c
        """
        state = setup_burden_at_boundary(over_by_one_cent=True)
        cw = make_case_worker_headers(new_case_worker_id())
        resp = api.finalize_tenancy(state["tenancy"]["id"], {}, cw)
        validate_error(resp, ApiErrorId.ERR_RENT_BURDEN_EXCEEDED.value)
        # Tenancy should not have advanced.
        t = get_tenancy(state["tenancy"]["id"])
        assert t["status"] in ("PENDING_RENT_REASONABLE", "REJECTED")


class TestFinalizeMobilityZone:

    def test_special_mobility_voucher_with_zone_b_unit_rejected(self, api):
        """PRD §3.7: "if the voucher's special_mobility_flag is true,
        the unit's zone must equal ZONE_A, or the finalize is rejected
        with ERR_MOBILITY_ZONE_VIOLATION."
        # difficulty: cross_entity_state_dependency/tenancy_finalize_requires_unit_zone_for_mobility_pair_tenancy_unit
        """
        state = setup_special_mobility_with_zone_b_unit()
        cw = make_case_worker_headers(new_case_worker_id())
        resp = api.finalize_tenancy(state["tenancy"]["id"], {}, cw)
        validate_error(
            resp, ApiErrorId.ERR_MOBILITY_ZONE_VIOLATION.value,
        )


class TestFinalizeRentNotReasonable:

    def test_finalize_with_unreasonable_rent_rejected(self, api):
        """PRD §3.7: "the attached rent-reasonableness record's
        is_reasonable must be true, or the finalize is rejected with
        ERR_RENT_NOT_REASONABLE."
        """
        # Force is_reasonable = False by passing low comparables vs
        # high gross_rent.
        state = setup_tenancy_pending_rent_reasonable(
            household_size=2, dependents_count=0,
            gross_annual_income_cents=2_400_000,
            zone="ZONE_A", bedroom_count=1,
            asking_rent_cents=200_000, tenant_paid_utilities_cents=0,
            standard_amount_cents=200_000,
            comparable_rents_cents=[80_000, 90_000, 100_000],
        )
        # gross_rent=200_000, threshold=floor(90_000*1.10)=99_000.
        assert state["rent_record"]["is_reasonable"] is False
        cw = make_case_worker_headers(new_case_worker_id())
        resp = api.finalize_tenancy(state["tenancy"]["id"], {}, cw)
        validate_error(resp, ApiErrorId.ERR_RENT_NOT_REASONABLE.value)


class TestFinalizeRentBurdenDivZero:

    def test_zero_adjusted_income_yields_burden_divzero(self, api):
        """PRD §3.7: "if the applicant's adjusted_annual_income_cents is
        zero, the rent-burden ratio is undefined and the finalize is
        rejected with ERR_RENT_BURDEN_DIVZERO".
        """
        # Build an applicant whose deductions zero out adjusted income.
        state = setup_tenancy_pending_rent_reasonable(
            gross_annual_income_cents=1_000_000,
            household_size=1, dependents_count=0,
            elderly_or_disabled_head=False,
            childcare_expense_annual_cents=2_000_000,  # capped at gross → wipes adjusted to 0
            zone="ZONE_A", bedroom_count=0,
            asking_rent_cents=60_000, tenant_paid_utilities_cents=0,
            standard_amount_cents=60_000,
            comparable_rents_cents=[50_000, 60_000, 70_000],
        )
        cw = make_case_worker_headers(new_case_worker_id())
        resp = api.finalize_tenancy(state["tenancy"]["id"], {}, cw)
        validate_error(resp, ApiErrorId.ERR_RENT_BURDEN_DIVZERO.value)


class TestFinalizeSpecialMobilityHAP:
    """PRD §3.7: HAP uses applicable_payment_standard_cents which was
    frozen on the tenancy using mobility_amount_cents when
    Voucher.special_mobility_flag=true. Same Tenancy gross_rent but
    different cent value for initial_hap."""

    def test_hap_uses_mobility_tier_for_special_mobility_voucher(self, api):
        """PRD §3.7 (HAP formula) + PRD §3.4 (PS lookup): the PS
        substitution between standard and mobility tier produces a
        DIFFERENT initial_hap_cents for identical gross_rent.

        Setup: PS standard=120_000 mobility=132_000. gross_rent=135_000.
        Initial TTP=73_800.
          T1 (standard):     HAP = min(120_000, 135_000) - 73_800 = 46_200.
          T2 (special_mob.): HAP = min(132_000, 135_000) - 73_800 = 58_200.
        # difficulty: dual_variant_calc/hap_standard_vs_special_mobility_on_tenancy
        """
        # Tenant A1 — standard.
        state1 = setup_tenancy_pending_rent_reasonable(
            gross_annual_income_cents=3_000_000,
            household_size=3, dependents_count=1,
            elderly_or_disabled_head=False,
            zone="ZONE_A", bedroom_count=2,
            asking_rent_cents=125_000, tenant_paid_utilities_cents=10_000,
            standard_amount_cents=120_000,
            mobility_amount_cents=132_000,
            special_mobility_flag=False,
            comparable_rents_cents=[120_000, 130_000, 140_000, 150_000],
        )
        t1_finalized = finalize_tenancy(state1["tenancy"]["id"])
        assert t1_finalized["initial_hap_cents"] == 46_200, (
            f"standard HAP expected 46_200, got {t1_finalized['initial_hap_cents']}"
        )
        # Tenant A2 — special_mobility, identical financials.
        state2 = setup_tenancy_pending_rent_reasonable(
            gross_annual_income_cents=3_000_000,
            household_size=3, dependents_count=1,
            elderly_or_disabled_head=False,
            zone="ZONE_A", bedroom_count=2,
            asking_rent_cents=125_000, tenant_paid_utilities_cents=10_000,
            standard_amount_cents=120_000,
            mobility_amount_cents=132_000,
            special_mobility_flag=True,
            comparable_rents_cents=[120_000, 130_000, 140_000, 150_000],
        )
        t2_finalized = finalize_tenancy(state2["tenancy"]["id"])
        assert t2_finalized["initial_hap_cents"] == 58_200, (
            f"special_mobility HAP expected 58_200, got "
            f"{t2_finalized['initial_hap_cents']}"
        )
        assert t1_finalized["initial_hap_cents"] != t2_finalized["initial_hap_cents"]


class TestTTPFormula:

    def test_initial_ttp_uses_divide_then_floor_then_multiply_then_ceil(
        self, api,
    ):
        """PRD §3.7: "monthly adjusted income is the floor of annual
        adjusted income divided by 12, and the thirty-percent figure is
        then the ceiling of monthly adjusted income times 0.30 ... This
        rounding order is pinned: divide-then-floor first, then
        multiply-then-ceil — reversing the order produces different
        cent values."

        For adjusted=2_952_000 (3-person, 1 dep): monthly = floor(2_952_000/12)
        = 246_000; 0.30 ceil → ceil(73_800) = 73_800.
        gross=3_000_000; monthly=250_000; 0.10 ceil → 25_000.
        max(73_800, 25_000, 0, 5000) = 73_800.
        """
        state = setup_active_tenancy(
            gross_annual_income_cents=3_000_000,
            household_size=3, dependents_count=1,
            zone="ZONE_A", bedroom_count=2,
            asking_rent_cents=125_000, tenant_paid_utilities_cents=10_000,
            standard_amount_cents=120_000,
            comparable_rents_cents=[120_000, 130_000, 140_000, 150_000],
        )
        t = state["tenancy"]
        assert t["initial_total_tenant_payment_cents"] == 73_800
        # HAP = min(120_000, 135_000) - 73_800 = 46_200.
        assert t["initial_hap_cents"] == 46_200

    def test_minimum_rent_floor_50_dollars(self, api):
        """PRD §3.7: "the statutory minimum rent floor
        (MINIMUM_RENT_CENTS, configured at $50 per month — five
        thousand cents)".

        For very low income, TTP floors at 5_000.
        """
        state = setup_tenancy_pending_rent_reasonable(
            gross_annual_income_cents=100_000,  # $1000/yr
            household_size=1, dependents_count=0,
            zone="ZONE_A", bedroom_count=0,
            asking_rent_cents=60_000, tenant_paid_utilities_cents=0,
            standard_amount_cents=60_000,
            comparable_rents_cents=[55_000, 60_000, 65_000],
        )
        # rent_burden divzero only triggers if adjusted==0; here
        # adjusted=100_000, monthly=8_333.
        # tenant_share = 60_000 - HAP. TTP = max(ceil(8_333*.30)=2_500,
        # ceil(8_333*.10)=834, 0, 5000) = 5_000.
        # HAP = min(60_000, 60_000) - 5_000 = 55_000.
        # burden = (60_000 - 55_000) / 8_333 = 0.6... too high — FAIL.
        # So this test must be re-framed: we need a setup where the
        # minimum rent dominates AND burden passes. Skip the burden
        # part and just observe TTP via the SUBMITTED Tenancy state by
        # NOT calling finalize. (Initial TTP is only computed on the
        # ACTIVE transition per PRD §3.7.)
        # Instead use sufficient income so burden passes but min rent
        # still dominates.
        state2 = setup_tenancy_pending_rent_reasonable(
            gross_annual_income_cents=240_000,    # $2400/yr
            household_size=1, dependents_count=0,
            zone="ZONE_A", bedroom_count=0,
            asking_rent_cents=15_000, tenant_paid_utilities_cents=0,
            standard_amount_cents=20_000,
            comparable_rents_cents=[14_000, 15_000, 16_000],
        )
        # adjusted=240_000, monthly=20_000.
        # 30% ceil = 6_000, 10% ceil = 2_000, min_rent = 5_000.
        # TTP = max(6_000, 2_000, 0, 5_000) = 6_000 (NOT minimum).
        # Try even lower income — but burden gates need a higher denom.
        # The MIN_RENT floor dominates when 30% < 5_000, i.e.,
        # monthly_adjusted * 0.30 < 5_000 → monthly_adjusted < 16_666.
        state3 = setup_tenancy_pending_rent_reasonable(
            gross_annual_income_cents=180_000,    # $1800/yr
            household_size=1, dependents_count=0,
            zone="ZONE_A", bedroom_count=0,
            asking_rent_cents=4_000, tenant_paid_utilities_cents=0,
            standard_amount_cents=10_000,
            comparable_rents_cents=[3_000, 4_000, 5_000],
        )
        # adjusted=180_000, monthly=15_000.
        # 30% ceil = 4_500, 10% ceil = 1_500, min_rent = 5_000.
        # TTP = max(4_500, 1_500, 0, 5_000) = 5_000.
        # HAP = min(10_000, 4_000) - 5_000 = max(0, -1000) = 0.
        # tenant_share = 4_000 - 0 = 4_000; burden = 4_000/15_000 = 0.267 → PASS.
        cw = make_case_worker_headers(new_case_worker_id())
        resp = api.finalize_tenancy(state3["tenancy"]["id"], {}, cw)
        data = validate_success(resp)
        assert data["initial_total_tenant_payment_cents"] == 5_000


class TestFinalizeCascadeAndInvariant:

    def test_finalize_active_cascades_voucher_to_leased(self, api):
        """PRD §3.7: "the tenancy advances from PENDING_RENT_REASONABLE
        to ACTIVE, the voucher cascades from SEARCHING (or
        SEARCHING_REISSUED) to LEASED, the unit's occupancy_status
        flips to OCCUPIED_ACTIVE".
        """
        state = setup_active_tenancy(
            gross_annual_income_cents=3_000_000,
            household_size=3, dependents_count=1,
        )
        t = state["tenancy"]
        v = state["voucher"]
        u = state["unit"]
        assert t["status"] == "ACTIVE"
        assert v["status"] == "LEASED"
        assert u["occupancy_status"] == "OCCUPIED_ACTIVE"

    def test_hap_plus_ttp_balances_gross_rent_at_lease_up(self, api):
        """PRD §3.7: "The initial HAP (Housing Assistance Payment) is
        the smaller of applicable_payment_standard_cents (already frozen
        on the tenancy) and gross_rent_cents, minus the initial TTP,
        then floored at zero."

        Claim: HAP + TTP + max(0, gross_rent - PS) == gross_rent.
        # difficulty: compensating_invariant/hap_plus_ttp_equals_gross_rent_per_tenancy_month
        """
        state = setup_active_tenancy(
            gross_annual_income_cents=3_000_000,
            household_size=3, dependents_count=1,
            zone="ZONE_A", bedroom_count=2,
            asking_rent_cents=110_000, tenant_paid_utilities_cents=10_000,
            standard_amount_cents=120_000,
            comparable_rents_cents=[110_000, 120_000, 130_000, 140_000],
        )
        assert_hap_plus_ttp_equals_gross_rent(state["tenancy"])
