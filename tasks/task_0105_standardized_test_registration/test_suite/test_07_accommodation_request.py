"""AccommodationRequest tests.

Covers PRD §3.6 — eligibility gate, submission deadlines, the
SUBMITTED -> UNDER_REVIEW -> NEEDS_MORE_INFO -> SUBMITTED cycle,
reviewer pinning (SoD), approval cascade onto Registration, denial,
and duplication.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock_to,
    api_client,
    approve_accommodation,
    assert_accommodation_request,
    create_accommodation_request_payload,
    create_candidate,
    create_event_with_capacity,
    create_test_event,
    create_test_center,
    create_capacity,
    deny_accommodation,
    force_confirmed_registration,
    make_accommodations_officer_headers,
    make_candidate_headers,
    request_more_info,
    reset_clock_to,
    resubmit_accommodation,
    start_review,
    submit_accommodation_request,
    submit_and_approve_accommodation,
    validate_error,
    validate_success,
)


# ===========================================================================
# Eligibility gate
# ===========================================================================
class TestEligibilityGate:
    def test_submit_without_iep_flag_rejected(self, api):
        """PRD §3.6: "A candidate whose record has `has_iep_or_504` at
        false is rejected with `ERR_ACCOMMODATION_NOT_ELIGIBLE`."

        Claim: POST /accommodation-requests as a candidate without the
        IEP flag returns ERR_ACCOMMODATION_NOT_ELIGIBLE.
        """
        event = create_test_event()
        cand = create_candidate(has_iep_or_504=False)
        res = api.create_accommodation_request(
            create_accommodation_request_payload(
                candidate_id=cand["id"],
                test_event_id=event["id"],
            ),
            make_candidate_headers(cand["id"]),
        )
        validate_error(res, ApiErrorId.ERR_ACCOMMODATION_NOT_ELIGIBLE.value)


# ===========================================================================
# Initial state and computed deadlines
# ===========================================================================
class TestInitialState:
    def test_create_starts_in_submitted(self, api):
        """PRD §3.6: "The request is created in `SUBMITTED` with two
        computed deadlines".

        Claim: a freshly created AccommodationRequest reports
        status=SUBMITTED.
        """
        event = create_test_event()
        cand = create_candidate(has_iep_or_504=True)
        req = submit_accommodation_request(cand, event["id"])
        assert_accommodation_request(req)
        assert req["status"] == "SUBMITTED"


# ===========================================================================
# Cycle: SUBMITTED -> UNDER_REVIEW -> NEEDS_MORE_INFO -> SUBMITTED -> UNDER_REVIEW
# ===========================================================================
class TestReviewCycle:
    def test_cycle_versions_strictly_increase(self, api):
        """PRD §3.6: "the candidate who owns the request may re-submit
        by appending new entries to `supporting_documents` (the length
        must strictly increase) ... and on success the row returns to
        `SUBMITTED`, from which the pinned officer pulls it back into
        `UNDER_REVIEW` again. The cycle through
        `SUBMITTED → UNDER_REVIEW → NEEDS_MORE_INFO → SUBMITTED →
        UNDER_REVIEW` may repeat any number of times".

        Claim: walking the cycle produces strictly increasing version
        numbers and revisits the same logical states.
        """
        event = create_test_event()
        cand = create_candidate(has_iep_or_504=True)
        req = submit_accommodation_request(
            cand, event["id"],
            docs=["https://docs.example.com/a.pdf"],
        )
        v0 = req["version"]
        # start-review.
        ur1 = start_review(req["id"])
        assert ur1["status"] == "UNDER_REVIEW"
        assert ur1["version"] == v0 + 1
        # request-info.
        nmi = request_more_info(req["id"])
        assert nmi["status"] == "NEEDS_MORE_INFO"
        assert nmi["version"] == v0 + 2
        # resubmit with longer docs list.
        re_sub = resubmit_accommodation(
            req["id"], cand,
            ["https://docs.example.com/a.pdf", "https://docs.example.com/b.pdf"],
        )
        assert re_sub["status"] == "SUBMITTED"
        assert re_sub["version"] == v0 + 3
        # start-review again — same state, different version.
        ur2 = start_review(req["id"])
        assert ur2["status"] == "UNDER_REVIEW"
        assert ur2["version"] == v0 + 4


# ===========================================================================
# SoD pinning
# ===========================================================================
class TestReviewerPinning:
    def test_second_officer_cannot_act_after_pinning(self, api):
        """PRD §3.6: "On success, the caller's `X-User-ID` is written
        into `reviewer_user_id` and pinned for the remainder of the
        row's life. From `UNDER_REVIEW`, the same pinned officer (any
        other officer is rejected with `ERR_NOT_PINNED_REVIEWER`) ..."

        Claim: after officer A start-reviews, officer B's call to
        approve returns ERR_NOT_PINNED_REVIEWER.
        """
        event = create_test_event()
        cand = create_candidate(has_iep_or_504=True)
        req = submit_accommodation_request(cand, event["id"])

        officer_a = make_accommodations_officer_headers("officer-pin-A")
        officer_b = make_accommodations_officer_headers("officer-pin-B")
        start_review(req["id"], officer_headers=officer_a)

        res = api.approve_accommodation(req["id"], officer_b)
        validate_error(res, ApiErrorId.ERR_NOT_PINNED_REVIEWER.value)

    def test_pinned_officer_can_complete_review(self, api):
        """PRD §3.6: "the same pinned officer ... may take three branches".

        Claim: after officer A pins, officer A's approve succeeds.
        """
        event = create_test_event()
        cand = create_candidate(has_iep_or_504=True)
        req = submit_accommodation_request(cand, event["id"])

        officer_a = make_accommodations_officer_headers("officer-pin-A")
        start_review(req["id"], officer_headers=officer_a)
        approved = approve_accommodation(req["id"], officer_headers=officer_a)
        assert approved["status"] == "APPROVED"


# ===========================================================================
# Approval cascade onto Registration
# ===========================================================================
class TestApprovalCascade:
    def test_approve_flips_registration_accommodation_required(self, api):
        """PRD §3.6: "Every `Registration` for the same
        `(candidate_id, test_event_id)` has its `accommodation_required`
        flipped to true, the new accommodation fee added to
        `accommodation_fee_cents_charged`, `amount_charged_cents`
        recomputed, and the approving `AccommodationRequest`'s
        `version` pinned into `locked_accommodation_request_version`."

        Claim: after approve, the matching CONFIRMED registration has
        accommodation_required=true and accommodation_fee_cents_charged
        set to ACCOMMODATION_FEE_CENTS (PRD §3.4 = 2500).
        """
        event, center, _ = create_event_with_capacity(
            total_capacity=5, accommodation_capacity=2,
        )
        cand = create_candidate(has_iep_or_504=True)
        reg = force_confirmed_registration(event["id"], cand, center["id"])
        before_charge = reg["amount_charged_cents"]
        # No accommodation yet -> fee should be zero on creation.
        assert reg["accommodation_fee_cents_charged"] == 0

        # Submit + start-review + approve.
        req = submit_accommodation_request(cand, event["id"])
        start_review(req["id"])
        approved = approve_accommodation(req["id"])

        # Refresh registration.
        refreshed = validate_success(
            api.get_registration(event["id"], reg["id"],
                                 TEST_USERS["registrar_headers"]),
            200,
        )
        assert refreshed["accommodation_required"] is True
        assert refreshed["accommodation_fee_cents_charged"] == 2500, (
            "PRD §3.4: ACCOMMODATION_FEE_CENTS is 2500 cents"
        )
        assert refreshed["amount_charged_cents"] == before_charge + 2500
        assert refreshed["locked_accommodation_request_version"] == approved["version"], (
            "PRD §3.6: locked_accommodation_request_version pins the request's version"
        )


# ===========================================================================
# Denial keeps accommodation_required false
# ===========================================================================
class TestDenial:
    def test_deny_keeps_accommodation_required_false(self, api):
        """PRD §3.6: "A denial does not change any registration's
        `accommodation_required` flag, and the candidate may still be
        checked in on the day of the test using the standard seating."

        Claim: after deny, the matching registration's
        accommodation_required is false (unchanged).
        """
        event, center, _ = create_event_with_capacity(
            total_capacity=5, accommodation_capacity=2,
        )
        cand = create_candidate(has_iep_or_504=True)
        reg = force_confirmed_registration(event["id"], cand, center["id"])
        req = submit_accommodation_request(cand, event["id"])
        start_review(req["id"])
        denied = deny_accommodation(req["id"])
        assert denied["status"] == "DENIED"
        refreshed = validate_success(
            api.get_registration(event["id"], reg["id"],
                                 TEST_USERS["registrar_headers"]),
            200,
        )
        assert refreshed["accommodation_required"] is False
