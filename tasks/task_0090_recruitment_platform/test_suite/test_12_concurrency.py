"""Concurrency-serialisation guarantees (PRD §2.9).

PRD §2.9 enumerates six races whose outcomes are explicitly named (e.g.,
"exactly one ... succeeds; the loser receives ERR_X"). We test these.
Where PRD says the loser receives a specific error_id we assert that
exact id; where the wording is "at most one succeeds" without naming the
loser's error_id, we use assert_exactly_one_succeeds.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_EPOCH,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    bind_hr_user,
    candidate_confirm_payload,
    candidate_confirm_slot,
    create_candidate,
    create_interview_round,
    create_live_posting,
    create_offer,
    create_onboarding_payload,
    create_verified_company,
    finance_approve_offer,
    forward_application,
    hm_approve_offer,
    hr_approve_offer,
    iso_utc,
    make_candidate_headers,
    make_hr_user_headers,
    mark_application_read,
    publish_round_slots,
    rescind_offer_payload,
    reset_clock_to_epoch,
    run_race,
    setup_application_at_interview_passed,
    setup_issued_offer,
    setup_accepted_offer,
    submit_application,
    submit_offer_for_approval,
    submit_posting_review,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers import api_client, create_job_posting_payload
from test_helpers.factories import accept_offer_payload


# ===========================================================================
# Two HR users approve the same offer stage simultaneously (PRD §2.9)
# ===========================================================================
class TestOfferApprovalRace:

    def test_two_hr_approvers_at_same_stage_only_one_succeeds(self, api):
        """PRD §2.9: "Two approvers attempt to approve the same `Offer`
        at the same approval stage simultaneously. Exactly one succeeds;
        the loser is rejected because the offer has already advanced out
        of that pending state, with `ERR_INVALID_STATE` (409)."

        Claim: in a race of two HR-approver calls at the PENDING_HR
        stage, exactly one returns 2xx and the loser yields
        ERR_INVALID_STATE.
        """
        bag = setup_application_at_interview_passed()
        company = bag["company"]
        hm_hr = bag["hr_user"]
        hr_a = bind_hr_user(company["id"])
        hr_b = bind_hr_user(company["id"])
        offer = create_offer(bag["application"]["id"], hm_hr["id"])
        submit_offer_for_approval(offer["id"], hm_hr["id"])
        hm_approve_offer(offer["id"], hm_hr["id"])
        # Race two HrApprover calls.
        from test_helpers import make_hr_approver_headers
        results = run_race(
            lambda: api.approve_offer(
                offer["id"], make_hr_approver_headers(hr_a["id"]),
            ),
            lambda: api.approve_offer(
                offer["id"], make_hr_approver_headers(hr_b["id"]),
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # PRD §2.9 names the loser's error_id explicitly: ERR_INVALID_STATE.
        for loser in outcome["failures"]:
            body = loser.json()
            assert body["data"]["error_id"] == ApiErrorId.ERR_INVALID_STATE.value, (
                f"Loser should receive ERR_INVALID_STATE, "
                f"got {body['data']['error_id']!r}"
            )


# ===========================================================================
# Candidate accept races HR rescind on the same ISSUED offer (PRD §2.9)
# ===========================================================================
class TestAcceptRescindRace:

    def test_accept_vs_rescind_exactly_one_succeeds(self, api):
        """PRD §2.9: "A candidate accepts and HR rescinds the same
        `ISSUED` offer simultaneously. Exactly one of the two write paths
        succeeds based on `offer_status` at write time; the loser
        receives `ERR_INVALID_STATE` (409)."

        Claim: exactly one of (accept, rescind) succeeds; the loser
        yields ERR_INVALID_STATE.
        """
        reset_clock_to_epoch()
        bag = setup_issued_offer()
        offer_id = bag["offer"]["id"]
        candidate_id = bag["candidate"]["id"]
        hr_user_id = bag["hr_user"]["id"]
        results = run_race(
            lambda: api.accept_offer(
                offer_id, make_candidate_headers(candidate_id),
                accept_offer_payload(),
            ),
            lambda: api.rescind_offer(
                offer_id, rescind_offer_payload("BUSINESS_NEED"),
                make_hr_user_headers(hr_user_id),
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        for loser in outcome["failures"]:
            body = loser.json()
            assert body["data"]["error_id"] == ApiErrorId.ERR_INVALID_STATE.value, (
                f"Loser should receive ERR_INVALID_STATE, "
                f"got {body['data']['error_id']!r}"
            )


# ===========================================================================
# Two HR users create a second Onboarding for the same Offer (PRD §2.9)
# ===========================================================================
class TestOnboardingUniquenessRace:

    def test_two_onboardings_for_same_offer_only_one_succeeds(self, api):
        """PRD §2.9: "Two HR users attempt to create a second `Onboarding`
        for the same `Offer`. At most one `Onboarding` per offer; the
        second creation is rejected with `ERR_ONBOARDING_ALREADY_EXISTS`
        (409)."

        Claim: in a race of two onboarding-creation calls for the same
        offer_id, exactly one succeeds and the loser yields
        ERR_ONBOARDING_ALREADY_EXISTS.
        """
        reset_clock_to_epoch()
        bag = setup_accepted_offer()
        offer_id = bag["offer"]["id"]
        hr_user_id = bag["hr_user"]["id"]
        start_date = iso_utc(TEST_EPOCH + timedelta(days=14))
        results = run_race(
            lambda: api.create_onboarding(
                create_onboarding_payload(
                    offer_id=offer_id, start_date=start_date,
                ),
                make_hr_user_headers(hr_user_id),
            ),
            lambda: api.create_onboarding(
                create_onboarding_payload(
                    offer_id=offer_id, start_date=start_date,
                ),
                make_hr_user_headers(hr_user_id),
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        for loser in outcome["failures"]:
            body = loser.json()
            assert body["data"]["error_id"] == ApiErrorId.ERR_ONBOARDING_ALREADY_EXISTS.value, (
                f"Loser should receive ERR_ONBOARDING_ALREADY_EXISTS, "
                f"got {body['data']['error_id']!r}"
            )


# ===========================================================================
# Two candidates confirm overlapping slots for a shared interviewer (PRD §2.9)
# ===========================================================================
class TestSharedInterviewerConfirmRace:

    def test_two_candidates_confirm_collide(self, api):
        """PRD §2.9: "Two candidates simultaneously confirm the same
        interview slot where confirming both would create overlapping
        schedules for a shared interviewer. At most one round transitions
        to `SCHEDULED`; the loser receives `ERR_INTERVIEWER_BUSY` (409)."

        Claim: in a race of two candidate-confirm calls whose chosen
        slots overlap a shared interviewer, exactly one succeeds and the
        loser yields ERR_INTERVIEWER_BUSY.
        """
        reset_clock_to_epoch()
        # Two distinct companies, applications, candidates, rounds, but
        # both rounds share an interviewer (hr_shared).
        company_a, hr_shared = create_verified_company()
        posting_a = create_live_posting(company_a["id"], hr_shared["id"])
        cand_a = create_candidate()
        app_a = submit_application(cand_a["id"], posting_a["id"])
        mark_application_read(app_a["id"], hr_shared["id"])
        forward_application(app_a["id"], hr_shared["id"])
        r1 = create_interview_round(
            app_a["id"], hr_shared["id"], interviewer_user_ids=[hr_shared["id"]],
        )
        slot = TEST_EPOCH + timedelta(hours=3)
        publish_round_slots(r1["id"], hr_shared["id"], [slot])
        company_b, hr_b = create_verified_company()
        posting_b = create_live_posting(company_b["id"], hr_b["id"])
        cand_b = create_candidate()
        app_b = submit_application(cand_b["id"], posting_b["id"])
        mark_application_read(app_b["id"], hr_b["id"])
        forward_application(app_b["id"], hr_b["id"])
        r2 = create_interview_round(
            app_b["id"], hr_b["id"],
            interviewer_user_ids=[hr_b["id"], hr_shared["id"]],
        )
        publish_round_slots(r2["id"], hr_b["id"], [slot])
        # Both candidates confirm the same slot — only one round can be SCHEDULED
        # because hr_shared cannot have two rounds at the same time.
        results = run_race(
            lambda: api.candidate_confirm_slot(
                r1["id"], candidate_confirm_payload(iso_utc(slot)),
                make_candidate_headers(cand_a["id"]),
            ),
            lambda: api.candidate_confirm_slot(
                r2["id"], candidate_confirm_payload(iso_utc(slot)),
                make_candidate_headers(cand_b["id"]),
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        for loser in outcome["failures"]:
            body = loser.json()
            assert body["data"]["error_id"] == ApiErrorId.ERR_INTERVIEWER_BUSY.value, (
                f"Loser should receive ERR_INTERVIEWER_BUSY, "
                f"got {body['data']['error_id']!r}"
            )


# ===========================================================================
# Two postings race for the last quota slot (PRD §2.9)
# ===========================================================================
class TestQuotaRace:

    def test_two_approves_for_last_slot_only_one_succeeds(self, api, platform_admin_headers):
        """PRD §2.9: "Two postings race to occupy the last available slot
        under a company's `posting_quota_limit`. Approval succeeds only
        while `active_job_posting_count` is strictly less than
        `posting_quota_limit`; the loser receives
        `ERR_POSTING_QUOTA_EXCEEDED` (409)."

        Claim: with active_job_posting_count==4 (BASIC quota=5), two
        simultaneous approves on two distinct UNDER_REVIEW postings yield
        exactly one success and one ERR_POSTING_QUOTA_EXCEEDED.
        """
        company, hr_user = create_verified_company(verification_tier="BASIC")
        # Take quota to 4.
        for _ in range(4):
            create_live_posting(company["id"], hr_user["id"])
        # Build two candidates for the last slot.
        p_a_resp = api.create_job_posting(
            create_job_posting_payload(
                company_id=company["id"], title="LastA",
                description="Distinct description A.",
            ),
            make_hr_user_headers(hr_user["id"]),
        )
        p_a = validate_success(p_a_resp, expected_status=201)
        submit_posting_review(p_a["id"], hr_user["id"])
        p_b_resp = api.create_job_posting(
            create_job_posting_payload(
                company_id=company["id"], title="LastB",
                description="Distinct description B.",
            ),
            make_hr_user_headers(hr_user["id"]),
        )
        p_b = validate_success(p_b_resp, expected_status=201)
        submit_posting_review(p_b["id"], hr_user["id"])
        results = run_race(
            lambda: api.approve_posting(p_a["id"], platform_admin_headers),
            lambda: api.approve_posting(p_b["id"], platform_admin_headers),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        for loser in outcome["failures"]:
            body = loser.json()
            assert body["data"]["error_id"] == ApiErrorId.ERR_POSTING_QUOTA_EXCEEDED.value, (
                f"Loser should receive ERR_POSTING_QUOTA_EXCEEDED, "
                f"got {body['data']['error_id']!r}"
            )


# ===========================================================================
# Two duplicate-fingerprint postings race to approve (PRD §2.9)
# ===========================================================================
class TestDuplicateFingerprintRace:

    def test_duplicate_fingerprint_approve_race(self, api, platform_admin_headers):
        """PRD §2.9: "Two HR users approve, simultaneously, two
        `JobPosting` rows that produce the same `content_fingerprint` for
        the same `Company`. Only one posting can be `LIVE` with a given
        fingerprint per company; the loser receives `ERR_DUPLICATE_POSTING`
        (409)."

        Claim: a race of two approves on two postings with identical
        content_fingerprint for the same Company yields exactly one
        success and one ERR_DUPLICATE_POSTING.
        """
        company, hr_user = create_verified_company(verification_tier="PREMIUM")
        # Two postings with identical title + description (and hence
        # identical content_fingerprint).
        same_title = "Senior Architect"
        same_desc = "Architect role description for the team."
        p_a_resp = api.create_job_posting(
            create_job_posting_payload(
                company_id=company["id"], title=same_title, description=same_desc,
            ),
            make_hr_user_headers(hr_user["id"]),
        )
        p_a = validate_success(p_a_resp, expected_status=201)
        submit_posting_review(p_a["id"], hr_user["id"])
        p_b_resp = api.create_job_posting(
            create_job_posting_payload(
                company_id=company["id"], title=same_title, description=same_desc,
            ),
            make_hr_user_headers(hr_user["id"]),
        )
        p_b = validate_success(p_b_resp, expected_status=201)
        submit_posting_review(p_b["id"], hr_user["id"])
        results = run_race(
            lambda: api.approve_posting(p_a["id"], platform_admin_headers),
            lambda: api.approve_posting(p_b["id"], platform_admin_headers),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        for loser in outcome["failures"]:
            body = loser.json()
            assert body["data"]["error_id"] == ApiErrorId.ERR_DUPLICATE_POSTING.value, (
                f"Loser should receive ERR_DUPLICATE_POSTING, "
                f"got {body['data']['error_id']!r}"
            )
