"""Opening a BackgroundCheckOrder: Ban-the-Box, consent validity,
consent-candidate mismatch, salary-history ban, eligibility posture,
package-set validation — PRD §2.9, §3.3.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_background_check_order,
    assert_status,
    create_candidate,
    create_order_payload,
    record_consent_as_recruiter,
    record_consent_payload,
    setup_candidate_with_consent,
    upsert_jurisdiction_policy,
    validate_error,
    validate_success,
)


# ===========================================================================
# Happy path — PRD §3.3
# ===========================================================================
class TestOrderHappyPath:

    def test_open_order_initial_state(self, api, recruiter_headers):
        """PRD §3.3: "The new order's `status` is `INTAKE`, its
        `composite_decision` is `PENDING`, its `opened_by_role` is the
        calling role".
        PRD §3.3: "The order responds with HTTP 201."

        Claim: POST /fcra/orders -> 201 with status=INTAKE,
        composite_decision=PENDING.
        """
        cand, cons = setup_candidate_with_consent(
            residence_jurisdiction="CA",
        )
        payload = create_order_payload(
            candidate_id=cand["id"],
            consent_disclosure_id=cons["id"],
            stage_at_order="PRE_OFFER",
            requested_packages=["CRIMINAL", "MVR"],
        )
        resp = api.create_order(payload, recruiter_headers)
        data = validate_success(resp, expected_status=201)
        assert_background_check_order(data)
        assert data["status"] == "INTAKE"
        assert data["composite_decision"] == "PENDING"


# ===========================================================================
# Ban-the-Box — PRD §2.9
# ===========================================================================
class TestBanTheBox:
    """PRD §2.9: "A jurisdiction whose `ban_the_box_stage` is
    `POST_OFFER` forbids `PRE_OFFER` and `POST_INTERVIEW` orders; a
    jurisdiction whose gate is `POST_INTERVIEW` forbids `PRE_OFFER`
    orders; a jurisdiction whose gate is `PRE_OFFER` permits all
    three."
    """

    def test_post_offer_gate_blocks_pre_offer_order(
        self, api, recruiter_headers,
    ):
        """PRD §2.9: "A jurisdiction whose `ban_the_box_stage` is
        `POST_OFFER` forbids `PRE_OFFER` and `POST_INTERVIEW` orders".

        Claim: POST_OFFER gate + PRE_OFFER stage_at_order ->
        ERR_BAN_THE_BOX_VIOLATION.
        """
        cand, cons = setup_candidate_with_consent(
            residence_jurisdiction="CA",
            jurisdiction_kwargs={"ban_the_box_stage": "POST_OFFER"},
        )
        resp = api.create_order(
            create_order_payload(
                candidate_id=cand["id"],
                consent_disclosure_id=cons["id"],
                stage_at_order="PRE_OFFER",
                requested_packages=["CRIMINAL"],
            ),
            recruiter_headers,
        )
        validate_error(resp, ApiErrorId.ERR_BAN_THE_BOX_VIOLATION.value)

    def test_post_offer_gate_blocks_post_interview_order(
        self, api, recruiter_headers,
    ):
        """PRD §2.9: "A jurisdiction whose `ban_the_box_stage` is
        `POST_OFFER` forbids `PRE_OFFER` and `POST_INTERVIEW` orders".

        Claim: POST_OFFER gate + POST_INTERVIEW stage_at_order ->
        ERR_BAN_THE_BOX_VIOLATION.
        """
        cand, cons = setup_candidate_with_consent(
            residence_jurisdiction="CA",
            jurisdiction_kwargs={"ban_the_box_stage": "POST_OFFER"},
        )
        resp = api.create_order(
            create_order_payload(
                candidate_id=cand["id"],
                consent_disclosure_id=cons["id"],
                stage_at_order="POST_INTERVIEW",
                requested_packages=["CRIMINAL"],
            ),
            recruiter_headers,
        )
        validate_error(resp, ApiErrorId.ERR_BAN_THE_BOX_VIOLATION.value)

    def test_post_interview_gate_blocks_pre_offer_order(
        self, api, recruiter_headers,
    ):
        """PRD §2.9: "a jurisdiction whose gate is `POST_INTERVIEW`
        forbids `PRE_OFFER` orders".

        Claim: POST_INTERVIEW gate + PRE_OFFER stage_at_order ->
        ERR_BAN_THE_BOX_VIOLATION.
        """
        cand, cons = setup_candidate_with_consent(
            residence_jurisdiction="NY",
            jurisdiction_kwargs={"ban_the_box_stage": "POST_INTERVIEW"},
        )
        resp = api.create_order(
            create_order_payload(
                candidate_id=cand["id"],
                consent_disclosure_id=cons["id"],
                stage_at_order="PRE_OFFER",
                requested_packages=["CRIMINAL"],
            ),
            recruiter_headers,
        )
        validate_error(resp, ApiErrorId.ERR_BAN_THE_BOX_VIOLATION.value)

    def test_post_interview_gate_allows_post_interview_order(
        self, api, recruiter_headers,
    ):
        """PRD §2.9: "A jurisdiction whose `ban_the_box_stage` is
        `POST_OFFER` forbids `PRE_OFFER` and `POST_INTERVIEW` orders;
        a jurisdiction whose gate is `POST_INTERVIEW` forbids
        `PRE_OFFER` orders; a jurisdiction whose gate is `PRE_OFFER`
        permits all three." (i.e. POST_INTERVIEW gate permits
        POST_INTERVIEW and POST_OFFER orders.)

        Claim: POST_INTERVIEW gate + POST_INTERVIEW stage_at_order ->
        201.
        """
        cand, cons = setup_candidate_with_consent(
            residence_jurisdiction="NY",
            jurisdiction_kwargs={"ban_the_box_stage": "POST_INTERVIEW"},
        )
        resp = api.create_order(
            create_order_payload(
                candidate_id=cand["id"],
                consent_disclosure_id=cons["id"],
                stage_at_order="POST_INTERVIEW",
                requested_packages=["CRIMINAL"],
            ),
            recruiter_headers,
        )
        validate_success(resp, expected_status=201)

    def test_pre_offer_gate_permits_all_three(
        self, api, recruiter_headers,
    ):
        """PRD §2.9: "a jurisdiction whose gate is `PRE_OFFER` permits
        all three."

        Claim: PRE_OFFER gate + each stage_at_order in {PRE_OFFER,
        POST_INTERVIEW, POST_OFFER} returns 201.
        """
        for stage in ("PRE_OFFER", "POST_INTERVIEW", "POST_OFFER"):
            cand, cons = setup_candidate_with_consent(
                residence_jurisdiction="IL",
                jurisdiction_kwargs={"ban_the_box_stage": "PRE_OFFER"},
            )
            resp = api.create_order(
                create_order_payload(
                    candidate_id=cand["id"],
                    consent_disclosure_id=cons["id"],
                    stage_at_order=stage,
                    requested_packages=["CRIMINAL"],
                ),
                recruiter_headers,
            )
            validate_success(resp, expected_status=201)


# ===========================================================================
# Consent referential / validity — PRD §3.3
# ===========================================================================
class TestConsentReferential:

    def test_consent_candidate_mismatch(self, api, recruiter_headers):
        """PRD §3.3: "The supplied `consent_disclosure_id` must
        reference a `ConsentDisclosure` whose `candidate_id` matches
        the order's `candidate_id`; a mismatch is
        `ERR_CONSENT_CANDIDATE_MISMATCH` (HTTP 422)."

        Claim: order with consent from a DIFFERENT candidate ->
        ERR_CONSENT_CANDIDATE_MISMATCH.
        """
        # Two independent candidates with permissive jurisdiction so
        # Ban-the-Box and salary-history don't pre-empt the referential
        # check.
        upsert_jurisdiction_policy(code="CA")
        cand_a = create_candidate(residence_jurisdiction="CA")
        cand_b = create_candidate(residence_jurisdiction="CA")
        consent_b = record_consent_as_recruiter(candidate_id=cand_b["id"])
        # Order for cand_a but using cand_b's consent.
        resp = api.create_order(
            create_order_payload(
                candidate_id=cand_a["id"],
                consent_disclosure_id=consent_b["id"],
                stage_at_order="POST_OFFER",
                requested_packages=["CRIMINAL"],
            ),
            recruiter_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_CONSENT_CANDIDATE_MISMATCH.value,
        )

    def test_order_against_revoked_consent_rejected(
        self, api, recruiter_headers,
    ):
        """PRD §3.3: "An order creation against a missing, `SUPERSEDED`,
        or `REVOKED` consent surfaces as `ERR_CONSENT_INVALID`."

        Claim: candidate revokes consent first; subsequent open-order
        request with that consent_id -> ERR_CONSENT_INVALID.
        """
        from test_helpers import make_candidate_headers
        cand, cons = setup_candidate_with_consent(
            residence_jurisdiction="CA",
        )
        # Candidate revokes own consent.
        validate_success(
            api.revoke_consent(
                cand["id"], make_candidate_headers(cand["id"]),
            )
        )
        # Order open with the now-REVOKED consent.
        resp = api.create_order(
            create_order_payload(
                candidate_id=cand["id"],
                consent_disclosure_id=cons["id"],
                stage_at_order="POST_OFFER",
                requested_packages=["CRIMINAL"],
            ),
            recruiter_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CONSENT_INVALID.value)


# ===========================================================================
# requested_packages — PRD §3.3
# ===========================================================================
class TestPackageSetValidation:
    """PRD §3.3: "The `requested_packages` array is a non-empty list,
    without duplicates, drawn from `CRIMINAL`, `MVR`, and `EDUCATION`;
    an empty array, a duplicated entry, or an unknown package code is
    rejected with `ERR_PACKAGE_SET_INVALID` (HTTP 422)."
    """

    def test_empty_requested_packages_rejected(
        self, api, recruiter_headers,
    ):
        """PRD §3.3: "an empty array, a duplicated entry, or an unknown
        package code is rejected with `ERR_PACKAGE_SET_INVALID` (HTTP
        422)."

        Claim: requested_packages=[] -> ERR_PACKAGE_SET_INVALID.
        """
        cand, cons = setup_candidate_with_consent(
            residence_jurisdiction="CA",
        )
        resp = api.create_order(
            create_order_payload(
                candidate_id=cand["id"],
                consent_disclosure_id=cons["id"],
                stage_at_order="PRE_OFFER",
                requested_packages=[],
            ),
            recruiter_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PACKAGE_SET_INVALID.value)

    def test_duplicate_requested_packages_rejected(
        self, api, recruiter_headers,
    ):
        """PRD §3.3: "an empty array, a duplicated entry, or an unknown
        package code is rejected with `ERR_PACKAGE_SET_INVALID` (HTTP
        422)."

        Claim: requested_packages with a duplicate ->
        ERR_PACKAGE_SET_INVALID.
        """
        cand, cons = setup_candidate_with_consent(
            residence_jurisdiction="CA",
        )
        resp = api.create_order(
            create_order_payload(
                candidate_id=cand["id"],
                consent_disclosure_id=cons["id"],
                stage_at_order="PRE_OFFER",
                requested_packages=["CRIMINAL", "CRIMINAL"],
            ),
            recruiter_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PACKAGE_SET_INVALID.value)

    def test_unknown_package_rejected(self, api, recruiter_headers):
        """PRD §3.3: "an empty array, a duplicated entry, or an unknown
        package code is rejected with `ERR_PACKAGE_SET_INVALID` (HTTP
        422)."

        Claim: requested_packages with an unknown code ->
        ERR_PACKAGE_SET_INVALID.
        """
        cand, cons = setup_candidate_with_consent(
            residence_jurisdiction="CA",
        )
        resp = api.create_order(
            create_order_payload(
                candidate_id=cand["id"],
                consent_disclosure_id=cons["id"],
                stage_at_order="PRE_OFFER",
                requested_packages=["CRIMINAL", "FINGERPRINTS"],
            ),
            recruiter_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PACKAGE_SET_INVALID.value)

    def test_minimal_one_package_accepted(self, api, recruiter_headers):
        """PRD §3.3: "The `requested_packages` array is a non-empty
        list, without duplicates, drawn from `CRIMINAL`, `MVR`, and
        `EDUCATION`".

        Claim: single-element requested_packages -> 201.
        """
        cand, cons = setup_candidate_with_consent(
            residence_jurisdiction="CA",
        )
        resp = api.create_order(
            create_order_payload(
                candidate_id=cand["id"],
                consent_disclosure_id=cons["id"],
                stage_at_order="PRE_OFFER",
                requested_packages=["EDUCATION"],
            ),
            recruiter_headers,
        )
        validate_success(resp, expected_status=201)


# ===========================================================================
# Eligibility posture — PRD §3.3
# ===========================================================================
class TestCandidateNotEligible:

    def test_open_order_while_under_review_rejected(
        self, api, recruiter_headers,
    ):
        """PRD §3.3: "The candidate's current `eligibility_posture`
        must be `ELIGIBLE` — neither `UNDER_REVIEW`, `ADVERSE`, nor
        `LOCKED` — and a violation surfaces as
        `ERR_CANDIDATE_NOT_ELIGIBLE` (HTTP 422)."

        Claim: a second order opened while the first is in
        IN_VERIFICATION (posture=UNDER_REVIEW) -> ERR_CANDIDATE_NOT_ELIGIBLE.
        """
        from test_helpers import start_verification
        cand, cons = setup_candidate_with_consent(
            residence_jurisdiction="CA",
        )
        # Open first order and move it to IN_VERIFICATION.
        first = validate_success(
            api.create_order(
                create_order_payload(
                    candidate_id=cand["id"],
                    consent_disclosure_id=cons["id"],
                    stage_at_order="POST_OFFER",
                    requested_packages=["CRIMINAL"],
                ),
                recruiter_headers,
            ),
            expected_status=201,
        )
        start_verification(first["id"], recruiter_headers)
        # Record a fresh consent (the prior one is now pinned to the
        # first order; a new ACTIVE consent is required to open a
        # second order). PRD §3.2 says recording a new consent
        # supersedes the old one.
        second_consent = record_consent_as_recruiter(
            candidate_id=cand["id"],
        )
        # Second order attempt — eligibility_posture is now UNDER_REVIEW.
        resp = api.create_order(
            create_order_payload(
                candidate_id=cand["id"],
                consent_disclosure_id=second_consent["id"],
                stage_at_order="POST_OFFER",
                requested_packages=["MVR"],
            ),
            recruiter_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CANDIDATE_NOT_ELIGIBLE.value)


# ===========================================================================
# Salary History Ban on order body — PRD §2.9
# ===========================================================================
class TestSalaryHistoryBanOnOrder:

    def test_order_with_salary_history_in_banned_state(
        self, api, recruiter_headers,
    ):
        """PRD §2.9: "when the candidate's jurisdiction has
        `salary_history_ban` set to true, no request body — candidate
        creation, candidate patch, or order creation — may carry a
        `salary_history` field".

        Claim: POST /fcra/orders body with salary_history in a banned
        jurisdiction -> ERR_SALARY_HISTORY_BAN.
        """
        cand, cons = setup_candidate_with_consent(
            residence_jurisdiction="FL",
            jurisdiction_kwargs={"salary_history_ban": True},
        )
        resp = api.create_order(
            create_order_payload(
                candidate_id=cand["id"],
                consent_disclosure_id=cons["id"],
                stage_at_order="PRE_OFFER",
                requested_packages=["CRIMINAL"],
                salary_history=80_000,
            ),
            recruiter_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SALARY_HISTORY_BAN.value)
