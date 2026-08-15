"""Intake assessment lifecycle: submit/verify/return/revise, banding, risk tiers."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_client,
    create_client_payload,
    create_coordinator,
    create_draft_assessment,
    register_client,
    submit_assessment,
    validate_error,
    validate_success,
)

ANON = TEST_USERS["anonymous_headers"]


def _submit_with_income(coord_headers, alias, **assessment_overrides):
    """Register a client and drive one assessment to SUBMITTED. Returns
    (client, submitted_assessment)."""
    client = register_client(**create_client_payload(alias_name=alias))
    assessment = create_draft_assessment(client["id"], coord_headers, **assessment_overrides)
    submitted = submit_assessment(client["id"], assessment["id"], coord_headers)
    return client, submitted


class TestEligibilityBanding:
    """Band chosen from the household-keyed baseline table with tiered ratio
    cutoffs and the HOMELESS override (PRD §3.2)."""

    def test_band_boundary_straddles_full_and_partial_by_one_hundred_cents(self, api):
        """PRD §3.2: "The baseline is 125,500 cents monthly for a household of
        one ... Otherwise a ratio of at most 1.30 bands `FULL`, a ratio above
        1.30 but at most 2.00 bands `PARTIAL`, and anything above 2.00 bands
        `INELIGIBLE`."
        PRD §2.7: "The intake `income_ratio` is a ratio rounded half-up to
        exactly four decimal places, and eligibility-band comparisons against
        it are inclusive of the band boundaries."

        Design: Difficulty/combinatorial_formula/eligibility_band_tiered_table_with_homeless_override
        """
        _, coord = create_coordinator()
        _, a_full = _submit_with_income(
            coord, "aa", household_size=1, monthly_income_cents=163100,
            housing_status="STABLE", food_insecurity_score=0,
        )
        _, a_partial = _submit_with_income(
            coord, "cc", household_size=1, monthly_income_cents=163200,
            housing_status="STABLE", food_insecurity_score=0,
        )
        assert a_full["income_ratio"] == pytest.approx(1.2996, abs=1e-9), (
            f"163100/125500 must round half-up to 1.2996, got {a_full['income_ratio']}"
        )
        assert a_full["eligibility_band"] == "FULL", "1.2996 <= 1.30 bands FULL"
        assert a_partial["income_ratio"] == pytest.approx(1.3004, abs=1e-9), (
            f"163200/125500 must round half-up to 1.3004, got {a_partial['income_ratio']}"
        )
        assert a_partial["eligibility_band"] == "PARTIAL", (
            "100 cents of income pushes the ratio just outside the FULL band"
        )

    def test_homeless_override_bands_full_regardless_of_ratio(self, api):
        """PRD §3.2: "A household whose `housing_status` is `HOMELESS` is
        banded `FULL` unconditionally, regardless of ratio."

        Design: Difficulty/combinatorial_formula/eligibility_band_tiered_table_with_homeless_override
        """
        _, coord = create_coordinator()
        _, assessment = _submit_with_income(
            coord, "bb", household_size=1, monthly_income_cents=900000,
            housing_status="HOMELESS", food_insecurity_score=6,
        )
        assert assessment["income_ratio"] == pytest.approx(7.1713, abs=1e-9)
        assert assessment["eligibility_band"] == "FULL", (
            "HOMELESS bands FULL unconditionally even at ratio 7.1713"
        )


def test_double_submit_rejected_and_frozen_values_unchanged(api):
    """PRD §3.2: "Submitting moves an assessment from `DRAFT` to `SUBMITTED` —
    a submit from any other state is rejected with
    `ERR_ASSESSMENT_NOT_EDITABLE`."
    PRD §3.2: "the assessment's `income_ratio` and `eligibility_band` are
    computed and frozen on the record".

    Design: Corner/state_machines/assessment_double_submit_rejected
    """
    _, coord = create_coordinator()
    client, submitted = _submit_with_income(
        coord, "ds", household_size=1, monthly_income_cents=163100,
        housing_status="STABLE", food_insecurity_score=0,
    )
    res = api.submit_assessment(client["id"], submitted["id"], coord)
    validate_error(res, ApiErrorId.ERR_ASSESSMENT_NOT_EDITABLE, expected_status=409)

    listing = validate_success(
        api.list_assessments(coord, params={"client_id": client["id"]}), 200
    )
    row = listing[0]
    assert row["status"] == "SUBMITTED"
    assert row["eligibility_band"] == "FULL"
    assert row["income_ratio"] == pytest.approx(1.2996, abs=1e-9), (
        "a rejected re-submit must not re-fire the freezing computation"
    )


def test_verify_returned_assessment_rejected(api):
    """PRD §3.2: "Only an `IntakeCoordinator` may verify, the assessment must
    be `SUBMITTED` (else `ERR_ASSESSMENT_NOT_EDITABLE`) ..."
    PRD §3.2: "Returning, by an `IntakeCoordinator`, moves a `SUBMITTED`
    assessment to `RETURNED` and records the coordinator's `return_notes` —
    a field that stays null unless the assessment is returned."

    Design: Corner/state_machines/verify_returned_assessment_rejected
    """
    _, coord = create_coordinator()
    client, submitted = _submit_with_income(
        coord, "vr", household_size=2, monthly_income_cents=100000,
        housing_status="COST_BURDENED", dependents_under_18=1,
        food_insecurity_score=2,
    )
    returned = validate_success(
        api.return_assessment(
            client["id"], submitted["id"], {"return_notes": "missing income proof"}, coord
        ),
        200,
    )
    assert returned["status"] == "RETURNED"

    res = api.verify_assessment(
        client["id"], submitted["id"],
        {"expected_client_version": client["version"]}, coord,
    )
    validate_error(res, ApiErrorId.ERR_ASSESSMENT_NOT_EDITABLE, expected_status=409)

    after = validate_success(api.get_assessment(submitted["id"], coord), 200)
    assert after["status"] == "RETURNED"
    assert after["return_notes"] == "missing income proof"


def test_revision_loop_return_to_draft_to_verified(api):
    """PRD §3.2: "Revising, by the client or an `IntakeCoordinator`, reopens a
    `RETURNED` assessment to `DRAFT`; any of the draft's payload fields
    supplied with the revision overwrite the corresponding fields in place,
    and the previously frozen `income_ratio` and `eligibility_band` are
    cleared until the next submit."
    PRD §3.2: "A successful verification stamps `verified_at` with the logical
    now, records the acting coordinator's staff id in `verified_by`, and sets
    `expires_at` exactly 365 days after verification ... When the verified
    assessment is the client's first, the client flips automatically from
    `INTAKE_PENDING` to `ACTIVE`."

    Design: Corner/state_machines/assessment_revision_loop_return_to_draft_to_verified
    """
    coord_staff, coord = create_coordinator()
    client, submitted = _submit_with_income(
        coord, "rl", household_size=2, monthly_income_cents=100000,
        housing_status="COST_BURDENED", dependents_under_18=1,
        food_insecurity_score=2,
    )
    validate_success(
        api.return_assessment(
            client["id"], submitted["id"], {"return_notes": "verify household"}, coord
        ),
        200,
    )

    revised = validate_success(
        api.revise_assessment(
            client["id"], submitted["id"],
            {"household_size": 1, "dependents_under_18": 0}, coord
        ),
        200,
    )
    assert revised["status"] == "DRAFT"
    assert revised["household_size"] == 1, "revise overwrites supplied fields in place"
    assert revised["eligibility_band"] is None, "frozen band cleared until next submit"
    assert revised["income_ratio"] is None

    resubmitted = validate_success(
        api.submit_assessment(client["id"], submitted["id"], coord), 200
    )
    assert resubmitted["income_ratio"] == pytest.approx(0.7968, abs=1e-9), (
        f"100000/125500 recomputed on the revised household, got {resubmitted['income_ratio']}"
    )
    assert resubmitted["eligibility_band"] == "FULL"

    verified = validate_success(
        api.verify_assessment(
            client["id"], submitted["id"],
            {"expected_client_version": client["version"]}, coord,
        ),
        200,
    )
    assert verified["status"] == "VERIFIED"
    assert verified["verified_by"] == coord_staff["id"]
    assert verified["expires_at"] == "2027-08-01T00:00:00.000Z", (
        "verified at the 2026-08-01T00:00:00Z startup clock + 365 days"
    )

    client_after = validate_success(api.get_client(client["id"], coord), 200)
    assert client_after["status"] == "ACTIVE"


class TestRiskTierDerivation:
    def test_risk_tier_materializes_at_verification(self, api):
        """PRD §3.2: "The tier rule reads the client's single verified
        assessment, null-safe: with no verified assessment the client's
        `risk_tier` is null. A household that is `UNSTABLE` or `HOMELESS`, or
        whose `food_insecurity_score` is at least 5, tiers `CRISIS`. Failing
        that, a `COST_BURDENED` household, a food score of at least 3, or an
        `income_ratio` of at most 1.30 tiers `ELEVATED`. Everything else tiers
        `STABLE`."

        Design: Corner/calculations/risk_tier_derivation_from_verified_assessment
        """
        _, coord = create_coordinator()
        client, _, _ = create_active_client(
            coord,
            assessment_overrides=dict(
                household_size=1, monthly_income_cents=900000,
                housing_status="HOMELESS", dependents_under_18=0,
                receives_snap=False, receives_childcare_subsidy=False,
                food_insecurity_score=0, consent_confidential=True,
            ),
            client_overrides={"alias_name": "crisis"},
        )
        # Pre-verification null is observable on a second, not-yet-verified client.
        pending = register_client(**create_client_payload(alias_name="pending"))
        pending_read = validate_success(api.get_client(pending["id"], coord), 200)
        assert pending_read["risk_tier"] is None

        assert client["risk_tier"] == "CRISIS", (
            "HOMELESS dominates despite income 900000"
        )

    def test_elevated_and_stable_tiers(self, api):
        """PRD §3.2: "Failing that, a `COST_BURDENED` household, a food score
        of at least 3, or an `income_ratio` of at most 1.30 tiers `ELEVATED`.
        Everything else tiers `STABLE`."

        Design: Corner/calculations/risk_tier_derivation_from_verified_assessment
        """
        _, coord = create_coordinator()
        elevated, _, _ = create_active_client(
            coord,
            assessment_overrides=dict(
                household_size=2, monthly_income_cents=300000,
                housing_status="COST_BURDENED", dependents_under_18=1,
                receives_snap=False, receives_childcare_subsidy=False,
                food_insecurity_score=3, consent_confidential=True,
            ),
            client_overrides={"alias_name": "elev"},
        )
        stable, _, _ = create_active_client(
            coord,
            assessment_overrides=dict(
                household_size=1, monthly_income_cents=400000,
                housing_status="STABLE", dependents_under_18=0,
                receives_snap=True, receives_childcare_subsidy=False,
                food_insecurity_score=2, consent_confidential=True,
            ),
            client_overrides={"alias_name": "stable"},
        )
        assert elevated["risk_tier"] == "ELEVATED"
        assert stable["risk_tier"] == "STABLE", (
            "STABLE housing, ratio 3.1873 > 1.30, food 2 < 3"
        )
