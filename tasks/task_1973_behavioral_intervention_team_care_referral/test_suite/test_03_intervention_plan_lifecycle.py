"""Intervention planning: revision loop, supersedure, OCC guard, open-plan gate.

PRD §3.3 covers drafting, submit/return/approve, the single-ACTIVE-plan
invariant, and the OCC guard of §2.9.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    approve_plan,
    draft_plan,
    get_case_version,
    get_success_data,
    score_case,
    setup_case_in_intake,
    setup_case_plan_active,
    setup_case_triaged,
    setup_staff_group,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPlanRevisionLoop:
    def test_return_moves_plan_back_to_draft_with_note(self, api):
        """PRD §3.3: "Returning it for revision moves `PENDING_APPROVAL` →
        `DRAFT` and records the supplied `revision_note` on the plan; the
        draft-revise loop may repeat as needed."

        Design: Difficulty/non_linear_state_machine/intervention_plan_revision_loop
        """
        ctx = setup_staff_group()
        setup_case_triaged(ctx, external_ref="S5002", category="ACADEMIC_DISTRESS")
        plan = draft_plan(ctx, ctx["case_id"], objectives=["tutoring"],
                          success_criteria="grades recover")
        get_success_data(api.submit_intervention_plan(plan["id"], ctx["cm_headers"]))
        returned = validate_success(
            api.return_intervention_plan(
                plan["id"], {"revision_note": "add measurable objectives"},
                ctx["chair_headers"],
            )
        )
        assert returned["status"] == "DRAFT"
        assert returned["revision_note"] == "add measurable objectives"

    def test_resubmit_then_approve_activates_plan_and_case(self, api):
        """PRD §3.3: "Approval moves `PENDING_APPROVAL` → `ACTIVE` and is the
        more heavily guarded step, evaluated in order: the plan must be
        `PENDING_APPROVAL` (`ERR_PLAN_NOT_PENDING_APPROVAL`), the case must be
        in `PLAN_DRAFTING` or `PLAN_ACTIVE`
        (`ERR_CASE_STATE_BLOCKS_PLAN_APPROVAL`), and — the §2.8 segregation
        rule — the approver's `X-User-ID` must differ from the plan's
        `drafted_by` (`ERR_SEGREGATION_OF_DUTIES`)."
        PRD §3.3: "The case moves `PLAN_DRAFTING` → `PLAN_ACTIVE` — a no-op
        when the approval ratified a revision on an already-`PLAN_ACTIVE` case
        — and its `version` increments by one."

        Design: Difficulty/non_linear_state_machine/intervention_plan_revision_loop
        """
        ctx = setup_staff_group()
        setup_case_triaged(ctx, external_ref="S5003", category="ACADEMIC_DISTRESS")
        plan = draft_plan(ctx, ctx["case_id"])
        get_success_data(api.submit_intervention_plan(plan["id"], ctx["cm_headers"]))
        get_success_data(
            api.return_intervention_plan(
                plan["id"], {"revision_note": "add measurable objectives"},
                ctx["chair_headers"],
            )
        )
        resubmitted = validate_success(
            api.submit_intervention_plan(plan["id"], ctx["cm_headers"])
        )
        assert resubmitted["status"] == "PENDING_APPROVAL"
        approved = validate_success(
            api.approve_intervention_plan(plan["id"], ctx["chair_headers"])
        )
        assert approved["status"] == "ACTIVE"
        case = get_success_data(api.get_care_case(ctx["case_id"], ctx["chair_headers"]))
        assert case["status"] == "PLAN_ACTIVE"


class TestSingleActivePlanInvariant:
    def test_approving_revision_supersedes_prior_active_plan(self, api):
        """PRD §3.3: "The approved plan becomes `ACTIVE`, and if another plan
        for the case was `ACTIVE`, that plan is superseded to `SUPERSEDED`
        (terminal) with the new plan's `supersedes_plan_id` recording its
        `id`."

        Design: Difficulty/compensating_invariant/single_active_plan_per_case
        """
        ctx = setup_staff_group()
        setup_case_plan_active(ctx, external_ref="S1101", category="ACADEMIC_DISTRESS")
        p1_id = ctx["plan"]["id"]
        plans, meta = validate_paginated(
            api.list_intervention_plans(
                ctx["chair_headers"], params={"case_id": ctx["case_id"], "status": "ACTIVE"}
            )
        )
        assert meta["total_count"] == 1
        assert plans[0]["id"] == p1_id
        p2 = draft_plan(ctx, ctx["case_id"], objectives=["o2"], success_criteria="s2")
        get_success_data(api.submit_intervention_plan(p2["id"], ctx["cm_headers"]))
        approved2 = validate_success(
            api.approve_intervention_plan(p2["id"], ctx["chair_headers"])
        )
        assert approved2["status"] == "ACTIVE"
        assert approved2["supersedes_plan_id"] == p1_id
        p1_after = validate_success(api.get_intervention_plan(p1_id, ctx["chair_headers"]))
        assert p1_after["status"] == "SUPERSEDED"

    def test_exactly_one_active_plan_after_supersede(self, api):
        """PRD §3.3: "The approved plan becomes `ACTIVE`, and if another plan
        for the case was `ACTIVE`, that plan is superseded to `SUPERSEDED`
        (terminal) with the new plan's `supersedes_plan_id` recording its
        `id`."

        Design: Difficulty/compensating_invariant/single_active_plan_per_case
        """
        ctx = setup_staff_group()
        setup_case_plan_active(ctx, external_ref="S1101B")
        p2 = draft_plan(ctx, ctx["case_id"], objectives=["o2"], success_criteria="s2")
        get_success_data(api.submit_intervention_plan(p2["id"], ctx["cm_headers"]))
        approve_plan(ctx, p2["id"])
        plans, meta = validate_paginated(
            api.list_intervention_plans(
                ctx["chair_headers"], params={"case_id": ctx["case_id"], "status": "ACTIVE"}
            )
        )
        assert meta["total_count"] == 1
        assert plans[0]["id"] == p2["id"]


class TestOpenPlanGate:
    def test_second_draft_while_draft_open_rejected(self, api):
        """PRD §3.3: "if the case already has a plan in `DRAFT` or
        `PENDING_APPROVAL`, the draft is refused with `ERR_OPEN_PLAN_EXISTS`
        (409) — one open drafting effort per case at a time."
        PRD §3.3: "a case in any other state besides `TRIAGED` or
        `PLAN_ACTIVE` yields `ERR_CASE_NOT_PLAN_ACTIVE`" — so the open-plan
        exclusion (§2.10 rank 9) is reachable only from `PLAN_ACTIVE`, where
        drafting a revision leaves the case `PLAN_ACTIVE` ("a case already
        `PLAN_ACTIVE` stays there") and the state gate (rank 5) passes.

        Design: Corner/errors/open_plan_exists_rejected
        """
        ctx = setup_staff_group()
        setup_case_plan_active(ctx, external_ref="S0025", category="ACADEMIC_DISTRESS")
        # First revision draft on the PLAN_ACTIVE case: plan DRAFT, case stays
        # PLAN_ACTIVE, so the next draft reaches the open-plan exclusion.
        draft_plan(ctx, ctx["case_id"], objectives=["o1"], success_criteria="s1")
        fresh_version = get_case_version(ctx, ctx["case_id"])
        resp = api.create_intervention_plan(
            {
                "case_id": ctx["case_id"],
                "expected_case_version": fresh_version,
                "objectives": ["o2"],
                "success_criteria": "s2",
            },
            ctx["cm_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_OPEN_PLAN_EXISTS)


class TestPlanApproveCaseStateGate:
    def test_approve_blocked_when_case_in_mandated_assessment(self, api):
        """PRD §3.3: "Approval moves `PENDING_APPROVAL` → `ACTIVE` and is the
        more heavily guarded step, evaluated in order: the plan must be
        `PENDING_APPROVAL` (`ERR_PLAN_NOT_PENDING_APPROVAL`), the case must be
        in `PLAN_DRAFTING` or `PLAN_ACTIVE`
        (`ERR_CASE_STATE_BLOCKS_PLAN_APPROVAL`), and — the §2.8 segregation
        rule — the approver's `X-User-ID` must differ from the plan's
        `drafted_by` (`ERR_SEGREGATION_OF_DUTIES`)."

        Design: Difficulty/cross_entity_state_dependency/plan_approve_requires_case_plan_drafting
        """
        ctx = setup_staff_group(evaluator=True)
        setup_case_plan_active(ctx, external_ref="S9001", category="SELF_HARM_RISK",
                               dims=(20, 20, 5, 5))
        p1_id = ctx["plan"]["id"]
        p2 = draft_plan(ctx, ctx["case_id"], objectives=["o2"], success_criteria="s2")
        get_success_data(api.submit_intervention_plan(p2["id"], ctx["cm_headers"]))
        # Move the case to MANDATED_ASSESSMENT while p2 is PENDING_APPROVAL.
        assessment = get_success_data(
            api.create_mandated_assessment(
                {
                    "case_id": ctx["case_id"],
                    "evaluator_id": ctx["ev"]["id"],
                    "due_at": "2026-08-10T00:00:00Z",
                    "rationale": "escalation",
                },
                ctx["chair_headers"],
            )
        )
        assert assessment["status"] == "SCHEDULED"
        resp = api.approve_intervention_plan(p2["id"], ctx["chair_headers"])
        validate_error(resp, ApiErrorId.ERR_CASE_STATE_BLOCKS_PLAN_APPROVAL)

    def test_blocked_approval_leaves_plans_unchanged(self, api):
        """PRD §3.3: "Approval moves `PENDING_APPROVAL` → `ACTIVE` and is the
        more heavily guarded step, evaluated in order: the plan must be
        `PENDING_APPROVAL` (`ERR_PLAN_NOT_PENDING_APPROVAL`), the case must be
        in `PLAN_DRAFTING` or `PLAN_ACTIVE`
        (`ERR_CASE_STATE_BLOCKS_PLAN_APPROVAL`), and — the §2.8 segregation
        rule — the approver's `X-User-ID` must differ from the plan's
        `drafted_by` (`ERR_SEGREGATION_OF_DUTIES`)."

        Design: Difficulty/cross_entity_state_dependency/plan_approve_requires_case_plan_drafting
        """
        ctx = setup_staff_group(evaluator=True)
        setup_case_plan_active(ctx, external_ref="S9001B", category="SELF_HARM_RISK",
                               dims=(20, 20, 5, 5))
        p1_id = ctx["plan"]["id"]
        p2 = draft_plan(ctx, ctx["case_id"], objectives=["o2"], success_criteria="s2")
        get_success_data(api.submit_intervention_plan(p2["id"], ctx["cm_headers"]))
        get_success_data(
            api.create_mandated_assessment(
                {
                    "case_id": ctx["case_id"],
                    "evaluator_id": ctx["ev"]["id"],
                    "due_at": "2026-08-10T00:00:00Z",
                    "rationale": "escalation",
                },
                ctx["chair_headers"],
            )
        )
        validate_error(
            api.approve_intervention_plan(p2["id"], ctx["chair_headers"]),
            ApiErrorId.ERR_CASE_STATE_BLOCKS_PLAN_APPROVAL,
        )
        p2_after = validate_success(api.get_intervention_plan(p2["id"], ctx["chair_headers"]))
        assert p2_after["status"] == "PENDING_APPROVAL"
        p1_after = validate_success(api.get_intervention_plan(p1_id, ctx["chair_headers"]))
        assert p1_after["status"] == "ACTIVE"


class TestScoringAfterTerminalClosure:
    def test_closed_case_rejects_further_scoring(self, api):
        """PRD §3.8: "Closure is the case's only terminal transition and is
        deliberately hard to reach."
        PRD §3.2: "State must agree too: scoring requires the case in `INTAKE`
        (for `INITIAL`) or `TRIAGED` (for `REASSESSMENT`), with anything else
        rejected as `ERR_CASE_NOT_TRIAGEABLE` (HTTP 409)."

        Design: Corner/state_machines/closed_case_terminal_lockdown_rejects_scoring
        """
        from test_helpers import setup_case_closed

        ctx = setup_staff_group()
        setup_case_closed(ctx, external_ref="S0007")
        assert ctx["closed_case"]["status"] == "CLOSED"
        resp = api.create_risk_scoring(
            {
                "case_id": ctx["case_id"],
                "mode": "REASSESSMENT",
                "harm_to_self": 10,
                "harm_to_others": 10,
                "academic_disruption": 10,
                "substance_involvement": 10,
                "rationale": "post-close",
            },
            ctx["chair_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_TRIAGEABLE)
