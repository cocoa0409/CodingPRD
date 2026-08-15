"""Research plans, ethics-committee decisions, and their cascades.

Covers: the revision loop cycle, REJECT cascading to project withdrawal,
validation-priority interplay (state vs segregation of duties), the
human/animal-subjects research-plan gate on project submission, SoD and
rationale guards, mentor ownership enforcement, OCC on project reassignment,
and read-after-write consistency of the ethics cascade.
"""
from test_helpers import (
    ApiErrorId,
    add_category,
    add_mentor,
    api_client,
    assert_project,
    assert_research_plan,
    drive_revision_loop,
    er_headers,
    fd_headers,
    get_plan,
    get_project,
    make_mentor_headers,
    record_decision,
    register_project,
    research_plan_payload,
    setup_open_edition,
    setup_plan_under_review,
    setup_project_with_plan,
    validate_error,
    validate_paginated,
    validate_success,
    get_success_data,
)


class TestResearchPlanRevisionLoop:
    def test_revision_loop_status_and_cycle_count(self, api):
        """PRD §3.3: "An `EthicsReviewer` then takes the plan under review
        (`SUBMITTED` → `UNDER_REVIEW`), which increments `review_cycle_count`
        by 1 so the committee can see how many rounds a plan has been through."
        PRD §3.3: "while the plan sits in `REVISION_REQUIRED`, any change to
        `plan_text` returns it to `DRAFT`, clears `approved_plan_version` to
        null, and increments the plan's `version` — ready to be submitted again
        for another cycle."

        Design: Difficulty/non_linear_state_machine/research_plan_revision_loop_cycle
        """
        ctx = setup_project_with_plan(human=True)
        plan, _project = drive_revision_loop(ctx)

        assert_research_plan(plan)
        assert plan["status"] == "APPROVED", (
            f"plan must end APPROVED after the second review round, got {plan['status']}"
        )
        assert plan["review_cycle_count"] == 2, (
            f"plan entered UNDER_REVIEW twice, expected review_cycle_count 2, got {plan['review_cycle_count']}"
        )

    def test_revision_loop_pins_second_approval_version(self, api):
        """PRD §3.3: "An `APPROVE` moves the plan `UNDER_REVIEW` → `APPROVED`,
        pins `approved_plan_version` to the plan's current `version` — a
        snapshot that goes stale if the plan's version later advances — and
        cascades onto the parent project, setting its `ethics_status` to
        `APPROVED` and incrementing the project's `version`".

        Design: Difficulty/non_linear_state_machine/research_plan_revision_loop_cycle
        """
        ctx = setup_project_with_plan(human=True)
        plan, project = drive_revision_loop(ctx)

        assert plan["approved_plan_version"] == plan["version"], (
            "approved_plan_version must pin the version current at the SECOND "
            f"approval: approved_plan_version={plan['approved_plan_version']} vs version={plan['version']}"
        )
        assert project["ethics_status"] == "APPROVED", (
            f"approval cascades ethics_status APPROVED onto the project, got {project['ethics_status']}"
        )


class TestEthicsRejectCascade:
    def test_reject_rejects_plan_and_sets_ethics(self, api):
        """PRD §3.3: "A `REJECT` moves the plan to `REJECTED`, sets the
        project's `ethics_status` to `REJECTED`, and cascades the project's
        `registration_status` to `WITHDRAWN`."

        Design: Difficulty/transitive_cascade/ethics_reject_cascades_plan_to_project_withdrawal
        """
        ctx = setup_plan_under_review(human=False, animal=True, plan_risk="HIGH")
        review = validate_success(
            record_decision(ctx["plan"]["id"], ctx["reviewer"]["id"], "REJECT", rationale="no IACUC approval"),
            201,
        )
        assert review["decision"] == "REJECT"

        plan = get_plan(ctx["plan"]["id"])
        project = get_project(ctx["project"]["id"])
        assert plan["status"] == "REJECTED"
        assert project["ethics_status"] == "REJECTED"

    def test_reject_withdraws_parent_project(self, api):
        """PRD §3.3: "A `REJECT` moves the plan to `REJECTED`, sets the
        project's `ethics_status` to `REJECTED`, and cascades the project's
        `registration_status` to `WITHDRAWN`."

        Design: Difficulty/transitive_cascade/ethics_reject_cascades_plan_to_project_withdrawal
        """
        ctx = setup_plan_under_review(human=False, animal=True, plan_risk="HIGH")
        validate_success(
            record_decision(ctx["plan"]["id"], ctx["reviewer"]["id"], "REJECT", rationale="no IACUC approval"),
            201,
        )
        project = get_project(ctx["project"]["id"])
        assert_project(project)
        assert project["registration_status"] == "WITHDRAWN", (
            "the plan rejection must cascade the project's registration_status to WITHDRAWN"
        )


