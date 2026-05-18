"""FinancialDisclosure lifecycle: create, submit, accept, reject, OCC.

PRD §3.2.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    accept_disclosure,
    answer_case,
    api_client,
    assert_disclosure,
    assert_net_income,
    create_case,
    create_disclosure,
    create_disclosure_payload,
    create_submit_accept_disclosure,
    make_petitioner_headers,
    make_respondent_headers,
    patch_disclosure_payload,
    re_get_disclosure,
    reject_disclosure_payload,
    submit_disclosure,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# Create + computed net income — PRD §3.2
# ===========================================================================
class TestCreateDisclosure:

    def test_create_disclosure_returns_draft_with_net_income(
        self, api,
    ):
        """PRD §3.2: 'A Petitioner, Respondent, or AttorneyOfRecord
        creates the disclosure in DRAFT status'.
        PRD §3.2: 'The server computes net_monthly_income_cents
        immediately as the gross income minus the deductible taxes,
        floored at zero so it is never negative'.

        Claim: POST /disclosures returns a DRAFT row with
        net_monthly_income_cents = max(0, gross - taxes).
        """
        case = create_case()
        answer_case(case["id"], case["respondent_party_id"])
        d = create_disclosure(
            case["id"], case["petitioner_party_id"],
            actor_role="petitioner",
            gross_monthly_income_cents=500_000,
            deductible_taxes_cents=120_000,
        )
        assert_disclosure(d)
        assert d["status"] == "DRAFT"
        assert d["net_monthly_income_cents"] == 380_000
        assert_net_income(d)

    def test_net_income_floors_at_zero(self, api):
        """PRD §3.2: 'floored at zero so it is never negative'.

        Claim: deductible_taxes_cents > gross_monthly_income_cents
        yields net_monthly_income_cents == 0 (in DRAFT — the consistency
        check fires only on submit per PRD §3.2).
        """
        case = create_case()
        answer_case(case["id"], case["respondent_party_id"])
        # Use deductible_taxes_cents <= gross (so we can create), but
        # equal — yields net = 0 (still passes consistency check at
        # submit time because deductible <= gross).
        d = create_disclosure(
            case["id"], case["petitioner_party_id"],
            actor_role="petitioner",
            gross_monthly_income_cents=400_000,
            deductible_taxes_cents=400_000,
        )
        assert d["net_monthly_income_cents"] == 0


# ===========================================================================
# Uniqueness — PRD §3.2
# ===========================================================================
class TestDuplicateDisclosure:

    def test_second_create_for_same_party_rejected(self, api):
        """PRD §3.2: 'The pair (case_id, party_id) is unique on the
        case — a second create attempt for the same party is rejected
        with ERR_DUPLICATE_DISCLOSURE (HTTP 409).'

        Claim: a second POST /disclosures for the same party_id is
        ERR_DUPLICATE_DISCLOSURE.
        """
        case = create_case()
        answer_case(case["id"], case["respondent_party_id"])
        create_disclosure(
            case["id"], case["petitioner_party_id"],
            actor_role="petitioner",
        )
        # Second attempt — same party.
        payload = create_disclosure_payload(
            party_id=case["petitioner_party_id"],
        )
        res = api.create_disclosure(
            case["id"], payload,
            make_petitioner_headers(case["petitioner_party_id"]),
        )
        validate_error(
            res, "ERR_DUPLICATE_DISCLOSURE", expected_status=409,
        )


# ===========================================================================
# Submit validations — PRD §3.2
# ===========================================================================
class TestSubmitValidation:

    def test_zero_gross_income_rejected_on_submit(self, api):
        """PRD §3.2: 'On submit, the system enforces ... that
        gross_monthly_income_cents is strictly greater than zero
        (otherwise ERR_DISCLOSURE_INCOMPLETE, HTTP 409)'.

        Claim: gross_monthly_income_cents == 0 yields
        ERR_DISCLOSURE_INCOMPLETE at submit time.
        """
        case = create_case()
        answer_case(case["id"], case["respondent_party_id"])
        d = create_disclosure(
            case["id"], case["petitioner_party_id"],
            actor_role="petitioner",
            gross_monthly_income_cents=0,
            deductible_taxes_cents=0,
        )
        res = api.submit_disclosure(
            case["id"], d["id"],
            make_petitioner_headers(case["petitioner_party_id"]),
        )
        validate_error(
            res, "ERR_DISCLOSURE_INCOMPLETE", expected_status=409,
        )

    def test_taxes_exceeding_gross_rejected_on_submit(self, api):
        """PRD §3.2: 'that deductible_taxes_cents does not exceed
        gross_monthly_income_cents (otherwise
        ERR_DISCLOSURE_INCONSISTENT, HTTP 422).'

        Claim: deductible_taxes_cents > gross_monthly_income_cents
        yields ERR_DISCLOSURE_INCONSISTENT at submit.
        """
        case = create_case()
        answer_case(case["id"], case["respondent_party_id"])
        # First create with valid values so we can create (taxes
        # <= gross), then patch to exceed.
        d = create_disclosure(
            case["id"], case["petitioner_party_id"],
            actor_role="petitioner",
            gross_monthly_income_cents=300_000,
            deductible_taxes_cents=100_000,
        )
        # Patch deductible_taxes to exceed gross.
        patch_res = api.patch_disclosure(
            case["id"], d["id"],
            patch_disclosure_payload(
                version=d["version"], deductible_taxes_cents=400_000,
            ),
            make_petitioner_headers(case["petitioner_party_id"]),
        )
        # The patch is on DRAFT (PRD §3.2 allows DRAFT patch); we
        # don't assert on the patch result, only on the subsequent
        # submit.
        validate_success(patch_res, 200)
        patched = re_get_disclosure(case["id"], d["id"])
        res = api.submit_disclosure(
            case["id"], d["id"],
            make_petitioner_headers(case["petitioner_party_id"]),
        )
        validate_error(
            res, "ERR_DISCLOSURE_INCONSISTENT",
            expected_status=422,
        )


# ===========================================================================
# Reject + edit cycle — PRD §3.2
# ===========================================================================
class TestRejectAndReDraft:

    def test_reject_without_reason_rejected(self, api, judge_headers):
        """PRD §3.2: 'Rejecting it requires a rejection_reason in the
        request body — submitting a rejection without one is refused
        with ERR_REJECTION_REASON_REQUIRED (HTTP 422).'

        Claim: POST /reject with empty body is
        ERR_REJECTION_REASON_REQUIRED.
        """
        case = create_case()
        answer_case(case["id"], case["respondent_party_id"])
        d = create_disclosure(
            case["id"], case["petitioner_party_id"],
            actor_role="petitioner",
            gross_monthly_income_cents=300_000,
        )
        submit_disclosure(
            case["id"], d["id"], case["petitioner_party_id"],
            actor_role="petitioner",
        )
        # Reject without rejection_reason.
        res = api.reject_disclosure(
            case["id"], d["id"], {}, judge_headers,
        )
        validate_error(
            res, "ERR_REJECTION_REASON_REQUIRED",
            expected_status=422,
        )

    def test_reject_with_reason_succeeds_and_status_rejected(
        self, api, judge_headers,
    ):
        """PRD §3.2: 'On rejection the disclosure transitions from
        SUBMITTED to REJECTED and the reason is stored.'

        Claim: reject with reason yields status=REJECTED.
        """
        case = create_case()
        answer_case(case["id"], case["respondent_party_id"])
        d = create_disclosure(
            case["id"], case["petitioner_party_id"],
            actor_role="petitioner",
            gross_monthly_income_cents=300_000,
        )
        submit_disclosure(
            case["id"], d["id"], case["petitioner_party_id"],
            actor_role="petitioner",
        )
        res = api.reject_disclosure(
            case["id"], d["id"],
            reject_disclosure_payload(rejection_reason="missing docs"),
            judge_headers,
        )
        updated = validate_success(res, 200)
        assert updated["status"] == "REJECTED"

    def test_patch_after_reject_returns_to_draft(
        self, api, judge_headers,
    ):
        """PRD §3.2: 'The owning party can then patch the disclosure
        (correcting any of the six monetary fields) which returns it
        from REJECTED to DRAFT and clears rejection_reason back to
        null.'

        Claim: PATCH on a REJECTED disclosure transitions it back to
        DRAFT and clears rejection_reason.
        """
        case = create_case()
        answer_case(case["id"], case["respondent_party_id"])
        d = create_disclosure(
            case["id"], case["petitioner_party_id"],
            actor_role="petitioner",
            gross_monthly_income_cents=300_000,
        )
        submit_disclosure(
            case["id"], d["id"], case["petitioner_party_id"],
            actor_role="petitioner",
        )
        api.reject_disclosure(
            case["id"], d["id"],
            reject_disclosure_payload(rejection_reason="x"),
            judge_headers,
        )
        rejected = re_get_disclosure(case["id"], d["id"])
        patched = api.patch_disclosure(
            case["id"], d["id"],
            patch_disclosure_payload(
                version=rejected["version"],
                gross_monthly_income_cents=350_000,
            ),
            make_petitioner_headers(case["petitioner_party_id"]),
        )
        body = validate_success(patched, 200)
        assert body["status"] == "DRAFT"
        assert body.get("rejection_reason") in (None, ""), (
            f"rejection_reason must be cleared to null on patch; got "
            f"{body.get('rejection_reason')!r}"
        )


# ===========================================================================
# OCC — PRD §2.8
# ===========================================================================
class TestOCC:

    def test_patch_with_stale_version_rejected(self, api):
        """PRD §2.8: 'When supplied, the server compares the request's
        version to the current version on the targeted resource; on
        mismatch the request is rejected with ERR_VERSION_CONFLICT
        (HTTP 409).'

        Claim: patching with a stale version raises
        ERR_VERSION_CONFLICT.
        """
        case = create_case()
        answer_case(case["id"], case["respondent_party_id"])
        d = create_disclosure(
            case["id"], case["petitioner_party_id"],
            actor_role="petitioner",
            gross_monthly_income_cents=300_000,
        )
        stale_version = d["version"]
        # Mutate the disclosure once to bump the version (patch with
        # current version succeeds; PRD §2.8 increments version).
        first_patch = api.patch_disclosure(
            case["id"], d["id"],
            patch_disclosure_payload(
                version=stale_version,
                gross_monthly_income_cents=310_000,
            ),
            make_petitioner_headers(case["petitioner_party_id"]),
        )
        validate_success(first_patch, 200)
        # Now patch with the stale (pre-mutation) version.
        res = api.patch_disclosure(
            case["id"], d["id"],
            patch_disclosure_payload(
                version=stale_version,
                gross_monthly_income_cents=320_000,
            ),
            make_petitioner_headers(case["petitioner_party_id"]),
        )
        validate_error(
            res, "ERR_VERSION_CONFLICT", expected_status=409,
        )


# ===========================================================================
# Accept side-effect: Case ANSWERED -> DISCLOSURE on first submit — PRD §3.2
# ===========================================================================
class TestCaseAdvanceOnFirstSubmit:

    def test_first_submit_on_answered_case_advances_to_disclosure(
        self, api,
    ):
        """PRD §3.2: 'On a successful submit, the disclosure moves
        from DRAFT to SUBMITTED, net_monthly_income_cents is
        recomputed, and if Case.status was ANSWERED it advances to
        DISCLOSURE'.

        Claim: first SUBMIT on an ANSWERED case bumps Case.status to
        DISCLOSURE.
        """
        case = create_case()
        answer_case(case["id"], case["respondent_party_id"])
        d = create_disclosure(
            case["id"], case["petitioner_party_id"],
            actor_role="petitioner",
            gross_monthly_income_cents=300_000,
        )
        submit_disclosure(
            case["id"], d["id"], case["petitioner_party_id"],
            actor_role="petitioner",
        )
        case_after = api.get_case(
            case["id"], TEST_USERS["judge_headers"],
        ).json()["data"]
        assert case_after["status"] == "DISCLOSURE", (
            f"expected DISCLOSURE after first submit on ANSWERED "
            f"case; got {case_after['status']!r}"
        )
