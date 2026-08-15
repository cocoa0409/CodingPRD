"""Validation evidence, closure adjudication (with its revision loop), and the
examination's terminal transitions (PRD §3.6, §3.7, §3.8, §2.7, §2.9, §2.10)."""
from test_helpers import (
    RAM,
    ApiErrorId,
    add_sufficient_evidence,
    create_commitment_payload,
    create_submit_validation_payload,
    create_validation_evidence_payload,
    get_exam,
    get_issue,
    get_plan,
    make_compliance_reviewer_headers,
    setup_exam_closed,
    setup_issue_closed,
    setup_issue_in_progress,
    setup_plan_complete_ctx,
    setup_validation_submitted,
    validate_error,
    validate_success,
)


class TestMilestoneToExaminationCascade:
    def test_final_milestone_completion_completes_active_plan(self, api):
        """PRD §3.6: "Completing a milestone requires it to be `IN_PROGRESS`;
        completion stamps `completed_at`, re-evaluates whether the parent plan
        has earned its `ACTIVE` → `COMPLETE` transition, and bumps the
        milestone's and plan's `version`."
        PRD §3.6: "An `ACTIVE` plan completes itself: the moment every one of
        its milestones stands `COMPLETE` — and there is at least one — the plan
        moves `ACTIVE` → `COMPLETE`."

        Cascade hop 1: completing the plan's only milestone earns the plan its
        ACTIVE -> COMPLETE transition.

        Design: Difficulty/transitive_cascade/milestone_complete_cascades_plan_complete_to_validation_transition
        """
        ctx = setup_issue_in_progress()
        milestone = validate_success(
            api.complete_remediation_milestone(ctx["milestone"]["id"],
                                               ctx["owner_headers"]))
        assert milestone["status"] == "COMPLETE"
        assert milestone["completed_at"], "completion stamps completed_at"
        plan = get_plan(ctx["plan"]["id"])
        assert plan["status"] == "COMPLETE", (
            "hop 1: every milestone COMPLETE completes the ACTIVE plan"
        )

    def test_submit_validation_auto_advances_exam_to_validation(self, api):
        """PRD §3.7: "A successful submission moves the issue `IN_PROGRESS` →
        `VALIDATION_SUBMITTED` and springs a closure request into existence:
        `PENDING`, stamped with a `request_round` equal to the count of prior
        closure requests on this issue plus one, carrying the payload's
        `validation_evidence_id` and the owner's `closure_narrative` asserting
        the issue is remediated."
        PRD §3.7: "The submission also re-evaluates the examination's automatic
        advance — the examination moves `REMEDIATION` → `VALIDATION` on its own
        the moment at least one issue exists and every issue stands
        `VALIDATION_SUBMITTED` or `CLOSED` — and bumps both the issue's and the
        examination's `version`."

        Cascade hops 2 and 3: the issue moves IN_PROGRESS ->
        VALIDATION_SUBMITTED, a PENDING closure request (round 1) springs into
        existence, and — this being the exam's only issue — the examination
        auto-advances REMEDIATION -> VALIDATION.

        Design: Difficulty/transitive_cascade/milestone_complete_cascades_plan_complete_to_validation_transition
        """
        ctx = setup_plan_complete_ctx()
        assert ctx["plan"]["status"] == "COMPLETE"
        closure = validate_success(
            api.submit_issue_validation(
                ctx["issue"]["id"],
                create_submit_validation_payload(ctx["evidence"]["id"]),
                ctx["owner_headers"]),
            201)
        assert closure["status"] == "PENDING"
        assert closure["request_round"] == 1
        assert closure["validation_evidence_id"] == ctx["evidence"]["id"]
        issue = get_issue(ctx["issue"]["id"])
        assert issue["status"] == "VALIDATION_SUBMITTED", "hop 2"
        exam = get_exam(ctx["exam"]["id"])
        assert exam["status"] == "VALIDATION", (
            "hop 3: every issue VALIDATION_SUBMITTED or CLOSED auto-advances the exam"
        )


