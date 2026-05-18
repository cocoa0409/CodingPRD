"""Customer onboarding (FICO tier derivation, status) and Vehicle CRUD.

PRD §3.1 — customer create / update / suspend / reinstate, FICO bands.
PRD §3.2 — vehicle register, residual_factor_bps bounds.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    api_client,
    assert_customer,
    assert_vehicle,
    create_customer,
    create_vehicle,
    get_customer,
    make_customer_headers,
    random_vin,
    reinstate_customer,
    suspend_customer,
    update_customer_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# Customer create — happy path + FICO tier derivation
# ===========================================================================
class TestCustomerCreate:

    def test_create_customer_returns_active_with_zero_clock(self, api):
        """PRD §3.1: "On a successful create, the customer's status is
        set to ACTIVE, the per-customer clock_day_index is initialized
        to 0, and the cumulative counters default_count,
        lifetime_payment_count, and default_rate start at 0, 0, and
        0.0 respectively."

        Claim: POST /customers returns ACTIVE, clock=0, default_count=0,
        lifetime_payment_count=0, default_rate=0.
        """
        cust = create_customer(fico_score=700)
        assert_customer(cust)
        assert cust["status"] == "ACTIVE"
        assert cust["clock_day_index"] == 0
        assert cust["default_count"] == 0
        assert cust["lifetime_payment_count"] == 0
        assert float(cust["default_rate"]) == 0.0

    @pytest.mark.parametrize("fico,tier", [
        (850, "TIER_1"),
        (720, "TIER_1"),
        (719, "TIER_2"),
        (700, "TIER_2"),
        (660, "TIER_2"),
        (659, "TIER_3"),
        (600, "TIER_3"),
        (599, "TIER_4"),
        (540, "TIER_4"),
        (539, "TIER_5_DECLINED"),
        (300, "TIER_5_DECLINED"),
    ])
    def test_fico_tier_assignment_boundaries(self, api, fico, tier):
        """PRD §3.1: "a score of at least 720 maps to TIER_1; a score
        below 720 but at least 660 maps to TIER_2; a score below 660
        but at least 600 maps to TIER_3; a score below 600 but at
        least 540 maps to TIER_4; any score below 540 maps to
        TIER_5_DECLINED. The boundaries are crisp: 720 is TIER_1 and
        719 is TIER_2; 660 is TIER_2 and 659 is TIER_3; and so on."

        Claim: each fico boundary lands on the named tier.
        """
        cust = create_customer(fico_score=fico)
        assert cust["fico_tier"] == tier, (
            f"fico_score={fico} expected {tier}, got "
            f"{cust['fico_tier']}"
        )

    @pytest.mark.parametrize("bad_fico", [299, 851, 0, -1, 1000])
    def test_fico_score_out_of_range_rejected(self, api, bad_fico):
        """PRD §3.1: "The server validates that fico_score lies between
        300 and 850 inclusive; values outside that range are rejected
        with ERR_FICO_OUT_OF_RANGE."

        Claim: fico_score outside [300, 850] -> ERR_FICO_OUT_OF_RANGE.
        """
        resp = api_client.create_customer(
            {"full_name": "X", "fico_score": bad_fico},
            TEST_USERS["platform_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FICO_OUT_OF_RANGE.value)


# ===========================================================================
# Customer update — fico_tier re-derivation
# ===========================================================================
class TestCustomerUpdate:

    def test_update_fico_score_re_derives_tier(self, api):
        """PRD §3.1: "A subsequent update to the customer that changes
        fico_score re-derives fico_tier immediately as part of the same
        response."

        Claim: PUT /customers with new fico_score -> fico_tier
        recomputed on the returned row.
        """
        cust = create_customer(fico_score=700)
        assert cust["fico_tier"] == "TIER_2"
        resp = api_client.update_customer(
            cust["id"],
            update_customer_payload(fico_score=720),
            TEST_USERS["platform_admin_headers"],
        )
        updated = validate_success(resp)
        assert updated["fico_score"] == 720
        assert updated["fico_tier"] == "TIER_1"


# ===========================================================================
# Customer suspend / reinstate
# ===========================================================================
class TestCustomerSuspendReinstate:

    def test_suspend_transitions_to_suspended(self, api):
        """PRD §3.1: "the customer's status transitions from ACTIVE to
        SUSPENDED."

        Claim: POST /customers/{id}/suspend on ACTIVE -> SUSPENDED.
        """
        cust = create_customer()
        suspended = suspend_customer(cust)
        assert suspended["status"] == "SUSPENDED"

    def test_reinstate_returns_to_active(self, api):
        """PRD §3.1: "The customer may later be reinstated by a
        PlatformAdmin, transitioning status back from SUSPENDED to
        ACTIVE."

        Claim: POST /customers/{id}/reinstate on SUSPENDED -> ACTIVE.
        """
        cust = create_customer()
        suspend_customer(cust)
        re = reinstate_customer(cust)
        assert re["status"] == "ACTIVE"

    def test_loan_officer_cannot_suspend(self, api):
        """PRD §4 (and §2.1): suspend is PlatformAdmin exclusive.

        Claim: LoanOfficer calling /suspend -> ERR_FORBIDDEN_ROLE.
        """
        cust = create_customer()
        resp = api_client.suspend_customer(
            cust["id"], TEST_USERS["loan_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ===========================================================================
# Clock advance — out-of-range rejection
# ===========================================================================
class TestClockAdvanceBounds:

    @pytest.mark.parametrize("bad_days", [0, -1, 366, 500])
    def test_clock_advance_out_of_range_rejected(self, api, bad_days):
        """PRD §3.11: "The supplied days_advanced value must be between
        1 and 365 inclusive; an out-of-range value is rejected with
        ERR_CLOCK_ADVANCE_OUT_OF_RANGE."

        Claim: days_advanced outside [1,365] -> ERR_CLOCK_ADVANCE_OUT_OF_RANGE.
        """
        cust = create_customer()
        resp = api_client.advance_clock(
            cust["id"], {"days_advanced": bad_days},
            TEST_USERS["platform_admin_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_CLOCK_ADVANCE_OUT_OF_RANGE.value,
        )

    def test_clock_advance_increments_index_per_customer(self, api):
        """PRD §3.11: "a single customer's clock_day_index by an
        integer days_advanced."

        Claim: clock advance on customer A does not touch customer B's
        clock_day_index. (PRD §2.9: "The clock is also reproducible
        per customer — advancing one customer's clock does not affect
        any other customer's payments, lease maturity, or default
        counters.")
        """
        a = create_customer()
        b = create_customer()
        ev = advance_clock(a, 5)
        assert ev["new_clock_day_index"] == 5
        b_after = get_customer(b)
        assert b_after["clock_day_index"] == 0


# ===========================================================================
# Vehicle CRUD — PRD §3.2
# ===========================================================================
class TestVehicle:

    def test_create_vehicle_starts_available(self, api):
        """PRD §3.2: "The vehicle's status begins at AVAILABLE on
        creation."

        Claim: POST /vehicles -> status == 'AVAILABLE'.
        """
        v = create_vehicle()
        assert_vehicle(v)
        assert v["status"] == "AVAILABLE"

    @pytest.mark.parametrize("bad_rf", [999, 0, 8001, 10000, -100])
    def test_residual_factor_bps_out_of_range_rejected(self, api, bad_rf):
        """PRD §3.2: "its residual_factor_bps — the residual value as
        basis points of MSRP for a 36-month lease, constrained to lie
        between 1000 and 8000 inclusive (so 5500 represents a 55%
        residual)."

        Claim: residual_factor_bps outside [1000,8000] -> ERR_INVALID_REQUEST.
        """
        resp = api_client.create_vehicle(
            {"vin": random_vin(), "model": "M",
             "msrp_cents": 1_000_000,
             "residual_factor_bps": bad_rf},
            TEST_USERS["platform_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    @pytest.mark.parametrize("bad_msrp", [0, -1, -1000])
    def test_msrp_must_be_strictly_positive(self, api, bad_msrp):
        """PRD §3.2: "msrp_cents manufacturer-suggested retail price
        (which must be strictly greater than zero, expressed in
        cents)".

        Claim: msrp_cents <= 0 -> ERR_INVALID_REQUEST.
        """
        resp = api_client.create_vehicle(
            {"vin": random_vin(), "model": "M",
             "msrp_cents": bad_msrp,
             "residual_factor_bps": 5000},
            TEST_USERS["platform_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
