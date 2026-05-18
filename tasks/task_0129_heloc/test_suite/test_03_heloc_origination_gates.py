"""HELOC origination gates and activation transition.

Covers PRD §3.2 origination safety checks (occupancy, lien position,
bankruptcy, CLTV, borrower-property match, rate-bound configuration)
and the PENDING → DRAW activation transition.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    activate_heloc_payload,
    assert_heloc,
    assert_version_incremented_by_one,
    create_borrower,
    create_heloc,
    create_heloc_payload,
    create_property,
    create_senior_lien,
    setup_borrower_property_lien,
    setup_pending_heloc,
    post_bankruptcy_event,
    post_senior_lien_default_event,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.2 PENDING creation default state
# ===========================================================================
class TestHelocCreatedInPending:

    def test_create_heloc_lands_in_pending_with_zero_balances(
        self, api, originator_headers,
    ):
        """PRD §3.2: "A successfully created HELOC lands in the PENDING
        status with zero principal_balance_cents, zero
        accrued_interest_cents, and zero delinquency_days."
        """
        borrower, prop, _, heloc = setup_pending_heloc()
        assert_heloc(heloc)
        assert heloc["status"] == "PENDING"
        assert heloc["principal_balance_cents"] == 0
        assert heloc["accrued_interest_cents"] == 0
        assert heloc["delinquency_days"] == 0


# ===========================================================================
# §3.2 Origination safety gates
# ===========================================================================
class TestOriginationGates:

    def test_secondary_occupancy_rejected(
        self, api, originator_headers,
    ):
        """PRD §3.2: "The property's occupancy must equal PRIMARY or
        the request is rejected with ERR_OCCUPANCY_NOT_PRIMARY."
        """
        borrower = create_borrower()
        prop = create_property(
            borrower_id=borrower["id"], occupancy="SECONDARY",
        )
        # Add a senior lien so this gate isolates from §3.2 lien gate.
        sl = create_senior_lien(property_id=prop["id"])
        resp = api.create_heloc(
            create_heloc_payload(
                borrower_id=borrower["id"], property_id=prop["id"],
            ),
            originator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_OCCUPANCY_NOT_PRIMARY.value)

    def test_investment_occupancy_rejected(
        self, api, originator_headers,
    ):
        """PRD §3.2: "The property's occupancy must equal PRIMARY or
        the request is rejected with ERR_OCCUPANCY_NOT_PRIMARY."
        """
        borrower = create_borrower()
        prop = create_property(
            borrower_id=borrower["id"], occupancy="INVESTMENT",
        )
        sl = create_senior_lien(property_id=prop["id"])
        resp = api.create_heloc(
            create_heloc_payload(
                borrower_id=borrower["id"], property_id=prop["id"],
            ),
            originator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_OCCUPANCY_NOT_PRIMARY.value)

    def test_no_senior_lien_rejected(self, api, originator_headers):
        """PRD §3.2: "There must be at least one existing SeniorLien on
        the same property whose status equals CURRENT, or the request
        is rejected with ERR_NO_SENIOR_LIEN (this enforces the
        second-lien position)."
        """
        borrower = create_borrower()
        prop = create_property(borrower_id=borrower["id"])
        # NO senior lien is created here.
        resp = api.create_heloc(
            create_heloc_payload(
                borrower_id=borrower["id"], property_id=prop["id"],
            ),
            originator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NO_SENIOR_LIEN.value)

    def test_defaulted_senior_lien_does_not_satisfy_lien_gate(
        self, api, originator_headers,
    ):
        """PRD §3.2: "There must be at least one existing SeniorLien on
        the same property whose status equals CURRENT, or the request
        is rejected with ERR_NO_SENIOR_LIEN".
        """
        borrower, prop, sl = setup_borrower_property_lien()
        # Default the senior lien before HELOC creation.
        post_senior_lien_default_event(sl["id"])
        resp = api.create_heloc(
            create_heloc_payload(
                borrower_id=borrower["id"], property_id=prop["id"],
            ),
            originator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NO_SENIOR_LIEN.value)

    def test_bankrupt_borrower_rejected(
        self, api, originator_headers,
    ):
        """PRD §3.2: "The owning borrower's bankruptcy_flag must equal
        false or the request is rejected with ERR_BORROWER_BANKRUPT."
        """
        borrower, prop, _ = setup_borrower_property_lien()
        post_bankruptcy_event(borrower["id"])
        resp = api.create_heloc(
            create_heloc_payload(
                borrower_id=borrower["id"], property_id=prop["id"],
            ),
            originator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_BORROWER_BANKRUPT.value)

    def test_cltv_exceeded_rejected(self, api, originator_headers):
        """PRD §3.2: "The combined loan-to-value at origination must not
        exceed 100 percent: the property's appraised_value_cents must
        be strictly greater than the senior lien's
        principal_balance_cents plus the requested credit_limit_cents,
        or the request is rejected with ERR_CLTV_EXCEEDED."
        """
        borrower, prop, sl = setup_borrower_property_lien(
            appraised_value_cents=20_000_000,
            senior_lien_principal_cents=15_000_000,
        )
        # appraised 20M, senior 15M, requested 6M → 21M > 20M → CLTV
        # exceeded.
        resp = api.create_heloc(
            create_heloc_payload(
                borrower_id=borrower["id"],
                property_id=prop["id"],
                credit_limit_cents=6_000_000,
            ),
            originator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CLTV_EXCEEDED.value)

    def test_cltv_strict_inequality_at_equal_rejected(
        self, api, originator_headers,
    ):
        """PRD §3.2: "the property's appraised_value_cents must be
        strictly greater than the senior lien's principal_balance_cents
        plus the requested credit_limit_cents".

        Boundary: appraised == senior + requested must FAIL because
        strict inequality is required.
        """
        borrower, prop, sl = setup_borrower_property_lien(
            appraised_value_cents=20_000_000,
            senior_lien_principal_cents=10_000_000,
        )
        # Equal sums: 10M + 10M == 20M; strict-greater fails.
        resp = api.create_heloc(
            create_heloc_payload(
                borrower_id=borrower["id"],
                property_id=prop["id"],
                credit_limit_cents=10_000_000,
            ),
            originator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CLTV_EXCEEDED.value)

    def test_borrower_property_mismatch_rejected(
        self, api, originator_headers,
    ):
        """PRD §3.2: "the property's borrower_id must match the HELOC's
        borrower_id so that the borrower owns the collateral they are
        pledging; a mismatch yields ERR_BORROWER_PROPERTY_MISMATCH."
        """
        owner = create_borrower()
        stranger = create_borrower()
        prop = create_property(borrower_id=owner["id"])
        sl = create_senior_lien(property_id=prop["id"])
        resp = api.create_heloc(
            create_heloc_payload(
                borrower_id=stranger["id"], property_id=prop["id"],
            ),
            originator_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_BORROWER_PROPERTY_MISMATCH.value,
        )


# ===========================================================================
# §3.2 Rate-configuration ordering checks
# ===========================================================================
class TestRateBoundConfiguration:

    def test_lifetime_cap_too_low_rejected(
        self, api, originator_headers,
    ):
        """PRD §3.2: "a lifetime_cap_bps that must be strictly greater
        than initial_rate_bps + periodic_cap_bps and at most 2500".
        PRD §3.2: "If any of these configured rate or cap bounds
        violate the ordering constraints ... the request is rejected
        with ERR_RATE_BOUND_INVALID."

        initial_rate_bps is fixed at activation; the check is also
        evaluated at create-time against the (assumed) initial_rate
        bound. lifetime_cap_bps==2500 paired with margin_bps==1000 and
        an implausibly-high initial_rate floor will violate; here we
        attack the explicit absolute bound of 2500 by setting 2501.

        PRD §3.2: "and at most 2500".
        """
        borrower, prop, _ = setup_borrower_property_lien()
        resp = api.create_heloc(
            create_heloc_payload(
                borrower_id=borrower["id"],
                property_id=prop["id"],
                lifetime_cap_bps=2501,  # > 2500 absolute upper bound
            ),
            originator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_RATE_BOUND_INVALID.value)

    def test_lifetime_floor_geq_initial_rate_rejected(
        self, api, originator_headers,
    ):
        """PRD §3.2: "a lifetime_floor_bps that is non-negative and
        strictly less than initial_rate_bps".

        With margin_bps=300 and lifetime_floor_bps high enough that no
        plausible initial_rate (prime+margin clamped to caps) could
        exceed the floor strictly, the configuration is invalid.
        """
        borrower, prop, _ = setup_borrower_property_lien()
        # Set floor very high so that clamp([prime+margin], floor,
        # cap) will pin initial_rate to floor, violating "strictly
        # less than initial_rate_bps".
        resp = api.create_heloc(
            create_heloc_payload(
                borrower_id=borrower["id"],
                property_id=prop["id"],
                margin_bps=300,
                periodic_cap_bps=200,
                lifetime_cap_bps=2000,
                lifetime_floor_bps=2000,  # >= cap, impossible bound
            ),
            originator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_RATE_BOUND_INVALID.value)


# ===========================================================================
# §3.2 Activation: PENDING → DRAW
# ===========================================================================
class TestActivation:

    def test_activation_transitions_pending_to_draw_and_sets_fields(
        self, api, originator_headers,
    ):
        """PRD §3.2: "The activation sets origination_date to the
        current server clock, computes draw_period_end_date as exactly
        3650 days (ten years) after origination_date, computes
        repayment_period_end_date as draw_period_end_date plus
        repayment_term_years multiplied by 365 days, computes
        initial_rate_bps as the sum of the supplied prime_rate_bps and
        the HELOC's margin_bps clamped to the closed interval bounded
        below by lifetime_floor_bps and above by lifetime_cap_bps,
        sets current_rate_bps equal to initial_rate_bps, sets
        available_credit_cents equal to credit_limit_cents, and
        transitions the HELOC's status from PENDING to DRAW."
        """
        _, _, _, heloc = setup_pending_heloc(
            margin_bps=300,
            periodic_cap_bps=200,
            lifetime_cap_bps=2000,
            lifetime_floor_bps=100,
            credit_limit_cents=2_000_000,
        )
        before_version = heloc["version"]
        resp = api.activate_heloc(
            heloc["id"],
            activate_heloc_payload(prime_rate_bps=500),
            originator_headers,
        )
        updated = validate_success(resp, 200)
        assert updated["status"] == "DRAW"
        # initial_rate_bps = clamp(500 + 300, 100, 2000) == 800.
        assert updated["initial_rate_bps"] == 800
        assert updated["current_rate_bps"] == 800
        # available_credit equals credit_limit at activation.
        assert (
            updated["available_credit_cents"]
            == updated["credit_limit_cents"]
        )
        # Activation is a mutation → version increments by 1.
        assert_version_incremented_by_one(updated, heloc)

    def test_activation_clamps_initial_rate_to_lifetime_cap(
        self, api, originator_headers,
    ):
        """PRD §3.2: "computes initial_rate_bps as the sum of the
        supplied prime_rate_bps and the HELOC's margin_bps clamped to
        the closed interval bounded below by lifetime_floor_bps and
        above by lifetime_cap_bps".

        With prime=2200 and margin=300 the raw sum is 2500; with
        lifetime_cap_bps=2000 the clamp brings it down to 2000.
        """
        _, _, _, heloc = setup_pending_heloc(
            margin_bps=300,
            periodic_cap_bps=200,
            lifetime_cap_bps=2000,
            lifetime_floor_bps=100,
        )
        resp = api.activate_heloc(
            heloc["id"],
            activate_heloc_payload(prime_rate_bps=2200),
            originator_headers,
        )
        updated = validate_success(resp, 200)
        assert updated["initial_rate_bps"] == 2000
        assert updated["current_rate_bps"] == 2000

    def test_activation_clamps_initial_rate_to_lifetime_floor(
        self, api, originator_headers,
    ):
        """PRD §3.2: "computes initial_rate_bps as the sum of the
        supplied prime_rate_bps and the HELOC's margin_bps clamped to
        the closed interval bounded below by lifetime_floor_bps and
        above by lifetime_cap_bps".

        With prime=0 and margin=0 the raw sum is 0; with
        lifetime_floor_bps=100 the clamp brings it up to 100.
        """
        _, _, _, heloc = setup_pending_heloc(
            margin_bps=0,
            periodic_cap_bps=200,
            lifetime_cap_bps=2000,
            lifetime_floor_bps=100,
        )
        resp = api.activate_heloc(
            heloc["id"],
            activate_heloc_payload(prime_rate_bps=0),
            originator_headers,
        )
        updated = validate_success(resp, 200)
        assert updated["initial_rate_bps"] == 100
        assert updated["current_rate_bps"] == 100

    def test_activate_already_active_returns_invalid_state(
        self, api, originator_headers,
    ):
        """PRD §3.2: "Activation ... requires the HELOC to be in
        PENDING — any other state yields ERR_INVALID_STATE".
        """
        _, _, _, heloc = setup_pending_heloc()
        validate_success(api.activate_heloc(
            heloc["id"],
            activate_heloc_payload(prime_rate_bps=500),
            originator_headers,
        ), 200)
        # Second activation attempt.
        resp = api.activate_heloc(
            heloc["id"],
            activate_heloc_payload(prime_rate_bps=500),
            originator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_activation_accepts_borderline_cltv(
        self, api, originator_headers,
    ):
        """PRD §3.2: "the property's appraised_value_cents must be
        strictly greater than the senior lien's principal_balance_cents
        plus the requested credit_limit_cents".

        Borderline-but-passing CLTV at create-time (appraised
        strictly greater by 1 cent) must also pass the activation
        re-check path. This confirms activation does not spuriously
        reject borderline-passing configurations.
        """
        borrower, prop, sl = setup_borrower_property_lien(
            appraised_value_cents=20_000_001,
            senior_lien_principal_cents=10_000_000,
        )
        heloc = create_heloc(
            borrower_id=borrower["id"],
            property_id=prop["id"],
            credit_limit_cents=10_000_000,
        )
        # 10M + 10M = 20M < 20_000_001 → strict-greater holds.
        resp = api.activate_heloc(
            heloc["id"],
            activate_heloc_payload(prime_rate_bps=500),
            originator_headers,
        )
        updated = validate_success(resp, 200)
        assert updated["status"] == "DRAW"