class TestClosureRevisionLoop:
    def test_closure_rejection_cycles_issue_back_to_in_progress(self, api):
        """PRD §3.7: "Rejection requires a non-empty `rejection_reason`, runs
        the same segregation check, records the same `reviewed_by_user_id`, and
        moves the request `PENDING` → `REJECTED` while the issue loops back
        `VALIDATION_SUBMITTED` → `IN_PROGRESS` for further work — with the
        `version` of the closure request, the issue, and the examination each
        incrementing by one, exactly as an approval would; the next validation
        submission on that issue then opens a fresh closure request with the
        next `request_round`."

        The round-1 closure request is rejected; the issue loops back to
        IN_PROGRESS.

        Design: Difficulty/non_linear_state_machine/closure_request_rejection_cycles_issue_back_to_in_progress
        """
        ctx = setup_validation_submitted()
        assert ctx["closure_request"]["request_round"] == 1
        rejected = validate_success(
            api.reject_closure_request(
                ctx["closure_request"]["id"],
                {"rejection_reason": "Insufficient artifact scope"},
                ctx["reviewer_headers"]))
        assert rejected["status"] == "REJECTED"
        assert rejected["reviewed_by_user_id"] == ctx["reviewer"]["id"]
        issue = get_issue(ctx["issue"]["id"])
        assert issue["status"] == "IN_PROGRESS", (
            "VALIDATION_SUBMITTED cycles back to IN_PROGRESS on rejection"
        )

    def test_second_validation_submission_opens_round_two(self, api):
        """PRD §3.7: "Rejection requires a non-empty `rejection_reason`, runs
        the same segregation check, records the same `reviewed_by_user_id`, and
        moves the request `PENDING` → `REJECTED` while the issue loops back
        `VALIDATION_SUBMITTED` → `IN_PROGRESS` for further work — with the
        `version` of the closure request, the issue, and the examination each
        incrementing by one, exactly as an approval would; the next validation
        submission on that issue then opens a fresh closure request with the
        next `request_round`. This revision loop may cycle as many times as the
        evidence requires."

        After the rejection cycle, a fresh validation submission opens a new
        PENDING closure request stamped request_round 2.

        Design: Difficulty/non_linear_state_machine/closure_request_rejection_cycles_issue_back_to_in_progress
        """
        ctx = setup_validation_submitted()
        validate_success(
            api.reject_closure_request(
                ctx["closure_request"]["id"],
                {"rejection_reason": "Insufficient artifact scope"},
                ctx["reviewer_headers"]))
        assert get_issue(ctx["issue"]["id"])["status"] == "IN_PROGRESS"

        evidence2 = add_sufficient_evidence(
            ctx, evidence_type="INTERNAL_AUDIT_REPORT")
        closure2 = validate_success(
            api.submit_issue_validation(
                ctx["issue"]["id"],
                create_submit_validation_payload(evidence2["id"],
                                                 closure_narrative="v2"),
                ctx["owner_headers"]),
            201)
        assert closure2["request_round"] == 2, "request_round increments across the cycle"
        assert closure2["status"] == "PENDING"
        assert get_issue(ctx["issue"]["id"])["status"] == "VALIDATION_SUBMITTED"


class TestClosureAdjudicationGates:
    def test_segregation_of_duties_blocks_owner_from_approving_closure(self, api):
        """PRD §2.10: "The segregation-of-duties rule prohibits a
        `ComplianceReviewer` from adjudicating a closure request — in either
        direction, approval or rejection — when that reviewer's own `id` equals
        the `owner_user_id` of the issue's currently `ACTIVE` remediation plan.
        The comparison is the acting reviewer's identity against the recorded
        plan owner; a match is rejected with `ERR_SEGREGATION_OF_DUTIES`
        (HTTP 422)."
        PRD §2.9: "A closure approval attempted by the plan's owner with a
        stale issue version, for instance, surfaces `ERR_SEGREGATION_OF_DUTIES`,
        because the segregation check (step 5) precedes the concurrency check
        (step 7)"

        The acting reviewer's identity equals the remediation plan owner's id.

        Design: Corner/validations/segregation_of_duties_blocks_owner_from_approving_closure
        """
        ctx = setup_validation_submitted()
        issue_v = get_issue(ctx["issue"]["id"])["version"]
        owner_as_reviewer = make_compliance_reviewer_headers(ctx["officer"]["id"])
        resp = api.approve_closure_request(
            ctx["closure_request"]["id"],
            {"expected_issue_version": issue_v},
            owner_as_reviewer)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_stale_issue_version_rejected_on_closure_approve(self, api):
        """PRD §2.7: "approving a closure request
        (`POST /regulatory-exams/closure-requests/{id}/approve`) requires
        `expected_issue_version`, the client-observed `version` of the parent
        issue, which advances whenever the issue's state, evidence linkage, or
        escalation flag changes"
        PRD §2.7: "In all three cases the expected-version field is
        non-optional, and a mismatch with the parent entity's current `version`
        is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.7: "Evidence is born with `review_status` `PENDING`, and its
        creation bumps the issue's `version`."

        An unrelated evidence submission advances the issue's version between
        the reviewer's read and the approval call.

        Design: Corner/endpoints/occ_stale_version_on_closure_approve
        """
        ctx = setup_validation_submitted()
        observed_v = get_issue(ctx["issue"]["id"])["version"]
        validate_success(
            api.create_validation_evidence(
                ctx["issue"]["id"],
                create_validation_evidence_payload(
                    submitted_by_user_id=ctx["officer"]["id"],
                    evidence_type="DOCUMENT_PACKAGE"),
                ctx["owner_headers"]),
            201)
        resp = api.approve_closure_request(
            ctx["closure_request"]["id"],
            {"expected_issue_version": observed_v},
            ctx["reviewer_headers"])
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_submit_validation_blocked_with_incomplete_milestone(self, api):
        """PRD §3.7: "Three preconditions guard that submission, and any failure
        is rejected with `ERR_ISSUE_NOT_CLOSABLE`: the issue must stand
        `IN_PROGRESS`; the payload's `validation_evidence_id` must reference
        evidence whose `review_status` is `SUFFICIENT` on this same issue; and
        every milestone of the issue's `ACTIVE` plan must stand `COMPLETE`."

        The issue stands IN_PROGRESS and the evidence is SUFFICIENT, but the
        ACTIVE plan's milestone is still IN_PROGRESS rather than COMPLETE.

        Design: Corner/errors/err_issue_not_closable_triggerable
        """
        ctx = setup_issue_in_progress()
        evidence = add_sufficient_evidence(ctx)
        resp = api.submit_issue_validation(
            ctx["issue"]["id"],
            create_submit_validation_payload(evidence["id"]),
            ctx["owner_headers"])
        validate_error(resp, ApiErrorId.ERR_ISSUE_NOT_CLOSABLE)


