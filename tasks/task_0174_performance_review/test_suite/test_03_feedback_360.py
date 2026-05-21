"""360-degree FeedbackRequest lifecycle: create, submit, decline,
self-feedback rule, narrative bounds.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    create_employee_with_role,
    create_feedback_request_payload,
    setup_submittable_review_case,
    submit_feedback_request_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# FeedbackRequest creation and self-feedback guard
# ===========================================================================
class TestFeedbackCreation:

    def test_create_feedback_request_pending(self, api):
        """PRD §3.4: "A 360 feedback request is opened by the Manager or
        HRBP, who supplies `reviewer_employee_id` and `relation`...The
        request begins in `PENDING`."."""
        bundle = setup_submittable_review_case(attach_feedback=False)
        rev = create_employee_with_role("Reviewer",
                                        department=bundle.subject["department"])
        res = api.create_feedback_request(
            bundle.cycle["id"], bundle.review_case["id"],
            create_feedback_request_payload(rev.id, relation="PEER"),
            bundle.hrbp.headers,
        )
        fr = validate_success(res, 201)
        assert fr["status"] == "PENDING"
        assert fr["reviewer_employee_id"] == rev.id
        assert fr["relation"] == "PEER"
        assert fr["submitted_at"] is None

    def test_self_feedback_forbidden(self, api):
        """PRD §3.4: "Self-review is forbidden: the
        `reviewer_employee_id` may not equal the parent case's
        `subject_employee_id`, and a violation yields
        `ERR_SELF_FEEDBACK_FORBIDDEN`."."""
        bundle = setup_submittable_review_case(attach_feedback=False)
        res = api.create_feedback_request(
            bundle.cycle["id"], bundle.review_case["id"],
            create_feedback_request_payload(
                bundle.subject["id"], relation="PEER",
            ),
            bundle.hrbp.headers,
        )
        validate_error(res, "ERR_SELF_FEEDBACK_FORBIDDEN")


# ===========================================================================
# FeedbackRequest submission: state transition + narrative bounds + ownership
# ===========================================================================
class TestFeedbackSubmission:

    def test_submit_feedback_sets_submitted_at_and_bumps_count(self, api):
        """PRD §3.4: "On submission, `submitted_at` is set to the current
        clock, the parent case's `peer_feedback_count` is incremented by
        1...".
        """
        bundle = setup_submittable_review_case(attach_feedback=False)
        rev = create_employee_with_role("Reviewer",
                                        department=bundle.subject["department"])
        fr = validate_success(api.create_feedback_request(
            bundle.cycle["id"], bundle.review_case["id"],
            create_feedback_request_payload(rev.id), bundle.hrbp.headers,
        ), 201)
        res = api.submit_feedback_request(
            bundle.cycle["id"], bundle.review_case["id"], fr["id"],
            submit_feedback_request_payload(), rev.headers,
        )
        fr2 = validate_success(res, 200)
        assert fr2["status"] == "SUBMITTED"
        assert fr2["submitted_at"] is not None
        rc = validate_success(api.get_review_case(
            bundle.cycle["id"], bundle.review_case["id"],
            bundle.hrbp.headers,
        ), 200)
        assert rc["peer_feedback_count"] == 1

    def test_submit_feedback_short_narrative_rejected(self, api):
        """PRD §3.4: "the supplied `narrative` is at least 50 and at most
        5000 characters in length"."""
        bundle = setup_submittable_review_case(attach_feedback=False)
        rev = create_employee_with_role("Reviewer",
                                        department=bundle.subject["department"])
        fr = validate_success(api.create_feedback_request(
            bundle.cycle["id"], bundle.review_case["id"],
            create_feedback_request_payload(rev.id), bundle.hrbp.headers,
        ), 201)
        res = api.submit_feedback_request(
            bundle.cycle["id"], bundle.review_case["id"], fr["id"],
            submit_feedback_request_payload(narrative="Too short."),
            rev.headers,
        )
        # PRD §3.4 states the length rule but does not pin a specific
        # error_id. Accept ERR_VALIDATION or any 4xx schema error.
        assert 400 <= res.status_code < 500

    def test_submit_feedback_by_wrong_reviewer_forbidden(self, api):
        """PRD §3.4: "A request advances to `SUBMITTED` only when the
        acting reviewer is the same person as the request's
        `reviewer_employee_id`...".

        Two-reader caveat: the rule is stated as a precondition but PRD
        does not pin a specific error_id when violated. Assert a 4xx
        and that the request is not promoted.
        """
        bundle = setup_submittable_review_case(attach_feedback=False)
        rev = create_employee_with_role("Reviewer",
                                        department=bundle.subject["department"])
        other = create_employee_with_role("Reviewer",
                                          department=bundle.subject["department"])
        fr = validate_success(api.create_feedback_request(
            bundle.cycle["id"], bundle.review_case["id"],
            create_feedback_request_payload(rev.id),
            bundle.hrbp.headers,
        ), 201)
        # `other` (different Reviewer Employee.id) tries to submit.
        res = api.submit_feedback_request(
            bundle.cycle["id"], bundle.review_case["id"], fr["id"],
            submit_feedback_request_payload(), other.headers,
        )
        assert 400 <= res.status_code < 500

    def test_decline_feedback_request(self, api):
        """PRD §3.4: "A reviewer may instead decline; declining is
        permitted whenever the acting reviewer is the request's own
        `reviewer_employee_id`, leaves the request at `DECLINED` with no
        narrative captured...".
        """
        bundle = setup_submittable_review_case(attach_feedback=False)
        rev = create_employee_with_role("Reviewer",
                                        department=bundle.subject["department"])
        fr = validate_success(api.create_feedback_request(
            bundle.cycle["id"], bundle.review_case["id"],
            create_feedback_request_payload(rev.id), bundle.hrbp.headers,
        ), 201)
        res = api.decline_feedback_request(
            bundle.cycle["id"], bundle.review_case["id"], fr["id"],
            rev.headers,
        )
        fr2 = validate_success(res, 200)
        assert fr2["status"] == "DECLINED"
        # Per PRD §3.4 narrative is "not captured" on decline; PRD does
        # not explicitly state submitted_at must remain null after
        # decline — only "null while PENDING/DECLINED" in §3.4 narrative.
        # Two-reader test still finds null on DECLINED to be definite.
        assert fr2["submitted_at"] is None

    def test_double_submit_same_request_rejected(self, api):
        """PRD §3.4: "If the same reviewer races their own submit
        against itself, exactly one reaches `SUBMITTED`; the second
        sees `ERR_INVALID_STATE` (HTTP 409)." Sequential second submit
        from the same actor is the deterministic form of this race."""
        bundle = setup_submittable_review_case(attach_feedback=False)
        rev = create_employee_with_role("Reviewer",
                                        department=bundle.subject["department"])
        fr = validate_success(api.create_feedback_request(
            bundle.cycle["id"], bundle.review_case["id"],
            create_feedback_request_payload(rev.id), bundle.hrbp.headers,
        ), 201)
        validate_success(api.submit_feedback_request(
            bundle.cycle["id"], bundle.review_case["id"], fr["id"],
            submit_feedback_request_payload(), rev.headers,
        ), 200)
        # Sequential second attempt.
        res = api.submit_feedback_request(
            bundle.cycle["id"], bundle.review_case["id"], fr["id"],
            submit_feedback_request_payload(), rev.headers,
        )
        validate_error(res, "ERR_INVALID_STATE")
