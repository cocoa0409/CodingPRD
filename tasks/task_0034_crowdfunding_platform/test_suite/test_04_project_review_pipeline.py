"""Project review pipeline: submit, three-stage editorial, segregation
of duties, and the revision loop.

PRD references:
  - §3.3 Submitting for Review and the Three-Stage Editorial Pipeline
  - §2.8 Validation Ordering
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_hours,
    DEFAULT_NOW_ISO,
    create_draft_project,
    create_initiator,
    create_reward,
    create_verified_initiator,
    current_clock_iso,
    make_initiator_headers,
    review_payload,
    setup_revision_loop_project,
    submit_project,
    validate_error,
    validate_success,
    review_content,
    review_legal,
    review_financial,
)
from test_helpers import make_content_reviewer_headers, make_legal_reviewer_headers


class TestSubmitGates:
    def test_submit_kyc_required_when_pending(self, api):
        """PRD §3.3: 'the calling initiator's kyc_status must be VERIFIED
        (otherwise ERR_KYC_REQUIRED)'.

        Claim: submit without verified KYC → ERR_KYC_REQUIRED.
        """
        initiator = create_initiator(with_tax_id=True)  # PENDING by default
        project = create_draft_project(
            initiator=initiator,
            deadline_hours_from_now=240.0,
        )
        # Need at least one reward to test KYC vs no-rewards precedence.
        # PRD §2.8 places KYC at priority 7 and no-rewards at priority 14.
        create_reward(
            project=project, initiator=initiator,
            pledge_amount_cents=1_000, reward_type="DIGITAL",
        )
        res = api.submit_project(
            project["id"], make_initiator_headers(initiator["id"])
        )
        validate_error(res, "ERR_KYC_REQUIRED")

    def test_submit_no_rewards_defined(self, api):
        """PRD §3.3: 'the project must already have at least one reward
        defined (otherwise ERR_NO_REWARDS_DEFINED)'.

        Claim: submit with zero rewards → ERR_NO_REWARDS_DEFINED.
        """
        initiator = create_verified_initiator(with_tax_id=True)
        project = create_draft_project(
            initiator=initiator, deadline_hours_from_now=240.0
        )  # no rewards
        res = api.submit_project(
            project["id"], make_initiator_headers(initiator["id"])
        )
        validate_error(res, "ERR_NO_REWARDS_DEFINED")

    def test_submit_deadline_too_soon(self, api):
        """PRD §3.3: 'deadline must be more than 24 hours after the
        current time (otherwise ERR_DEADLINE_TOO_SOON)'.

        Claim: deadline only 23h ahead → ERR_DEADLINE_TOO_SOON.
        """
        # Pin the simulated clock to a known instant so the 23h deadline
        # we construct below is meaningfully less than 24h ahead of the
        # server's current time. Without this, the server would still be
        # using wall-clock time and a deadline at DEFAULT_NOW_ISO + 23h
        # would in fact be many days ahead.
        from test_helpers import advance_clock
        advance_clock(DEFAULT_NOW_ISO)

        initiator = create_verified_initiator(with_tax_id=True)
        # Project with a deadline 23h from current server time (< 24h).
        deadline = add_hours(current_clock_iso(), 23)
        from test_helpers import create_project_payload
        res_create = api.create_project(
            create_project_payload(deadline=deadline),
            make_initiator_headers(initiator["id"]),
        )
        # Either creation rejected, or creation succeeded but submit fails.
        if res_create.status_code >= 400:
            validate_error(res_create, "ERR_DEADLINE_TOO_SOON")
        else:
            project = res_create.json()["data"]
            create_reward(
                project=project, initiator=initiator,
                pledge_amount_cents=1_000, reward_type="DIGITAL",
            )
            res = api.submit_project(
                project["id"], make_initiator_headers(initiator["id"])
            )
            validate_error(res, "ERR_DEADLINE_TOO_SOON")

    def test_submit_advances_to_content_review(self, api):
        """PRD §3.3: 'Submission advances status from DRAFT to
        CONTENT_REVIEW and is gated by five preconditions checked
        together'.

        Claim: well-formed submit → status CONTENT_REVIEW.
        """
        initiator = create_verified_initiator(with_tax_id=True)
        project = create_draft_project(
            initiator=initiator, deadline_hours_from_now=240.0
        )
        create_reward(
            project=project, initiator=initiator,
            pledge_amount_cents=1_000, reward_type="DIGITAL",
        )
        res = api.submit_project(
            project["id"], make_initiator_headers(initiator["id"])
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "CONTENT_REVIEW"

    def test_double_submit_second_invalid_state(self, api):
        """PRD §3.3: 'A second concurrent submit on the same draft is
        rejected with ERR_INVALID_STATE, since only one transition out
        of DRAFT may win.'

        Claim: second submit (after first succeeded) → ERR_INVALID_STATE.
        """
        initiator = create_verified_initiator(with_tax_id=True)
        project = create_draft_project(
            initiator=initiator, deadline_hours_from_now=240.0
        )
        create_reward(
            project=project, initiator=initiator,
            pledge_amount_cents=1_000, reward_type="DIGITAL",
        )
        api.submit_project(
            project["id"], make_initiator_headers(initiator["id"])
        )
        # Second submit on a project now in CONTENT_REVIEW must fail.
        res = api.submit_project(
            project["id"], make_initiator_headers(initiator["id"])
        )
        validate_error(res, "ERR_INVALID_STATE")


class TestReviewPipeline:
    def test_content_approve_advances_to_legal_review(self, api):
        """PRD §3.3: 'An APPROVE decision moves the project to
        LEGAL_REVIEW.'

        Claim: content APPROVE → LEGAL_REVIEW.
        """
        initiator, project = setup_revision_loop_project()
        submitted = submit_project(project=project, initiator=initiator)
        assert submitted["status"] == "CONTENT_REVIEW"
        res = api.review_content(
            project["id"], review_payload(decision="APPROVE"),
            make_content_reviewer_headers("crv-001"),
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "LEGAL_REVIEW"

    def test_content_request_changes_returns_to_draft_with_reason(self, api):
        """PRD §3.3: 'A REQUEST_CHANGES decision moves the project back to
        DRAFT, sets rejection_reason to the supplied message so the
        initiator can revise and resubmit, and writes an audit entry —
        this is the revision loop.'

        Claim: REQUEST_CHANGES → DRAFT with rejection_reason set.
        """
        initiator, project = setup_revision_loop_project()
        submit_project(project=project, initiator=initiator)
        res = api.review_content(
            project["id"],
            review_payload(decision="REQUEST_CHANGES",
                           message="Needs better description"),
            make_content_reviewer_headers("crv-001"),
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "DRAFT"
        assert data["rejection_reason"] == "Needs better description"

    def test_content_reject_terminal(self, api):
        """PRD §3.3: 'A REJECT decision moves the project to the terminal
        REJECTED status with rejection_reason set.'

        Claim: content REJECT → terminal REJECTED.
        """
        initiator, project = setup_revision_loop_project()
        submit_project(project=project, initiator=initiator)
        res = api.review_content(
            project["id"],
            review_payload(decision="REJECT", message="Out of scope"),
            make_content_reviewer_headers("crv-001"),
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "REJECTED"
        assert data["rejection_reason"] == "Out of scope"

    def test_legal_approve_advances_to_financial_review(self, api):
        """PRD §3.3: 'APPROVE advances to FINANCIAL_REVIEW' (legal stage).

        Claim: legal APPROVE → FINANCIAL_REVIEW.
        """
        initiator, project = setup_revision_loop_project()
        submit_project(project=project, initiator=initiator)
        review_content(project_id=project["id"], decision="APPROVE",
                       reviewer_id="crv-1")
        res = api.review_legal(
            project["id"], review_payload(decision="APPROVE"),
            make_legal_reviewer_headers("lrv-1"),
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "FINANCIAL_REVIEW"

    def test_financial_approve_takes_project_live(self, api):
        """PRD §3.3: 'APPROVE advances to LIVE' (financial stage).

        Claim: financial APPROVE → LIVE.
        """
        initiator, project = setup_revision_loop_project()
        submit_project(project=project, initiator=initiator)
        review_content(project_id=project["id"], decision="APPROVE",
                       reviewer_id="crv-X")
        review_legal(project_id=project["id"], decision="APPROVE",
                     reviewer_id="lrv-X")
        from test_helpers import make_financial_reviewer_headers
        res = api.review_financial(
            project["id"], review_payload(decision="APPROVE"),
            make_financial_reviewer_headers("frv-X"),
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "LIVE"


class TestSegregationOfDuties:
    def test_legal_approver_cannot_be_content_approver(self, api):
        """PRD §3.3: 'The legal-review approve transition therefore
        requires that the calling reviewer's X-User-ID differ from the
        content reviewer who approved this project ... A repeat approval
        by a previously-recorded reviewer is rejected with
        ERR_SEGREGATION_OF_DUTIES_VIOLATION.'

        Claim: legal APPROVE by the same X-User-ID as content APPROVE →
        ERR_SEGREGATION_OF_DUTIES_VIOLATION.
        """
        initiator, project = setup_revision_loop_project()
        submit_project(project=project, initiator=initiator)
        # Same reviewer ID across content and legal stages is the violation.
        same_id = "shared-reviewer-001"
        review_content(project_id=project["id"], decision="APPROVE",
                       reviewer_id=same_id)
        # Now try legal review with the same X-User-ID.
        res = api.review_legal(
            project["id"], review_payload(decision="APPROVE"),
            # The legal-review endpoint accepts a LegalReviewer role, but
            # PRD §3.3's SoD rule compares X-User-ID alone across the
            # three stages.
            make_legal_reviewer_headers(same_id),
        )
        validate_error(res, "ERR_SEGREGATION_OF_DUTIES_VIOLATION")

    def test_financial_approver_cannot_be_either_prior_approver(self, api):
        """PRD §3.3: 'the financial-review approve transition requires that
        the calling reviewer's X-User-ID differ from both prior approvers'.

        Claim: financial APPROVE by the content reviewer's id →
        ERR_SEGREGATION_OF_DUTIES_VIOLATION.
        """
        initiator, project = setup_revision_loop_project()
        submit_project(project=project, initiator=initiator)
        review_content(project_id=project["id"], decision="APPROVE",
                       reviewer_id="content-rv-A")
        review_legal(project_id=project["id"], decision="APPROVE",
                     reviewer_id="legal-rv-B")
        from test_helpers import make_financial_reviewer_headers
        # Use the content reviewer's id at the financial stage.
        res = api.review_financial(
            project["id"], review_payload(decision="APPROVE"),
            make_financial_reviewer_headers("content-rv-A"),
        )
        validate_error(res, "ERR_SEGREGATION_OF_DUTIES_VIOLATION")
