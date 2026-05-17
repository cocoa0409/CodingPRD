"""Patient intake, sliding-fee scale, insurance plans.

PRD §3.4 (patient + sliding-fee), §3.5 (insurance plan + contract
mode).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    FPL_BASE_CENTS,
    FPL_INCREMENT_CENTS_PER_PERSON_OVER_4,
    TEST_USERS,
    assert_insurance_plan,
    assert_patient,
    create_insurance_plan,
    create_insurance_plan_payload,
    create_patient,
    create_patient_payload,
    fpl_base_cents,
    patch_patient_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.4 Patient create + initial computed fields
# ===========================================================================
class TestCreatePatient:

    def test_create_patient_initial_state(self, api):
        """PRD §3.4: "At creation the system also initialises
        deductible_remaining_cents to zero (administrators may later
        adjust this value at year-end via PATCH), initialises
        latest_crisis_level to null, and initialises
        safety_plan_required to false."

        Claim: a freshly-created Patient has
        deductible_remaining_cents=0, latest_crisis_level=null,
        safety_plan_required=false.
        """
        res = api.create_patient(
            create_patient_payload(),
            TEST_USERS["practice_admin_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert_patient(data)
        assert data["deductible_remaining_cents"] == 0
        assert data.get("latest_crisis_level") is None
        assert data["safety_plan_required"] is False

    def test_create_patient_negative_income_rejected(self, api):
        """PRD §3.4: "household_income_cents, must be at least zero."

        Claim: negative household_income_cents returns ERR_VALIDATION
        or ERR_INVALID_AMOUNT (PRD §2.6 normalises monetary input).
        """
        payload = create_patient_payload(household_income_cents=-1)
        res = api.create_patient(
            payload, TEST_USERS["practice_admin_headers"],
        )
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(
            res, ["ERR_INVALID_AMOUNT", "ERR_VALIDATION"],
        )

    def test_create_patient_zero_household_size_rejected(self, api):
        """PRD §3.4: "household_size, must be at least one."

        Claim: household_size=0 returns ERR_VALIDATION.
        """
        payload = create_patient_payload(household_size=0)
        res = api.create_patient(
            payload, TEST_USERS["practice_admin_headers"],
        )
        validate_error(res, "ERR_VALIDATION")


# ===========================================================================
# §3.4 Sliding-fee tier — boundary precision
# ===========================================================================
class TestSlidingFeeTier:
    """PRD §3.4: 'a ratio that is at most 1.00 yields
    sliding_fee_tier_pct of 20; a ratio that exceeds 1.00 but is at
    most 1.50 yields 40; a ratio that exceeds 1.50 but is at most 2.00
    yields 60; a ratio that exceeds 2.00 but is at most 2.50 yields 80;
    any ratio above 2.50 yields 100.'"""

    def test_household_one_at_or_below_fpl_yields_tier_20(self, api):
        """PRD §3.4: "a ratio that is at most 1.00 yields
        sliding_fee_tier_pct of 20" ... "1,497,000 cents for a
        household of one".

        Claim: household_size=1 with household_income_cents = FPL base
        (ratio = 1.00 exactly, inclusive of 1.00) yields
        sliding_fee_tier_pct=20.
        """
        res = api.create_patient(
            create_patient_payload(
                household_size=1,
                household_income_cents=FPL_BASE_CENTS[1],
            ),
            TEST_USERS["practice_admin_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["sliding_fee_tier_pct"] == 20

    def test_zero_income_yields_tier_20(self, api):
        """PRD §3.4: "If household_income_cents is zero or below, the
        household's poverty ratio is treated as zero" ... "a ratio that
        is at most 1.00 yields sliding_fee_tier_pct of 20".

        Claim: household_income_cents=0 yields sliding_fee_tier_pct=20.
        """
        res = api.create_patient(
            create_patient_payload(
                household_size=2, household_income_cents=0,
            ),
            TEST_USERS["practice_admin_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["sliding_fee_tier_pct"] == 20

    @pytest.mark.parametrize("ratio_target,expected_pct", [
        (1.50, 40),  # exact 1.50 -> 40 (upper inclusive)
        (2.00, 60),
        (2.50, 80),
    ])
    def test_tier_at_upper_boundary(self, api, ratio_target, expected_pct):
        """PRD §3.4: "a ratio that exceeds 1.00 but is at most 1.50
        yields 40; a ratio that exceeds 1.50 but is at most 2.00 yields
        60; a ratio that exceeds 2.00 but is at most 2.50 yields 80".

        Claim: ratios exactly at the upper bound 1.50 / 2.00 / 2.50
        yield 40 / 60 / 80 respectively (inclusive upper boundary).
        """
        size = 2
        income = int(FPL_BASE_CENTS[size] * ratio_target)
        res = api.create_patient(
            create_patient_payload(
                household_size=size, household_income_cents=income,
            ),
            TEST_USERS["practice_admin_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["sliding_fee_tier_pct"] == expected_pct

    def test_tier_above_top_bracket_yields_100(self, api):
        """PRD §3.4: "any ratio above 2.50 yields 100."

        Claim: a ratio strictly above 2.50 yields
        sliding_fee_tier_pct=100.
        """
        size = 2
        # 2.51x the base — strictly above 2.50.
        income = int(FPL_BASE_CENTS[size] * 2.51)
        res = api.create_patient(
            create_patient_payload(
                household_size=size, household_income_cents=income,
            ),
            TEST_USERS["practice_admin_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["sliding_fee_tier_pct"] == 100

    def test_household_size_5_extends_base(self, api):
        """PRD §3.4: "For households larger than four, the base is
        extended by adding 547,000 cents per additional person beyond
        four — so a household of five uses 3,685,000 cents as its base."

        Claim: a household of size 5 with income = 3,685,000 cents
        (ratio == 1.00 inclusive) yields sliding_fee_tier_pct=20.
        """
        assert fpl_base_cents(5) == FPL_BASE_CENTS[4] + (
            FPL_INCREMENT_CENTS_PER_PERSON_OVER_4
        )
        res = api.create_patient(
            create_patient_payload(
                household_size=5,
                household_income_cents=fpl_base_cents(5),
            ),
            TEST_USERS["practice_admin_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["sliding_fee_tier_pct"] == 20

    def test_patch_household_income_recomputes_tier(self, api):
        """PRD §3.4: "The tier is recomputed whenever a PATCH changes
        either household_income_cents or household_size."

        Claim: PATCH that changes household_income_cents recomputes
        sliding_fee_tier_pct.
        """
        patient = create_patient(
            household_size=2,
            household_income_cents=FPL_BASE_CENTS[2],  # tier 20
        )
        assert patient["sliding_fee_tier_pct"] == 20
        # Move ratio to ~2.6 -> tier 100.
        new_income = int(FPL_BASE_CENTS[2] * 2.6)
        res = api.patch_patient(
            patient["id"],
            patch_patient_payload(household_income_cents=new_income),
            TEST_USERS["practice_admin_headers"],
        )
        data = validate_success(res, expected_status=200)
        assert data["sliding_fee_tier_pct"] == 100


# ===========================================================================
# §3.5 InsurancePlan
# ===========================================================================
class TestInsurancePlan:

    def test_create_insurance_plan_minimal(self, api):
        """PRD §3.5: "An InsurancePlan is created with the payer's
        commercial name in payer_name, an internal plan_code that must
        be unique within the practice, a network_status of either
        IN_NETWORK or OUT_OF_NETWORK, and a contract_mode of either
        DEDUCTIBLE_FIRST or COPAY_ONLY."

        Claim: a successful create returns the recorded plan with the
        declared fields.
        """
        res = api.create_insurance_plan(
            create_insurance_plan_payload(),
            TEST_USERS["practice_admin_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert_insurance_plan(data)
        assert data["network_status"] == "IN_NETWORK"
        assert data["contract_mode"] == "DEDUCTIBLE_FIRST"

    def test_create_insurance_plan_negative_allowed_amount_rejected(
        self, api,
    ):
        """PRD §3.5: "All three monetary fields must be at least zero."
        PRD §2.6: "Negative monetary inputs are rejected with
        ERR_INVALID_AMOUNT (HTTP 422)."

        Claim: a negative allowed_amount_90834_cents returns
        ERR_INVALID_AMOUNT.
        """
        payload = create_insurance_plan_payload(
            allowed_amount_90834_cents=-1,
        )
        res = api.create_insurance_plan(
            payload, TEST_USERS["practice_admin_headers"],
        )
        validate_error(res, "ERR_INVALID_AMOUNT")

    def test_create_insurance_plan_duplicate_plan_code_rejected(self, api):
        """PRD §3.5: "an internal plan_code that must be unique within
        the practice."

        Claim: creating a second plan with the same plan_code returns
        ERR_VALIDATION (uniqueness violation).
        """
        first = create_insurance_plan(payer_name="Aetna")
        duplicate_payload = create_insurance_plan_payload(
            plan_code=first["plan_code"], payer_name="BCBS",
        )
        res = api.create_insurance_plan(
            duplicate_payload, TEST_USERS["practice_admin_headers"],
        )
        from test_helpers import validate_error_is_one_of
        # Implementations may surface uniqueness as ERR_VALIDATION
        # (priority-22 schema/constraint) — accept either generic 4xx
        # constraint error.
        validate_error_is_one_of(
            res, ["ERR_VALIDATION", "ERR_INVALID_STATE"],
        )
