"""Validation corner cases: listing-met needs listing_reference; child over 18
rejected; medical-decision needs at least one evidence; family-max headroom."""
import pytest
from test_helpers import (
    validate_error, validate_success, get_success_data, api_client, TEST_USERS,
    set_clock,
    create_claimant, post_work_credits_for_years, INSURED_BASELINE_YEARS,
    create_application_for_claimant, submit_application,
    setup_application_in_medical_review,
    setup_application_awarded,
    create_child_auxiliary, get_current_award,
    medical_decision_payload, create_child_auxiliary_payload,
    make_claimant_headers,
)


# =========================================================================
# Instance: medical_decision_listing_met_missing_listing_reference_returns_422
# =========================================================================

def test_listing_met_without_listing_reference_returns_422(api):
    """PRD §3.4: "a `LISTING_MET` decision must carry a non-null
    `listing_reference`; omitting it is rejected with
    `ERR_LISTING_REFERENCE_REQUIRED` (422)."

    Design: Corner/validations/medical_decision_listing_met_missing_listing_reference_returns_422
    """
    set_clock("2026-01-15T00:00:00Z")
    claimant, app = setup_application_in_medical_review(
        claimant_overrides={
            "ssn_last4": "3001",
            "full_name": "Miss Listing",
            "date_of_birth": "1980-01-01T00:00:00Z",
            "filing_state": "TX",
        },
    )
    payload = medical_decision_payload(
        decision_type="LISTING_MET",
        established_onset_date="2024-01-15T00:00:00Z",
        expected_application_version=app["version"],
        # listing_reference deliberately omitted.
    )
    res = api_client.medical_decision(app["id"], payload, TEST_USERS["dds_examiner_headers"])
    validate_error(res, "ERR_LISTING_REFERENCE_REQUIRED", expected_status=422)


# =========================================================================
# Instance: child_aux_over_18_returns_422
# =========================================================================

def test_child_auxiliary_over_age_18_returns_422(api):
    """PRD §3.8: "the child must be under 18 at the moment of creation:
    the difference between the current server time and
    `child_date_of_birth` must be strictly less than 18 years. A child who
    is 18 years old or older at creation is rejected with
    `ERR_CHILD_OVER_AGE` (422)."

    Design: Corner/validations/child_aux_over_18_returns_422
    """
    set_clock("2026-01-15T00:00:00Z")
    ctx = setup_application_awarded(
        claimant_overrides={
            "ssn_last4": "3002",
            "full_name": "Old Child Test",
            "date_of_birth": "1980-01-01T00:00:00Z",
            "filing_state": "TX",
        },
    )
    award = ctx["award"]
    # Child born 2005-01-01, NOW is 2026-01-15 → age ~21 (over 18).
    payload = create_child_auxiliary_payload(
        child_full_name="Adult Child",
        child_date_of_birth="2005-01-01T00:00:00Z",
        relationship="BIOLOGICAL",
        expected_benefit_award_version=award["version"],
    )
    res = api_client.create_child_auxiliary(award["id"], payload,
                                             TEST_USERS["benefits_admin_headers"])
    validate_error(res, "ERR_CHILD_OVER_AGE", expected_status=422)


# =========================================================================
# Instance: medical_decision_no_evidence_attached_returns_422
# =========================================================================

def test_medical_decision_with_zero_evidence_rows_returns_422(api):
    """PRD §3.4: "At least one `MedicalEvidence` record must already be
    attached to the application; an examiner who tries to decide an
    evidence-less application is rejected with `ERR_EVIDENCE_REQUIRED`."

    Design: Corner/validations/medical_decision_no_evidence_attached_returns_422
    """
    set_clock("2026-01-15T00:00:00Z")
    c = create_claimant(ssn_last4="3003", full_name="No Ev",
                        date_of_birth="1980-01-01T00:00:00Z", filing_state="TX")
    post_work_credits_for_years(c["id"], INSURED_BASELINE_YEARS)
    app = create_application_for_claimant(
        c["id"],
        alleged_onset_date="2024-01-01T00:00:00Z",
        protective_filing_date="2026-01-15T00:00:00Z",
        claim_type="SSDI_ONLY",
    )
    app_submitted = submit_application(app["id"], c["id"])
    # No evidence attached. Medical decision should be rejected.
    payload = medical_decision_payload(
        decision_type="RFC_DISABLED",
        established_onset_date="2024-01-15T00:00:00Z",
        expected_application_version=app_submitted["version"],
        rfc_score=30,
    )
    res = api_client.medical_decision(app["id"], payload, TEST_USERS["dds_examiner_headers"])
    validate_error(res, "ERR_EVIDENCE_REQUIRED", expected_status=422)


# =========================================================================
# Instance: family_max_exceeded_excluded_by_difficulty_alignment
# =========================================================================

def test_third_child_after_family_max_exhausted_returns_422(api):
    """PRD §3.8: "The headroom available for the new auxiliary is the
    family maximum minus the primary's `monthly_benefit_cents` minus the
    sum of `monthly_amount_cents` across every existing
    `ChildAuxiliaryBenefit` already attached to this award whose `status`
    is `ACTIVE` (processed in `created_at` ascending order, which is the
    same tie-break and processing order the system uses for the
    family-max accounting). If the headroom is zero or negative, the
    creation is rejected with `ERR_FAMILY_MAX_EXCEEDED` (422)."

    Design: Corner/validations/family_max_exceeded_excluded_by_difficulty_alignment
    """
    set_clock("2026-01-15T00:00:00Z")
    ctx = setup_application_awarded(
        claimant_overrides={
            "ssn_last4": "3004",
            "full_name": "Fam Max",
            "date_of_birth": "1980-01-01T00:00:00Z",
            "filing_state": "TX",
        },
        earnings_cents=4_800_000,
    )
    award = ctx["award"]
    # PIA=196092, family_max=343161, monthly_benefit=196092 → initial headroom 147069.
    # Child 1: base=98046, headroom=147069 → gets 98046. Remaining headroom = 49023.
    create_child_auxiliary(
        award["id"],
        expected_benefit_award_version=award["version"],
        child_full_name="Child 1",
        child_date_of_birth="2015-01-01T00:00:00Z",
    )
    # Child 2: base=98046, headroom=49023 → gets 49023. Remaining headroom = 0.
    award_v2 = get_current_award(award["id"])["version"]
    create_child_auxiliary(
        award["id"],
        expected_benefit_award_version=award_v2,
        child_full_name="Child 2",
        child_date_of_birth="2017-01-01T00:00:00Z",
    )
    # Child 3: headroom = 0 → rejected with ERR_FAMILY_MAX_EXCEEDED.
    award_v3 = get_current_award(award["id"])["version"]
    payload = create_child_auxiliary_payload(
        child_full_name="Child 3",
        child_date_of_birth="2019-01-01T00:00:00Z",
        relationship="BIOLOGICAL",
        expected_benefit_award_version=award_v3,
    )
    res = api_client.create_child_auxiliary(award["id"], payload,
                                             TEST_USERS["benefits_admin_headers"])
    validate_error(res, "ERR_FAMILY_MAX_EXCEEDED", expected_status=422)
