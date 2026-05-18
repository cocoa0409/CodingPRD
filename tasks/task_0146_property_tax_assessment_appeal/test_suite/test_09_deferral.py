"""DeferralPlan lifecycle and interest accrual (PRD §3.6).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    DEFERRAL_INTEREST_RATE,
    DEFERRAL_MAX_TERM_DAYS,
    ApiErrorId,
    activate_deferral_plan,
    add_days_iso,
    add_minutes_iso,
    advance_clock_to,
    assert_deferral_plan,
    cancel_deferral_plan,
    create_owner,
    create_property,
    create_tax_bill,
    get_deferral_plan,
    get_tax_bill,
    iso_now_utc,
    make_owner_headers,
    request_deferral_plan,
    senior_eligible_dob,
    setup_finalized_assessment_via_clock,
    setup_issued_tax_bill,
    validate_error,
    validate_success,
    young_dob,
)


# ===========================================================================
# Eligibility — PRD §3.6
# ===========================================================================
class TestDeferralEligibility:

    def test_activate_requires_senior_age_or_disability(self, api):
        """PRD §3.6: 'Activation is gated by an eligibility check:
        the property's Owner must satisfy at least one hardship
        indicator — either Owner.disability_rating at least 50 percent
        (the system constant DEFERRAL_DISABILITY_MIN_PCT) or the
        Owner's age computed from date_of_birth is at least the
        system constant SENIOR_AGE (65 years). Failure raises
        ERR_DEFERRAL_NOT_ELIGIBLE.'

        Claim: a young, non-disabled Owner cannot activate a
        DeferralPlan; activation is rejected with
        ERR_DEFERRAL_NOT_ELIGIBLE.
        """
        # Owner young and not disabled.
        from test_helpers import api_client, TEST_USERS
        owner, prop, asmt, bill = setup_issued_tax_bill(
            market_value=400_000.00, roll_year=2025,
            market_value_at_roll=400_000.00, mill_rate=12.5,
            date_of_birth=young_dob(2025),
            disability_rating=0,
        )
        dp = request_deferral_plan(
            owner=owner, property_id=prop["id"],
            tax_bill_id=bill["id"],
        )
        resp = api_client.activate_deferral_plan(
            prop["id"], bill["id"], dp["id"],
            TEST_USERS["treasurer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_DEFERRAL_NOT_ELIGIBLE.value)

    def test_activate_succeeds_for_senior_owner(self, api):
        """PRD §3.6: 'either Owner.disability_rating at least 50
        percent (the system constant DEFERRAL_DISABILITY_MIN_PCT) or
        the Owner's age computed from date_of_birth is at least the
        system constant SENIOR_AGE (65 years).'

        Claim: an Owner of senior age can activate; status → ACTIVE
        and the bill cascades to IN_DEFERRAL.
        """
        owner, prop, asmt, bill = setup_issued_tax_bill(
            market_value=400_000.00, roll_year=2025,
            market_value_at_roll=400_000.00, mill_rate=12.5,
            date_of_birth=senior_eligible_dob(2025),
        )
        dp = request_deferral_plan(
            owner=owner, property_id=prop["id"],
            tax_bill_id=bill["id"],
        )
        activated = activate_deferral_plan(
            property_id=prop["id"], tax_bill_id=bill["id"],
            deferral_plan_id=dp["id"], version=dp["version"],
        )
        assert_deferral_plan(activated)
        assert activated["status"] == "ACTIVE"
        # PRD §3.6: 'principal_deferred is captured equal to the
        # bill's amount_due at this exact moment'. The bill base is
        # 400000*12.5/1000 = 5000.
        assert activated["principal_deferred"] == pytest.approx(
            5_000.00, abs=0.01,
        )
        # PRD §3.6: 'annual_interest_rate is captured from the system
        # constant DEFERRAL_INTEREST_RATE (5 percent annually)'.
        assert activated["annual_interest_rate"] == pytest.approx(
            0.05, abs=1e-9,
        )
        # PRD §3.6: 'the bill cascades to IN_DEFERRAL'.
        re_bill = get_tax_bill(prop["id"], bill["id"])
        assert re_bill["status"] == "IN_DEFERRAL"


# ===========================================================================
# Cross-entity gate — PRD §3.6
# ===========================================================================
class TestDeferralCrossEntityGate:

    def test_activate_rejected_when_bill_pending(self, api):
        """PRD §3.6: 'The linked TaxBill must be in ISSUED or
        PARTIALLY_PAID at activation; other states are rejected with
        ERR_INVALID_STATE and, where appropriate,
        ERR_ASSESSMENT_NOT_FINALIZED.'

        Claim: activating a DeferralPlan on a PENDING bill (the bill
        has been created but not yet issued) → ERR_INVALID_STATE.

        # difficulty: cross_entity_state_dependency/deferral_activation_requires_taxbill_issued_or_partial
        """
        # FINALIZE the Assessment naturally, then create the bill but
        # do NOT issue it (bill stays in PENDING).
        owner, prop, asmt = setup_finalized_assessment_via_clock(
            market_value=400_000.00, roll_year=2025,
            market_value_at_roll=400_000.00,
            date_of_birth=senior_eligible_dob(2025),
        )
        bill = create_tax_bill(
            property_id=prop["id"], roll_year=2025, mill_rate=12.5,
        )
        assert bill["status"] == "PENDING"
        dp = request_deferral_plan(
            owner=owner, property_id=prop["id"], tax_bill_id=bill["id"],
        )
        from test_helpers import api_client, TEST_USERS
        resp = api_client.activate_deferral_plan(
            prop["id"], bill["id"], dp["id"],
            TEST_USERS["treasurer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Cancel REQUESTED — PRD §3.6
# ===========================================================================
class TestCancelRequestedDeferral:

    def test_owner_cancels_requested_plan(self, api):
        """PRD §3.6: 'The Owner may cancel a request that has not yet
        been activated; this transitions the plan REQUESTED →
        DEFAULTED and is the model's way of recording a cancellation
        — the bill itself is unaffected and remains in whatever
        status it had before.'

        Claim: Owner cancels a REQUESTED plan → status=DEFAULTED;
        bill status unchanged.
        """
        owner, prop, asmt, bill = setup_issued_tax_bill(
            market_value=400_000.00, roll_year=2025,
            market_value_at_roll=400_000.00, mill_rate=12.5,
            date_of_birth=senior_eligible_dob(2025),
        )
        dp = request_deferral_plan(
            owner=owner, property_id=prop["id"], tax_bill_id=bill["id"],
        )
        cancelled = cancel_deferral_plan(
            owner=owner, property_id=prop["id"],
            tax_bill_id=bill["id"], deferral_plan_id=dp["id"],
            version=dp["version"],
        )
        assert cancelled["status"] == "DEFAULTED"
        # Bill unaffected.
        re_bill = get_tax_bill(prop["id"], bill["id"])
        assert re_bill["status"] == "ISSUED"


# ===========================================================================
# Interest accrual boundary — PRD §3.6
# ===========================================================================
class TestInterestAccrual:

    def test_same_day_deferral_has_zero_accrued(self, api):
        """PRD §3.6: 'When days_elapsed is zero (a same-day deferral),
        accrued_interest is exactly 0.00.'

        Claim: a freshly activated plan read same day reports
        accrued_interest == 0.00.

        # difficulty: boundary_precision_check/deferral_zero_days_zero_interest_boundary
        """
        owner, prop, asmt, bill = setup_issued_tax_bill(
            market_value=400_000.00, roll_year=2025,
            market_value_at_roll=400_000.00, mill_rate=12.5,
            date_of_birth=senior_eligible_dob(2025),
        )
        dp = request_deferral_plan(
            owner=owner, property_id=prop["id"], tax_bill_id=bill["id"],
        )
        activate_deferral_plan(
            property_id=prop["id"], tax_bill_id=bill["id"],
            deferral_plan_id=dp["id"], version=dp["version"],
        )
        fetched = get_deferral_plan(
            property_id=prop["id"], tax_bill_id=bill["id"],
            deferral_plan_id=dp["id"],
        )
        assert fetched["accrued_interest"] == pytest.approx(
            0.00, abs=0.005,
        ), (
            f"PRD §3.6: same-day deferral must have accrued_interest "
            f"exactly 0.00, got {fetched['accrued_interest']}"
        )

    def test_one_day_elapsed_accrued_matches_formula(self, api):
        """PRD §3.6: "The number of elapsed days is the floor of the
        difference between the current time and started_at, expressed
        in whole days. The daily rate is annual_interest_rate divided
        by 365.0. The accrued interest is principal_deferred
        multiplied by the quantity (1 + daily_rate) raised to the
        power days_elapsed, then minus 1, with the final result
        rounded half up to two decimal places exactly once — never
        per-day."

        Claim: after advancing the clock 1 day, accrued_interest
        equals round_half_up(principal_deferred * ((1+rate/365)^1 -
        1), 2).

        # difficulty: boundary_precision_check/deferral_zero_days_zero_interest_boundary
        """
        owner, prop, asmt, bill = setup_issued_tax_bill(
            market_value=400_000.00, roll_year=2025,
            market_value_at_roll=400_000.00, mill_rate=12.5,
            date_of_birth=senior_eligible_dob(2025),
        )
        dp = request_deferral_plan(
            owner=owner, property_id=prop["id"], tax_bill_id=bill["id"],
        )
        activated = activate_deferral_plan(
            property_id=prop["id"], tax_bill_id=bill["id"],
            deferral_plan_id=dp["id"], version=dp["version"],
        )
        # Advance one day. PRD §3.6: 'The number of elapsed days is
        # the floor of the difference between the current time and
        # started_at, expressed in whole days.' Add 1 day + 1 minute
        # to ensure floor = 1 even with timing jitter.
        new_ts = add_days_iso(activated["started_at"], 1)
        advance_clock_to(add_minutes_iso(new_ts, 1))
        fetched = get_deferral_plan(
            property_id=prop["id"], tax_bill_id=bill["id"],
            deferral_plan_id=dp["id"],
        )
        principal = activated["principal_deferred"]
        daily = 0.05 / 365.0
        expected = round(principal * ((1 + daily) ** 1 - 1), 2)
        assert fetched["accrued_interest"] == pytest.approx(
            expected, abs=0.01,
        ), (
            f"PRD §3.6 1-day accrual mismatch: expected {expected}, "
            f"got {fetched['accrued_interest']}"
        )


# ===========================================================================
# Default after max term — PRD §3.6
# ===========================================================================
class TestDeferralDefault:

    def test_clock_past_max_term_defaults_plan_and_delinquents_bill(self, api):
        """PRD §3.6: 'if the logical clock advances past started_at
        plus the system constant DEFERRAL_MAX_TERM_DAYS (365 days),
        the plan auto-transitions ACTIVE → DEFAULTED, closed_at is
        recorded, and the bill cascades from IN_DEFERRAL to
        DELINQUENT.'

        Claim: clock advanced past started_at + 365 days flips
        DeferralPlan → DEFAULTED and bill → DELINQUENT.
        """
        owner, prop, asmt, bill = setup_issued_tax_bill(
            market_value=400_000.00, roll_year=2025,
            market_value_at_roll=400_000.00, mill_rate=12.5,
            date_of_birth=senior_eligible_dob(2025),
        )
        dp = request_deferral_plan(
            owner=owner, property_id=prop["id"], tax_bill_id=bill["id"],
        )
        activated = activate_deferral_plan(
            property_id=prop["id"], tax_bill_id=bill["id"],
            deferral_plan_id=dp["id"], version=dp["version"],
        )
        # Advance clock 366 days past started_at.
        advance_clock_to(add_days_iso(activated["started_at"], 366))
        fetched = get_deferral_plan(
            property_id=prop["id"], tax_bill_id=bill["id"],
            deferral_plan_id=dp["id"],
        )
        assert fetched["status"] == "DEFAULTED"
        re_bill = get_tax_bill(prop["id"], bill["id"])
        assert re_bill["status"] == "DELINQUENT"