class TestExaminationClose:
    def test_close_blocked_while_issue_not_closed(self, api):
        """PRD §3.8: "Commitments bind the end of the lifecycle: closing the
        examination, moving it `VALIDATION` → `CLOSED`, requires every issue on
        the examination to stand `CLOSED` — any straggler draws
        `ERR_OPEN_ISSUES_REMAIN` — and requires every commitment on the
        examination to have a non-null `fulfilled_at`, with an outstanding
        promise drawing `ERR_COMMITMENT_OUTSTANDING`."

        The exam auto-advanced to VALIDATION, but its only issue still stands
        VALIDATION_SUBMITTED.

        Design: Corner/errors/err_open_issues_remain_triggerable
        """
        ctx = setup_validation_submitted()
        assert get_exam(ctx["exam"]["id"])["status"] == "VALIDATION"
        assert get_issue(ctx["issue"]["id"])["status"] == "VALIDATION_SUBMITTED"
        resp = api.close_examination(ctx["exam"]["id"], RAM)
        validate_error(resp, ApiErrorId.ERR_OPEN_ISSUES_REMAIN)

    def test_close_blocked_by_outstanding_commitment(self, api):
        """PRD §3.8: "Commitments bind the end of the lifecycle: closing the
        examination, moving it `VALIDATION` → `CLOSED`, requires every issue on
        the examination to stand `CLOSED` — any straggler draws
        `ERR_OPEN_ISSUES_REMAIN` — and requires every commitment on the
        examination to have a non-null `fulfilled_at`, with an outstanding
        promise drawing `ERR_COMMITMENT_OUTSTANDING`."

        Every issue is CLOSED, but one commitment still has a null fulfilled_at.

        Design: Corner/errors/err_commitment_outstanding_triggerable
        """
        ctx = setup_issue_closed()
        assert get_exam(ctx["exam"]["id"])["status"] == "VALIDATION"
        assert get_issue(ctx["issue"]["id"])["status"] == "CLOSED"
        validate_success(
            api.create_commitment(
                ctx["exam"]["id"],
                create_commitment_payload(
                    committed_by_user_id=ctx["officer"]["id"]),
                RAM),
            201)
        resp = api.close_examination(ctx["exam"]["id"], RAM)
        validate_error(resp, ApiErrorId.ERR_COMMITMENT_OUTSTANDING)

    def test_closed_exam_rejects_further_transitions(self, api):
        """PRD §2.9: "When the target already rests in a terminal state
        (`CLOSED`, `CANCELLED`, `SUBMITTED`, `WAIVED`, `ACCEPTED`, `REJECTED`,
        `FINALIZED`, `COMPLETE`, `SUPERSEDED`, `SUFFICIENT`, `INSUFFICIENT`, or
        `APPROVED`), the rejection instead carries `ERR_ALREADY_TERMINAL`
        (HTTP 409)."

        A cancel attempt against an already-CLOSED examination is rejected as
        terminal rather than as a plain state violation.

        Design: Corner/state_machines/terminal_state_lockdown_closed_exam_rejects_further_transitions
        """
        ctx = setup_exam_closed()
        assert ctx["exam"]["status"] == "CLOSED"
        resp = api.cancel_examination(
            ctx["exam"]["id"], {"cancelled_reason": "post-close attempt"}, RAM)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)
