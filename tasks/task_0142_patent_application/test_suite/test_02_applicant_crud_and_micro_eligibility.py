"""Applicant CRUD, MICRO entity eligibility, and risk score / SUSPEND.

Covers PRD §3.1 in full.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    MICRO_HUGE_INCOME_CENTS,
    MICRO_HUGE_PRIOR_FILINGS_COUNT,
    MICRO_SAFE_INCOME_CENTS,
    MICRO_SAFE_PRIOR_FILINGS_COUNT,
    assert_applicant,
    create_applicant,
    create_applicant_payload,
    get_applicant,
    patch_applicant_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# Applicant creation (PRD §3.1)
# ===========================================================================
class TestApplicantCreate:

    def test_create_large_applicant_succeeds(self, api, uspto_admin_headers):
        """PRD §3.1: "registers by supplying the applicant's legal name
        and the USPTO-recognised entity-size classification entity_size,
        which must be one of LARGE, SMALL, or MICRO."
        """
        res = api.create_applicant(
            create_applicant_payload(name="Big Co", entity_size="LARGE"),
            uspto_admin_headers,
        )
        data = validate_success(res, 201)
        assert_applicant(data)
        assert data["entity_size"] == "LARGE"
        assert data["status"] == "ACTIVE", (
            "PRD §3.1: \"A newly created applicant's lifecycle field status defaults to ACTIVE.\""
        )

    def test_create_small_applicant_succeeds(self, api, uspto_admin_headers):
        """PRD §3.1 entity_size in {LARGE, SMALL, MICRO}."""
        res = api.create_applicant(
            create_applicant_payload(entity_size="SMALL"), uspto_admin_headers,
        )
        data = validate_success(res, 201)
        assert data["entity_size"] == "SMALL"
        assert data["status"] == "ACTIVE"

    def test_create_micro_applicant_with_caps_succeeds(self, api, uspto_admin_headers):
        """PRD §3.1: "Two additional fields, gross_income_cents and
        prior_filings_count, are optional in general but become
        mandatory when entity_size is MICRO: the registration is
        rejected with ERR_MICRO_INELIGIBLE unless both income and
        prior-filings figures are present and within the published
        caps."

        Claim: MICRO with safe (within-cap) values is accepted.
        """
        res = api.create_applicant(
            create_applicant_payload(
                entity_size="MICRO",
                gross_income_cents=MICRO_SAFE_INCOME_CENTS,
                prior_filings_count=MICRO_SAFE_PRIOR_FILINGS_COUNT,
            ),
            uspto_admin_headers,
        )
        data = validate_success(res, 201)
        assert data["entity_size"] == "MICRO"
        assert data["status"] == "ACTIVE"

    def test_create_micro_applicant_huge_income_rejected(self, api, uspto_admin_headers):
        """PRD §3.1: "the registration is rejected with
        ERR_MICRO_INELIGIBLE unless both income and prior-filings
        figures are present and within the published caps."
        """
        res = api.create_applicant(
            create_applicant_payload(
                entity_size="MICRO",
                gross_income_cents=MICRO_HUGE_INCOME_CENTS,
                prior_filings_count=MICRO_SAFE_PRIOR_FILINGS_COUNT,
            ),
            uspto_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_MICRO_INELIGIBLE.value)

    def test_create_micro_applicant_huge_prior_filings_rejected(self, api, uspto_admin_headers):
        """PRD §3.1: "the registration is rejected with
        ERR_MICRO_INELIGIBLE unless both income and prior-filings
        figures are present and within the published caps."
        """
        res = api.create_applicant(
            create_applicant_payload(
                entity_size="MICRO",
                gross_income_cents=MICRO_SAFE_INCOME_CENTS,
                prior_filings_count=MICRO_HUGE_PRIOR_FILINGS_COUNT,
            ),
            uspto_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_MICRO_INELIGIBLE.value)


# ===========================================================================
# Applicant update (PRD §3.1)
# ===========================================================================
class TestApplicantPatch:

    def test_patch_applicant_name_succeeds(self, api, uspto_admin_headers):
        """PRD §3.1: "the same admin-driven applicant update also
        accepts a name, an entity_size, a gross_income_cents, and a
        prior_filings_count, optionally paired with a version for
        concurrency control."

        Claim: PATCH /applicants/{id} accepts a name update and bumps
        version.
        """
        a = create_applicant(entity_size="SMALL")
        res = api.patch_applicant(
            a["id"], patch_applicant_payload(name="New Name"), uspto_admin_headers,
        )
        data = validate_success(res, 200)
        assert data["name"] == "New Name"
        assert data["version"] > a["version"]

    def test_patch_to_micro_with_huge_income_rejected(self, api, uspto_admin_headers):
        """PRD §3.1: "the registration is rejected with
        ERR_MICRO_INELIGIBLE unless both income and prior-filings
        figures are present and within the published caps."

        Claim: applies to PATCH as well as POST per PRD §3.1 (the same
        admin-driven applicant update also accepts entity_size and the
        MICRO eligibility precondition is enforced).
        """
        a = create_applicant(entity_size="SMALL")
        res = api.patch_applicant(
            a["id"],
            patch_applicant_payload(
                entity_size="MICRO",
                gross_income_cents=MICRO_HUGE_INCOME_CENTS,
                prior_filings_count=MICRO_SAFE_PRIOR_FILINGS_COUNT,
            ),
            uspto_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_MICRO_INELIGIBLE.value)

    def test_patch_with_stale_version_rejected(self, api, uspto_admin_headers):
        """PRD §2.5: "if a version value is supplied, it must equal the
        entity's current version exactly, and any other value causes
        the request to be rejected with ERR_VERSION_CONFLICT (HTTP
        409)."
        """
        a = create_applicant(entity_size="SMALL")
        v0 = a["version"]
        first = api.patch_applicant(
            a["id"], patch_applicant_payload(name="N1", version=v0), uspto_admin_headers,
        )
        validate_success(first, 200)
        res = api.patch_applicant(
            a["id"], patch_applicant_payload(name="N2", version=v0), uspto_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_VERSION_CONFLICT.value)

    def test_patch_without_version_skips_occ(self, api, uspto_admin_headers):
        """PRD §2.5: "if a version value is omitted from the request
        body, no concurrency check is performed and the mutation
        proceeds against whatever the current row holds".
        """
        a = create_applicant(entity_size="SMALL")
        res = api.patch_applicant(
            a["id"], patch_applicant_payload(name="N1"), uspto_admin_headers,
        )
        data = validate_success(res, 200)
        assert data["version"] > a["version"]


# ===========================================================================
# Risk score & SUSPEND (PRD §3.1)
# ===========================================================================
class TestApplicantRiskScore:

    def test_applicant_risk_score_zero_on_fresh_applicant(self, api, uspto_admin_headers):
        """PRD §3.1: "The weighted sum is rounded half-up to an integer
        and then clamped to the interval from 0 to 100 inclusive — even
        a portfolio with many lapses can never report a score above
        100."

        Claim: a fresh applicant with no patents has risk score 0 and
        status ACTIVE.
        """
        a = create_applicant(entity_size="SMALL")
        res = api.get_applicant(a["id"], uspto_admin_headers)
        data = validate_success(res, 200)
        assert data.get("applicant_risk_score") == 0
        assert data["status"] == "ACTIVE"

    def test_applicant_risk_score_includes_pending_office_action(self, api, uspto_admin_headers):
        """PRD §3.1: "each OfficeAction whose owning Application
        belongs to this applicant and whose status is PENDING
        contributes a weight of 5 points."
        """
        from test_helpers import setup_office_action_pending
        applicant, app, oa = setup_office_action_pending(entity_size="SMALL")
        res = api.get_applicant(applicant["id"], uspto_admin_headers)
        data = validate_success(res, 200)
        # One PENDING OA -> 5 weighted points (well under the
        # SUSPEND threshold of 75).
        assert data["applicant_risk_score"] == 5, (
            f"PRD §3.1: PENDING OA contributes 5 points; got "
            f"{data['applicant_risk_score']!r}"
        )
        assert data["status"] == "ACTIVE"