class TestValidationPriorityOnDecisions:
    def test_state_error_beats_sod_on_early_decision(self, api):
        """PRD §2.8: "Every request passes through a single ordered validation
        pipeline, and the first failing check determines the error response."
        PRD §2.8: "**Priority 4 — state legality.** The target resource is in a
        state from which the requested transition is allowed; otherwise
        `ERR_INVALID_STATE` (409)."
        PRD §2.8: "**Priority 5 — segregation of duties.** An ethics reviewer
        must not be the project's own mentor, and a judge must not score a
        project against which a declared conflict exists; breaches report
        `ERR_SOD_VIOLATION` (422)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_ethics_decision
        """
        # Plan is only SUBMITTED (never began review) AND the reviewer id is the
        # project's own mentor: state (priority 4) fails before SoD (priority 5).
        ctx = setup_project_with_plan(human=True)
        mentor_id = ctx["mentor"]["id"]
        get_success_data(
            api_client.submit_research_plan(ctx["plan"]["id"], make_mentor_headers(mentor_id))
        )

        resp = record_decision(ctx["plan"]["id"], mentor_id, "APPROVE")
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_rejected_decision_leaves_no_trace(self, api):
        """PRD §2.8: "Every request passes through a single ordered validation
        pipeline, and the first failing check determines the error response."
        PRD §2.8: "**Priority 4 — state legality.** The target resource is in a
        state from which the requested transition is allowed; otherwise
        `ERR_INVALID_STATE` (409)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_ethics_decision
        """
        ctx = setup_project_with_plan(human=True)
        mentor_id = ctx["mentor"]["id"]
        get_success_data(
            api_client.submit_research_plan(ctx["plan"]["id"], make_mentor_headers(mentor_id))
        )

        validate_error(record_decision(ctx["plan"]["id"], mentor_id, "APPROVE"), ApiErrorId.ERR_INVALID_STATE)

        plan = get_plan(ctx["plan"]["id"])
        assert plan["status"] == "SUBMITTED", "a rejected decision request must not move the plan"
        reviews, meta = validate_paginated(
            api_client.list_ethics_reviews(fd_headers(), params={"research_plan_id": ctx["plan"]["id"]})
        )
        assert meta["total_count"] == 0, "a rejected decision request must not create an ethics review"
        assert reviews == []


class TestProjectSubmitEthicsGate:
    def test_submit_without_plan_rejected(self, api):
        """PRD §3.2: "if `involves_human_subjects` or `involves_animal_subjects`
        is true, the project must already have a research plan in `SUBMITTED`,
        `UNDER_REVIEW`, or `APPROVED` status — otherwise the submission is
        rejected with `ERR_RESEARCH_PLAN_REQUIRED`."

        Design: Difficulty/cross_entity_state_dependency/project_submit_gated_by_research_plan_state
        """
        ctx = setup_open_edition(name="XDep Edition", code="BME")
        project = register_project(
            ctx["edition"]["id"], ctx["category"]["id"], ctx["mentor"]["id"],
            title="HS", human=True,
        )
        resp = api_client.submit_project(project["id"], make_mentor_headers(ctx["mentor"]["id"]))
        validate_error(resp, ApiErrorId.ERR_RESEARCH_PLAN_REQUIRED, 422)

    def test_submit_succeeds_once_plan_submitted(self, api):
        """PRD §3.2: "if `involves_human_subjects` or `involves_animal_subjects`
        is true, the project must already have a research plan in `SUBMITTED`,
        `UNDER_REVIEW`, or `APPROVED` status — otherwise the submission is
        rejected with `ERR_RESEARCH_PLAN_REQUIRED`."
        PRD §3.2: "A successful submission stamps the project's `ethics_status`:
        `PENDING` when either subject flag is true, `NOT_REQUIRED` when neither
        is."

        Design: Difficulty/cross_entity_state_dependency/project_submit_gated_by_research_plan_state
        """
        ctx = setup_open_edition(name="XDep Edition", code="BME")
        mentor_id = ctx["mentor"]["id"]
        project = register_project(
            ctx["edition"]["id"], ctx["category"]["id"], mentor_id, title="HS", human=True
        )
        plan = get_success_data(
            api_client.create_research_plan(
                research_plan_payload(project["id"], plan_text="plan", risk_level="LOW"),
                make_mentor_headers(mentor_id),
            ),
            201,
        )
        get_success_data(api_client.submit_research_plan(plan["id"], make_mentor_headers(mentor_id)))

        submitted = validate_success(
            api_client.submit_project(project["id"], make_mentor_headers(mentor_id))
        )
        assert submitted["registration_status"] == "SUBMITTED"
        assert submitted["ethics_status"] == "PENDING", (
            "a human-subjects project must be stamped PENDING on submission"
        )


