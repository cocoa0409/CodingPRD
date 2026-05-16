"""Household creation, applicant intake, immutable income / asset
records. Exercises PRD §3.1.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    add_applicant,
    add_asset,
    add_income,
    assert_applicant,
    assert_asset_record,
    assert_household,
    assert_income_record,
    create_application_payload,
    create_household,
    create_household_payload,
    create_state_policy,
    create_state_policy_payload,
    get_applicant,
    get_household,
    is_valid_uuid,
    random_state_code,
    setup_basic_household,
    validate_error,
    validate_success,
)


# ===========================================================================
# Household creation — PRD §3.1
# ===========================================================================
class TestHouseholdCreation:

    def test_create_household_returns_201_and_head_unset(
            self, api, intake_worker_headers):
        """PRD §3.1: "The household's head_applicant_id is initially
        null and is filled in automatically when the first Applicant
        with a non-EXCLUDED dependent_status is added to the
        household."

        Claim: create returns 201, head_applicant_id is null, and
        household_size starts at 0.
        """
        policy = create_state_policy()
        res = api.create_household(
            create_household_payload(state_code=policy["state_code"]),
            intake_worker_headers,
        )
        data = validate_success(res, expected_status=201)
        assert_household(data)
        assert data.get("head_applicant_id") is None, (
            "head_applicant_id must be null before any applicants are "
            f"added per PRD §3.1, got {data.get('head_applicant_id')!r}"
        )
        assert data["household_size"] == 0

    def test_create_household_with_unknown_state_code_404(
            self, api, intake_worker_headers):
        """PRD §3.1: "The household carries a state_code that must
        reference an existing StatePolicy."
        PRD §2.5: dangling FK references → ERR_NOT_FOUND.

        Claim: POST /households with unknown state_code → ERR_NOT_FOUND.
        """
        res = api.create_household(
            create_household_payload(state_code="ZZ"),
            intake_worker_headers,
        )
        validate_error(res, "ERR_NOT_FOUND")

    def test_first_non_excluded_applicant_sets_head_applicant_id(
            self, api, intake_worker_headers):
        """PRD §3.1: "The household's head_applicant_id is initially
        null and is filled in automatically when the first Applicant
        with a non-EXCLUDED dependent_status is added to the household;
        subsequent applicants do not displace the head."

        Claim: adding a PRIMARY applicant sets head_applicant_id; a
        second applicant does not change it.
        """
        policy = create_state_policy()
        household = create_household(state_code=policy["state_code"])
        a1 = add_applicant(
            household=household, dependent_status="PRIMARY",
        )
        h_after_a1 = get_household(household["id"])
        assert h_after_a1["head_applicant_id"] == a1["id"], (
            "head_applicant_id must be set to the first non-EXCLUDED "
            f"applicant per PRD §3.1; expected {a1['id']!r}, got "
            f"{h_after_a1['head_applicant_id']!r}"
        )
        a2 = add_applicant(
            household=household, dependent_status="SPOUSE",
        )
        h_after_a2 = get_household(household["id"])
        assert h_after_a2["head_applicant_id"] == a1["id"], (
            "head_applicant_id must NOT be displaced by subsequent "
            "applicants per PRD §3.1"
        )

    def test_first_excluded_applicant_does_not_set_head(
            self, api, intake_worker_headers):
        """PRD §3.1: "head_applicant_id is initially null and is filled
        in automatically when the first Applicant with a non-EXCLUDED
        dependent_status is added to the household."

        Claim: adding an EXCLUDED-only applicant leaves head_applicant_id
        null.
        """
        policy = create_state_policy()
        household = create_household(state_code=policy["state_code"])
        add_applicant(
            household=household, dependent_status="EXCLUDED",
        )
        h = get_household(household["id"])
        assert h["head_applicant_id"] is None, (
            "head_applicant_id must remain null when only an EXCLUDED "
            "applicant exists per PRD §3.1"
        )


# ===========================================================================
# Applicant — PRD §3.1
# ===========================================================================
class TestApplicantIntake:

    def test_create_applicant_returns_201_and_shape(
            self, api, intake_worker_headers):
        """PRD §3.1: applicants carry full_name, date_of_birth,
        dependent_status, is_disabled (default false), is_pregnant
        (default false).

        Claim: a created applicant returns 201 with the documented
        fields and defaults.
        """
        policy = create_state_policy()
        household = create_household(state_code=policy["state_code"])
        a = add_applicant(
            household=household, dependent_status="PRIMARY",
        )
        assert_applicant(a)
        assert a["is_disabled"] is False, (
            "is_disabled defaults to false per PRD §3.1"
        )
        assert a["is_pregnant"] is False, (
            "is_pregnant defaults to false per PRD §3.1"
        )

    def test_excluded_applicant_does_not_increment_household_size(
            self, api, intake_worker_headers):
        """PRD §3.1: "EXCLUDED applicants do not contribute to
        household_size or total_magi."

        Claim: adding a PRIMARY then EXCLUDED applicant leaves
        household_size at 1.
        """
        _sp, household, _ = setup_basic_household(applicants=[
            {"dependent_status": "PRIMARY"},
            {"dependent_status": "EXCLUDED"},
        ])
        h = get_household(household["id"])
        assert h["household_size"] == 1, (
            "household_size must count only non-EXCLUDED applicants "
            f"per PRD §3.1; got household_size={h['household_size']}"
        )

    def test_pregnant_increases_effective_size(
            self, api, intake_worker_headers):
        """PRD §3.1: "is_pregnant flag (defaulting to false; a true
        value increases the effective household size by one per
        pregnancy when the FPL denominator is computed)."
        PRD §3.2: "an effective household size is computed as the count
        of Applicants whose dependent_status is not EXCLUDED, plus the
        count of applicants whose is_pregnant flag is true."

        Claim: a single PRIMARY+pregnant applicant produces an
        fpl_threshold_amount of fpl_base + 1*fpl_per_member (size==2).
        """
        _sp, household, _ = setup_basic_household(
            state_policy_kwargs={
                "fpl_base_amount": 15_000.00,
                "fpl_per_member_amount": 5_000.00,
            },
            applicants=[
                {"dependent_status": "PRIMARY", "is_pregnant": True},
            ],
        )
        h = get_household(household["id"])
        assert float(h["fpl_threshold_amount"]) == pytest.approx(20_000.00), (
            "effective size with one PRIMARY+pregnant must be 2 per PRD "
            f"§3.2; expected fpl_threshold=20000.00, got "
            f"{h['fpl_threshold_amount']}"
        )


# ===========================================================================
# IncomeRecord — PRD §3.1 (append-only)
# ===========================================================================
class TestIncomeRecord:

    def test_create_income_record_returns_201_and_shape(
            self, api, intake_worker_headers):
        """PRD §3.1: IncomeRecord carries source_type, gross_amount,
        frequency.
        PRD §2.4: "IncomeRecord and AssetRecord carry only id and
        created_at; they have no updated_at and no version because they
        are immutable once written."

        Claim: a successful income create returns 201 and an append-only
        shape.
        """
        _sp, household, [applicant] = setup_basic_household()
        rec = add_income(
            household=household, applicant=applicant,
            source_type="WAGES", gross_amount=1000.00, frequency="MONTHLY",
        )
        assert_income_record(rec)


# ===========================================================================
# AssetRecord — PRD §3.1 (append-only)
# ===========================================================================
class TestAssetRecord:

    def test_create_asset_record_returns_201_and_shape(
            self, api, intake_worker_headers):
        """PRD §3.1: AssetRecord carries asset_type and market_value.
        PRD §2.4: "IncomeRecord and AssetRecord carry only id and
        created_at."

        Claim: a successful asset create returns 201 and an append-only
        shape.
        """
        _sp, household, [applicant] = setup_basic_household()
        rec = add_asset(
            household=household, applicant=applicant,
            asset_type="CHECKING", market_value=5000.00,
        )
        assert_asset_record(rec)

    def test_asset_exempt_under_federal_flags(
            self, api, intake_worker_headers):
        """PRD §3.1: "the system tags each asset record with two
        computed flags, exempt_under_federal (true if the asset type is
        PRIMARY_RESIDENCE, RETIREMENT, or LIFE_INSURANCE, the fixed
        federal exempt set)."

        Claim: PRIMARY_RESIDENCE has exempt_under_federal=true; CHECKING
        has exempt_under_federal=false.
        """
        _sp, household, [applicant] = setup_basic_household()
        residence = add_asset(
            household=household, applicant=applicant,
            asset_type="PRIMARY_RESIDENCE", market_value=100_000.00,
        )
        checking = add_asset(
            household=household, applicant=applicant,
            asset_type="CHECKING", market_value=5000.00,
        )
        assert residence["exempt_under_federal"] is True, (
            "PRIMARY_RESIDENCE must have exempt_under_federal=true per "
            f"PRD §3.1; got {residence['exempt_under_federal']}"
        )
        assert checking["exempt_under_federal"] is False, (
            "CHECKING must have exempt_under_federal=false per PRD §3.1"
        )

    def test_asset_exempt_under_state_flags(
            self, api, intake_worker_headers):
        """PRD §3.1: "exempt_under_state (true iff the asset type
        appears in the household's StatePolicy.state_exempt_asset_types)."

        Claim: VEHICLE has exempt_under_state=true when the state
        exempts VEHICLE, and false otherwise.
        """
        _sp, household, [applicant] = setup_basic_household(
            state_policy_kwargs={
                "state_exempt_asset_types": ["VEHICLE"],
            },
        )
        vehicle = add_asset(
            household=household, applicant=applicant,
            asset_type="VEHICLE", market_value=20_000.00,
        )
        checking = add_asset(
            household=household, applicant=applicant,
            asset_type="CHECKING", market_value=5_000.00,
        )
        assert vehicle["exempt_under_state"] is True, (
            "VEHICLE must have exempt_under_state=true when state "
            f"exempts VEHICLE per PRD §3.1; got "
            f"{vehicle['exempt_under_state']}"
        )
        assert checking["exempt_under_state"] is False, (
            "CHECKING must have exempt_under_state=false when state "
            "does not exempt CHECKING per PRD §3.1"
        )
