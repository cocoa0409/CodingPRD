"""Offer creation, three-stage approval, acceptance window, and rescission
(PRD §3.6)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    OFFER_ACCEPTANCE_WINDOW_HOURS,
    TEST_EPOCH,
    accept_offer_payload,
    advance_clock_by,
    advance_clock_to,
    assert_offer,
    bind_hr_user,
    create_offer,
    create_offer_payload,
    finance_approve_offer,
    hm_approve_offer,
    hr_approve_offer,
    iso_utc,
    make_candidate_headers,
    make_finance_approver_headers,
    make_hiring_manager_headers,
    make_hr_approver_headers,
    make_hr_user_headers,
    rescind_offer_payload,
    reset_clock_to_epoch,
    setup_accepted_offer,
    setup_application_at_interview_passed,
    setup_issued_offer,
    submit_offer_for_approval,
    validate_error,
    validate_success,
)


# ===========================================================================
# Offer creation (PRD §3.6)
# ===========================================================================
class TestOfferCreate:

    def test_create_offer_starts_in_draft(self, api):
        """PRD §3.6: "The offer starts in `offer_status` `DRAFT`."

        Claim: a new Offer is in DRAFT.
        """
        bag = setup_application_at_interview_passed()
        offer = create_offer(bag["application"]["id"], bag["hr_user"]["id"])
        assert_offer(offer)
        assert offer["offer_status"] == "DRAFT"

    def test_base_salary_zero_rejected_on_create(self, api):
        """PRD §3.6: "Both money fields are validated: `base_salary_cents`
        must be strictly greater than zero and `sign_on_bonus_cents` must
        be at least zero, else `ERR_INVALID_AMOUNT`."

        Claim: base_salary_cents == 0 yields ERR_INVALID_AMOUNT.
        """
        bag = setup_application_at_interview_passed()
        resp = api.create_offer(
            create_offer_payload(
                application_id=bag["application"]["id"],
                base_salary_cents=0,
                sign_on_bonus_cents=0,
            ),
            make_hr_user_headers(bag["hr_user"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_AMOUNT.value)

    def test_sign_on_bonus_negative_rejected_on_create(self, api):
        """PRD §3.6: "`sign_on_bonus_cents` must be at least zero, else
        `ERR_INVALID_AMOUNT`."

        Claim: sign_on_bonus_cents < 0 yields ERR_INVALID_AMOUNT.
        """
        bag = setup_application_at_interview_passed()
        resp = api.create_offer(
            create_offer_payload(
                application_id=bag["application"]["id"],
                base_salary_cents=5_000_000,
                sign_on_bonus_cents=-1,
            ),
            make_hr_user_headers(bag["hr_user"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_AMOUNT.value)


# ===========================================================================
# Submit-approval guards (PRD §3.6)
# ===========================================================================
class TestSubmitApproval:

    def test_submit_approval_advances_to_pending_hm(self, api):
        """PRD §3.6: "Submitting the offer for approval advances `DRAFT`
        to `PENDING_HM`."

        Claim: submit-approval transitions DRAFT → PENDING_HM.
        """
        bag = setup_application_at_interview_passed()
        offer = create_offer(bag["application"]["id"], bag["hr_user"]["id"])
        resp = api.submit_offer_approval(
            offer["id"], make_hr_user_headers(bag["hr_user"]["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["offer_status"] == "PENDING_HM"


# ===========================================================================
# Three-stage approval (PRD §3.6)
# ===========================================================================
class TestThreeStageApproval:

    def test_full_chain_to_issued(self, api):
        """PRD §3.6: "A `HiringManager` calls the approve action,
        transitioning `PENDING_HM` to `PENDING_HR`."
        PRD §3.6: "An `HrApprover` then calls the approve action,
        transitioning `PENDING_HR` to `PENDING_FINANCE`."
        PRD §3.6: "A `FinanceApprover` then calls the approve action,
        transitioning `PENDING_FINANCE` to `ISSUED`."

        Claim: HM → HR → Finance approvals chain DRAFT to ISSUED with
        each stage's approver field populated.
        """
        bag = setup_issued_offer()
        offer = bag["offer"]
        assert offer["offer_status"] == "ISSUED"
        assert offer["hm_approver_user_id"] == bag["hr_users"][0]["id"]
        assert offer["hr_approver_user_id"] == bag["hr_users"][1]["id"]
        assert offer["finance_approver_user_id"] == bag["hr_users"][2]["id"]

    def test_finance_approve_sets_issued_at_and_acceptance_deadline(self, api):
        """PRD §3.6: "On success, `finance_approver_user_id` is set,
        `issued_at` is set to the current instant, and
        `acceptance_deadline_at` is set to one hundred and sixty-eight
        hours (which equals seven days) after `issued_at`."

        Claim: ISSUED transition populates issued_at and
        acceptance_deadline_at = issued_at + 168h.
        """
        reset_clock_to_epoch()
        bag = setup_issued_offer()
        offer = bag["offer"]
        # Parse the two timestamps and compare.
        issued = datetime.fromisoformat(
            offer["issued_at"].replace("Z", "+00:00"),
        )
        deadline = datetime.fromisoformat(
            offer["acceptance_deadline_at"].replace("Z", "+00:00"),
        )
        assert (deadline - issued) == timedelta(
            hours=OFFER_ACCEPTANCE_WINDOW_HOURS,
        ), (
            f"acceptance_deadline_at - issued_at should be 168h, "
            f"got {deadline - issued}"
        )

    def test_segregation_violation_on_hr_same_as_hm(self, api):
        """PRD §3.6: "the actor must not be the same `HrUser` who served
        as the hiring manager — segregation of duties is enforced at
        this step. A repeat yields `ERR_SEGREGATION_VIOLATION`."

        Claim: HrApprover stage with the same HrUser id as the HM yields
        ERR_SEGREGATION_VIOLATION.
        """
        bag = setup_application_at_interview_passed()
        hm_hr = bag["hr_user"]
        offer = create_offer(bag["application"]["id"], hm_hr["id"])
        submit_offer_for_approval(offer["id"], hm_hr["id"])
        hm_approve_offer(offer["id"], hm_hr["id"])
        # HR-approver call uses the same HrUser id as the HM.
        resp = api.approve_offer(
            offer["id"], make_hr_approver_headers(hm_hr["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_VIOLATION.value)

    def test_segregation_violation_on_finance_same_as_hm(self, api):
        """PRD §3.6: "The actor must be bound to the offer's company and
        must differ from both `hm_approver_user_id` and `hr_approver_user_id`."

        Claim: FinanceApprover stage with the same HrUser id as the HM
        yields ERR_SEGREGATION_VIOLATION.
        """
        bag = setup_application_at_interview_passed()
        hm_hr = bag["hr_user"]
        hr_approver = bind_hr_user(bag["company"]["id"])
        offer = create_offer(bag["application"]["id"], hm_hr["id"])
        submit_offer_for_approval(offer["id"], hm_hr["id"])
        hm_approve_offer(offer["id"], hm_hr["id"])
        hr_approve_offer(offer["id"], hr_approver["id"])
        # Finance call reuses HM.
        resp = api.approve_offer(
            offer["id"], make_finance_approver_headers(hm_hr["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_VIOLATION.value)


# ===========================================================================
# Reject-approval (PRD §3.6)
# ===========================================================================
class TestRejectApproval:

    def test_reject_from_pending_hr_clears_hm(self, api):
        """PRD §3.6: "From `PENDING_HR`, rejecting returns the offer to
        `DRAFT` and clears `hm_approver_user_id`."

        Claim: rejecting at PENDING_HR returns offer to DRAFT and clears
        hm_approver_user_id.
        """
        bag = setup_application_at_interview_passed()
        hm_hr = bag["hr_user"]
        hr_approver = bind_hr_user(bag["company"]["id"])
        offer = create_offer(bag["application"]["id"], hm_hr["id"])
        submit_offer_for_approval(offer["id"], hm_hr["id"])
        hm_approve_offer(offer["id"], hm_hr["id"])
        # Reject from PENDING_HR as the HrApprover.
        resp = api.reject_offer_approval(
            offer["id"], make_hr_approver_headers(hr_approver["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["offer_status"] == "DRAFT"
        assert data.get("hm_approver_user_id") in (None, "")

    def test_reject_from_pending_finance_clears_both_approvers(self, api):
        """PRD §3.6: "From `PENDING_FINANCE`, rejecting returns the offer
        to `DRAFT` and clears both `hm_approver_user_id` and
        `hr_approver_user_id` (so the entire pipeline must restart)."

        Claim: rejecting at PENDING_FINANCE clears HM and HR approver fields.
        """
        bag = setup_application_at_interview_passed()
        hm_hr = bag["hr_user"]
        hr_approver = bind_hr_user(bag["company"]["id"])
        finance_approver = bind_hr_user(bag["company"]["id"])
        offer = create_offer(bag["application"]["id"], hm_hr["id"])
        submit_offer_for_approval(offer["id"], hm_hr["id"])
        hm_approve_offer(offer["id"], hm_hr["id"])
        hr_approve_offer(offer["id"], hr_approver["id"])
        resp = api.reject_offer_approval(
            offer["id"], make_finance_approver_headers(finance_approver["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["offer_status"] == "DRAFT"
        assert data.get("hm_approver_user_id") in (None, "")
        assert data.get("hr_approver_user_id") in (None, "")


# ===========================================================================
# Accept / decline window (PRD §3.6, validation 12)
# ===========================================================================
class TestOfferAcceptanceWindow:

    def test_accept_within_window_advances_to_accepted(self, api):
        """PRD §3.6: "The accept capability transitions `ISSUED` to
        `ACCEPTED` and is gated on the current instant being strictly
        less than `acceptance_deadline_at`."

        Claim: accept before the deadline moves ISSUED → ACCEPTED.
        """
        reset_clock_to_epoch()
        bag = setup_issued_offer()
        offer = bag["offer"]
        resp = api.accept_offer(
            offer["id"], make_candidate_headers(bag["candidate"]["id"]),
            accept_offer_payload(),
        )
        data = validate_success(resp, expected_status=200)
        assert data["offer_status"] == "ACCEPTED"
        assert data["accepted_at"] is not None

    def test_accept_at_deadline_returns_offer_expired(self, api):
        """PRD §3.6: "is gated on the current instant being strictly less
        than `acceptance_deadline_at`; equality means the deadline has
        already arrived and the request must be rejected with
        `ERR_OFFER_EXPIRED`."

        Claim: at now() == acceptance_deadline_at the accept is rejected
        with ERR_OFFER_EXPIRED.
        """
        reset_clock_to_epoch()
        bag = setup_issued_offer()
        offer = bag["offer"]
        deadline = datetime.fromisoformat(
            offer["acceptance_deadline_at"].replace("Z", "+00:00"),
        )
        advance_clock_to(deadline)
        resp = api.accept_offer(
            offer["id"], make_candidate_headers(bag["candidate"]["id"]),
            accept_offer_payload(),
        )
        validate_error(resp, ApiErrorId.ERR_OFFER_EXPIRED.value)

    def test_decline_advances_issued_to_declined(self, api):
        """PRD §3.6: "The decline capability transitions `ISSUED` to
        `DECLINED` and is unconditional."

        Claim: decline moves ISSUED → DECLINED.
        """
        bag = setup_issued_offer()
        offer = bag["offer"]
        resp = api.decline_offer(
            offer["id"], make_candidate_headers(bag["candidate"]["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["offer_status"] == "DECLINED"

    def test_clock_advance_past_deadline_auto_expires(self, api):
        """PRD §3.6: "The clock-advance capability auto-expires an
        `ISSUED` offer when the current instant reaches or surpasses
        `acceptance_deadline_at`, transitioning to `EXPIRED`."

        Claim: clock-advance past acceptance_deadline_at moves ISSUED →
        EXPIRED.
        """
        reset_clock_to_epoch()
        bag = setup_issued_offer()
        offer = bag["offer"]
        deadline = datetime.fromisoformat(
            offer["acceptance_deadline_at"].replace("Z", "+00:00"),
        )
        advance_clock_to(deadline + timedelta(seconds=1))
        data = validate_success(
            api.get_offer(
                offer["id"], make_candidate_headers(bag["candidate"]["id"]),
            ),
            expected_status=200,
        )
        assert data["offer_status"] == "EXPIRED"


# ===========================================================================
# Rescission (PRD §3.6)
# ===========================================================================
class TestRescission:

    def test_rescind_from_issued(self, api):
        """PRD §3.6: "Rescission from `ISSUED` requires a categorised
        `rescission_reason`..."

        Claim: rescind from ISSUED moves the offer to RESCINDED with the
        supplied rescission_reason.
        """
        bag = setup_issued_offer()
        offer = bag["offer"]
        resp = api.rescind_offer(
            offer["id"], rescind_offer_payload("BUSINESS_NEED"),
            make_hr_user_headers(bag["hr_user"]["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["offer_status"] == "RESCINDED"
        assert data["rescission_reason"] == "BUSINESS_NEED"

    def test_rescind_from_accepted_with_no_onboarding(self, api):
        """PRD §3.6: "Rescission from `ACCEPTED` requires the same
        `rescission_reason` and additionally requires that no `Onboarding`
        row yet exists for this offer; once onboarding has begun, the
        offer can no longer be rescinded through this path."

        Claim: rescind from ACCEPTED (no Onboarding yet) succeeds.
        """
        bag = setup_accepted_offer()
        offer = bag["offer"]
        resp = api.rescind_offer(
            offer["id"], rescind_offer_payload("CANDIDATE_MISREP"),
            make_hr_user_headers(bag["hr_user"]["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["offer_status"] == "RESCINDED"


# ===========================================================================
# Single-offer-per-application uniqueness (PRD §3.6)
# ===========================================================================
class TestOfferPerApplicationUnique:

    def test_second_offer_for_same_application_rejected(self, api):
        """PRD §3.6: "the `application_id` (which must be unique across
        all offers, so each application gets at most one offer)..."

        Claim: a second create-offer for the same application_id is
        rejected. PRD does not pin a more specific error_id than the
        generic validation/duplicate channel.
        """
        bag = setup_application_at_interview_passed()
        create_offer(bag["application"]["id"], bag["hr_user"]["id"])
        # Second offer:
        resp = api.create_offer(
            create_offer_payload(
                application_id=bag["application"]["id"],
                base_salary_cents=4_000_000,
                sign_on_bonus_cents=0,
            ),
            make_hr_user_headers(bag["hr_user"]["id"]),
        )
        assert resp.status_code >= 400, (
            "Second Offer for the same application_id must fail "
            "(application_id is unique across Offer)"
        )