class TestDecisionGuards:
    def test_reviewer_must_not_be_project_mentor(self, api):
        """PRD §3.3: "the `reviewer_mentor_id` must differ from the parent
        project's `mentor_id`, or the decision is rejected with
        `ERR_SOD_VIOLATION`."

        Design: Corner/validations/sod_violation_reviewer_is_project_mentor
        """
        ctx = setup_plan_under_review(human=True)
        mentor_id = ctx["mentor"]["id"]

        resp = record_decision(ctx["plan"]["id"], mentor_id, "APPROVE")
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION, 422)

        plan = get_plan(ctx["plan"]["id"])
        assert plan["status"] == "UNDER_REVIEW", "a rejected decision must not move the plan"

    def test_revision_request_requires_rationale(self, api):
        """PRD §3.3: "for any `decision` other than `APPROVE`, the `rationale`
        must be non-empty, or the decision is rejected with
        `ERR_RATIONALE_REQUIRED`."

        Design: Corner/validations/rationale_required_on_revision_request
        """
        ctx = setup_plan_under_review(human=False, animal=True, plan_risk="HIGH")
        resp = record_decision(ctx["plan"]["id"], ctx["reviewer"]["id"], "REQUEST_REVISION", rationale="")
        validate_error(resp, ApiErrorId.ERR_RATIONALE_REQUIRED, 422)


class TestMentorOwnership:
    def test_mentor_cannot_submit_other_mentors_project(self, api):
        """PRD §3.2: "The acting mentor must own the project (`ERR_FORBIDDEN`
        otherwise)".
        PRD §2.1: "When an entity-backed role attempts to act on a resource it
        does not own — a mentor touching another mentor's project, a judge
        scoring another judge's assignment — the rejection is `ERR_FORBIDDEN`."

        Design: Corner/rbac/mentor_cannot_act_on_other_mentors_project
        """
        ctx = setup_open_edition(name="RBAC Edition")
        other = add_mentor(full_name="Mentor Two")
        project = register_project(
            ctx["edition"]["id"], ctx["category"]["id"], ctx["mentor"]["id"], title="OwnedP"
        )

        resp = api_client.submit_project(project["id"], make_mentor_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

        assert get_project(project["id"])["registration_status"] == "DRAFT"


class TestEthicsCascadeConsistency:
    def test_approve_visible_immediately_on_project(self, api):
        """PRD §3.3: "An `APPROVE` moves the plan `UNDER_REVIEW` → `APPROVED`,
        pins `approved_plan_version` to the plan's current `version` — a
        snapshot that goes stale if the plan's version later advances — and
        cascades onto the parent project, setting its `ethics_status` to
        `APPROVED` and incrementing the project's `version`".
        PRD §2.10: "Many operations deliberately mutate more than one entity at
        once, and all such cascades are atomic".

        Design: Corner/consistency_model/immediate_consistency_cascade_visible_same_request
        """
        ctx = setup_plan_under_review(human=True)
        review = validate_success(
            record_decision(ctx["plan"]["id"], ctx["reviewer"]["id"], "APPROVE"), 201
        )

        project = get_project(ctx["project"]["id"])
        assert project["ethics_status"] == "APPROVED", (
            "read-after-write: the project must show the cascaded ethics_status immediately"
        )
        fetched = validate_success(api_client.get_ethics_review(review["id"], er_headers()))
        assert fetched["id"] == review["id"]
        assert fetched["decision"] == "APPROVE"


class TestProjectReassignmentOcc:
    def test_stale_reassignment_rejected_then_fresh_succeeds(self, api):
        """PRD §2.7: "Updating a project requires `expected_project_version` to
        match the project's current `version`; a mismatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.2: "because an ethics decision can cascade a mutation onto the
        project, a reassignment prepared before that decision is rejected with
        `ERR_STALE_VERSION` rather than applied against a snapshot the client
        never saw."

        Design: Corner/cross_cutting_layers/occ_category_reassign_stale_project
        """
        ctx = setup_plan_under_review(human=True)
        mentor_id = ctx["mentor"]["id"]
        project = ctx["project"]
        edition_id = ctx["edition"]["id"]
        cat2 = add_category(edition_id, code="BHS", name="Behavioral")

        # Mentor's observed version, captured before the ethics decision.
        stale_version = project["version"]

        # The APPROVE decision cascades a mutation onto the project.
        validate_success(record_decision(ctx["plan"]["id"], ctx["reviewer"]["id"], "APPROVE"), 201)

        resp = api_client.update_project(
            project["id"],
            {"category_id": cat2["id"], "expected_project_version": stale_version},
            make_mentor_headers(mentor_id),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        fresh_version = get_project(project["id"])["version"]
        updated = validate_success(
            api_client.update_project(
                project["id"],
                {"category_id": cat2["id"], "expected_project_version": fresh_version},
                make_mentor_headers(mentor_id),
            )
        )
        assert updated["category_id"] == cat2["id"], (
            "retry with the fresh version must apply the reassignment"
        )
