"""Plan review: phase gating, revision supersession, blocking comments."""
from test_helpers import (
    ApiErrorId,
    create_approved_plan_submission,
    create_plan_submission_record,
    create_project_record,
    create_review_comment_payload,
    create_work_letter_record,
    get_success_data,
    make_tenant_rep_headers,
    setup_project_in_plan_review,
    setup_property_space_tenant_lease,
    validate_error,
    validate_success,
)


class TestPlanPhaseGate:
    def test_plan_approval_requires_project_plan_review(self, api, landlord_pm_headers):
        """PRD 3.3: "The whole filing-and-review cycle is a `PLAN_REVIEW`-phase
        activity: filing a set, starting a review, approving, requesting
        revision, and final rejection each require the project to still be in
        `PLAN_REVIEW`." PRD 2.7: "The targeted entity must be in a state from
        which the requested transition exists — including the parent-phase
        gates named throughout §3 — and terminal states reject every
        transition, else `ERR_INVALID_STATE` (409)."

        Design: Difficulty/cross_entity_state_dependency/plan_approval_requires_project_plan_review
        """
        sc = setup_project_in_plan_review()

        # sub1 approved; sub2 filed and under review.
        sub1 = create_approved_plan_submission(sc["project"]["id"], sc["tenant"]["id"])
        assert sub1["status"] == "APPROVED"
        sub2 = create_plan_submission_record(sc["project"]["id"], sc["tenant"]["id"])
        sub2 = get_success_data(api.start_review(sub2["id"], landlord_pm_headers))
        assert sub2["status"] == "UNDER_REVIEW"

        # The project legally advances on the strength of sub1's approval.
        project = get_success_data(
            api.begin_pre_construction(sc["project"]["id"], landlord_pm_headers)
        )
        assert project["status"] == "PRE_CONSTRUCTION"

        # Approving sub2 now violates the parent-phase gate.
        resp = api.approve_submission(sub2["id"], landlord_pm_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        sub2_after = get_success_data(api.get_plan_submission(sub2["id"], landlord_pm_headers))
        assert sub2_after["status"] == "UNDER_REVIEW", (
            "the rejected approval must leave the submission untouched"
        )

    def test_start_review_after_phase_advance_rejected(self, api, landlord_pm_headers):
        """PRD 3.3: "The whole filing-and-review cycle is a `PLAN_REVIEW`-phase
        activity: filing a set, starting a review, approving, requesting
        revision, and final rejection each require the project to still be in
        `PLAN_REVIEW`." PRD 2.7: "The targeted entity must be in a state from
        which the requested transition exists — including the parent-phase
        gates named throughout §3 — and terminal states reject every
        transition, else `ERR_INVALID_STATE` (409)."

        Design: Difficulty/cross_entity_state_dependency/plan_approval_requires_project_plan_review
        """
        sc = setup_project_in_plan_review()
        sub1 = create_approved_plan_submission(sc["project"]["id"], sc["tenant"]["id"])
        assert sub1["status"] == "APPROVED"
        sub2 = create_plan_submission_record(sc["project"]["id"], sc["tenant"]["id"])
        assert sub2["status"] == "SUBMITTED"

        project = get_success_data(
            api.begin_pre_construction(sc["project"]["id"], landlord_pm_headers)
        )
        assert project["status"] == "PRE_CONSTRUCTION"

        resp = api.start_review(sub2["id"], landlord_pm_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        sub2_after = get_success_data(api.get_plan_submission(sub2["id"], landlord_pm_headers))
        assert sub2_after["status"] == "SUBMITTED"


class TestRevisionSupersession:
    def test_plan_revision_supersede_side_effect(self, api, landlord_pm_headers):
        """PRD 3.3: "Filing a fresh submission is also the only way out of a
        revision loop — when the project's prior submission sits in
        `REVISION_REQUIRED`, creating the next one flips the prior to
        `SUPERSEDED` and assigns the new record a `revision_no` one greater
        than its predecessor's." PRD 3.3: "Requesting revision moves it
        `UNDER_REVIEW` → `REVISION_REQUIRED` and increments its `review_round`
        by 1."

        Design: Corner/state_machines/plan_revision_supersede_side_effect
        """
        sc = setup_project_in_plan_review()
        sub1 = create_plan_submission_record(sc["project"]["id"], sc["tenant"]["id"])
        assert sub1["revision_no"] == 1
        sub1 = get_success_data(api.start_review(sub1["id"], landlord_pm_headers))
        sub1 = get_success_data(api.request_revision(sub1["id"], landlord_pm_headers))
        assert sub1["status"] == "REVISION_REQUIRED"

        sub2 = validate_success(
            api.create_plan_submission(
                sc["project"]["id"],
                {"drawing_set_ref": "DS-2"},
                make_tenant_rep_headers(sc["tenant"]["id"]),
            ),
            201,
        )
        assert sub2["revision_no"] == 2, (
            f"the next revision must be numbered one greater, got {sub2['revision_no']}"
        )
        assert sub2["status"] == "SUBMITTED"

        sub1_after = get_success_data(api.get_plan_submission(sub1["id"], landlord_pm_headers))
        assert sub1_after["status"] == "SUPERSEDED"
        assert sub1_after["review_round"] == 1, "the completed review cycle stays recorded"


class TestBlockingComments:
    def test_plan_approval_blocked_by_open_blocking_comment(self, api, landlord_pm_headers):
        """PRD 3.3: "Approval moves the submission `UNDER_REVIEW` → `APPROVED`
        and is refused with `ERR_BLOCKING_COMMENTS_OPEN` (HTTP 422) while any
        comment of the submission is simultaneously `OPEN` and `BLOCKING`."
        PRD 3.3: "Comments close `OPEN` → `RESOLVED`, but only while their
        submission remains `UNDER_REVIEW`."

        Design: Corner/state_machines/plan_approval_blocked_by_open_blocking_comment
        """
        sc = setup_project_in_plan_review()
        sub = create_plan_submission_record(sc["project"]["id"], sc["tenant"]["id"])
        sub = get_success_data(api.start_review(sub["id"], landlord_pm_headers))
        comment = get_success_data(
            api.create_review_comment(
                sub["id"],
                create_review_comment_payload(
                    comment_text="Egress path violates code", severity="BLOCKING"
                ),
                landlord_pm_headers,
            )
        )
        assert comment["status"] == "OPEN"

        resp = api.approve_submission(sub["id"], landlord_pm_headers)
        validate_error(resp, ApiErrorId.ERR_BLOCKING_COMMENTS_OPEN)

        get_success_data(api.resolve_review_comment(comment["id"], landlord_pm_headers))
        approved = validate_success(api.approve_submission(sub["id"], landlord_pm_headers), 200)
        assert approved["status"] == "APPROVED", (
            "resolving the only OPEN BLOCKING comment must unblock approval"
        )

    def test_comment_on_non_under_review_submission_rejected(self, api, landlord_pm_headers):
        """PRD 3.3: "The landlord picks up a submission `SUBMITTED` →
        `UNDER_REVIEW`, and while it is under review records review comments on
        it — each comment tied to its submission through `submission_id`,
        carrying the free-text `comment_text` and a `severity` of `INFO`,
        `REQUIRED`, or `BLOCKING`, and opening in `OPEN`." PRD 2.7: "The
        targeted entity must be in a state from which the requested transition
        exists — including the parent-phase gates named throughout §3 — and
        terminal states reject every transition, else `ERR_INVALID_STATE`
        (409)."

        Design: Corner/state_machines/comment_on_non_under_review_submission_rejected
        """
        sc = setup_project_in_plan_review()
        sub = create_plan_submission_record(sc["project"]["id"], sc["tenant"]["id"])
        assert sub["status"] == "SUBMITTED"
        resp = api.create_review_comment(
            sub["id"],
            create_review_comment_payload(comment_text="too early", severity="INFO"),
            landlord_pm_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestPlanReviewPrerequisite:
    def test_begin_plan_review_without_executed_work_letter_rejected(
        self, api, landlord_pm_headers
    ):
        """PRD 3.3: "With exactly one letter `EXECUTED`, the landlord moves the
        project `WORK_LETTER_NEGOTIATION` → `PLAN_REVIEW`; attempting the move
        without an executed letter is rejected with `ERR_PREREQUISITE_NOT_MET`
        (HTTP 422)."

        Design: Corner/validations/begin_plan_review_without_executed_work_letter_rejected
        """
        base = setup_property_space_tenant_lease()
        project = create_project_record(base["lease"]["id"])
        wl = create_work_letter_record(project["id"])
        wl = get_success_data(api.propose_work_letter(wl["id"], landlord_pm_headers))
        assert wl["status"] == "PROPOSED"  # tabled but never accepted/executed

        resp = api.begin_plan_review(project["id"], landlord_pm_headers)
        validate_error(resp, ApiErrorId.ERR_PREREQUISITE_NOT_MET)
        project_after = get_success_data(api.get_project(project["id"], landlord_pm_headers))
        assert project_after["status"] == "WORK_LETTER_NEGOTIATION"
