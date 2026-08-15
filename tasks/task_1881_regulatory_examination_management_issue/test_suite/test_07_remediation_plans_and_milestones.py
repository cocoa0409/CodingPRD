"""Remediation plans and milestones: sequence allocation, revision loop,
plan-version monotonicity, ACTIVE-plan gating, OCC, certification (PRD §3.6)."""
import pytest

from test_helpers import (
    RAM,
    ApiErrorId,
    create_milestone_payload,
    create_plan_with_milestone,
    create_remediation_plan_payload,
    drive_plan_to_status,
    get_issue,
    get_plan,
    setup_exam_remediation,
    validate_error,
    validate_paginated,
    validate_success,
)


def _setup_active_plan_without_seq1(api):
    """ACTIVE plan whose bootstrap milestone took explicit sequence_index 2,
    leaving index 1 open for gap-fill assertions."""
    ctx = setup_exam_remediation()
    bundle = create_plan_with_milestone(
        ctx["issue"]["id"], ctx["owner_headers"],
        milestone_overrides={"sequence_index": 2})
    ctx["plan"] = drive_plan_to_status(bundle["plan"]["id"], "ACTIVE", ctx)
    return ctx


def _add_milestone(api, plan_id, owner_headers, **overrides):
    payload = create_milestone_payload(
        expected_plan_version=get_plan(plan_id)["version"], **overrides)
    return api.create_remediation_milestone(plan_id, payload, owner_headers)


class TestMilestoneSequenceAllocation:
    def test_explicit_then_omitted_sequence_index_assigns_max_plus_one(self, api):
        """PRD §3.6: "The sequence index is a strictly increasing integer, at
        least 1, unique within its plan. When the payload omits it, the server
        assigns the highest existing index on the plan plus one — or 1 when the
        plan has none yet; when the payload supplies an index already in use on
        that plan, the create is rejected with `ERR_DUPLICATE_KEY`."

        Explicit 5 is honored; the next omitted index is max(2, 5) + 1 = 6 —
        not 1 and not gap-filling.

        Design: Difficulty/combinatorial_formula/milestone_sequence_allocation_ordering
        """
        ctx = _setup_active_plan_without_seq1(api)
        m_explicit = validate_success(
            _add_milestone(api, ctx["plan"]["id"], ctx["owner_headers"],
                           milestone_name="explicit-5", sequence_index=5,
                           due_date="2026-08-10T00:00:00Z"), 201)
        assert m_explicit["sequence_index"] == 5
        m_auto = validate_success(
            _add_milestone(api, ctx["plan"]["id"], ctx["owner_headers"],
                           milestone_name="auto-next", due_date="2026-08-15T00:00:00Z"),
            201)
        assert m_auto["sequence_index"] == 6, "omitted index = highest existing + 1"

    def test_explicit_gap_fill_allowed_when_unique(self, api):
        """PRD §3.6: "The sequence index is a strictly increasing integer, at
        least 1, unique within its plan. When the payload omits it, the server
        assigns the highest existing index on the plan plus one — or 1 when the
        plan has none yet; when the payload supplies an index already in use on
        that plan, the create is rejected with `ERR_DUPLICATE_KEY`."

        Index 1 is unused on this plan, so supplying it explicitly succeeds.

        Design: Difficulty/combinatorial_formula/milestone_sequence_allocation_ordering
        """
        ctx = _setup_active_plan_without_seq1(api)
        validate_success(
            _add_milestone(api, ctx["plan"]["id"], ctx["owner_headers"],
                           milestone_name="explicit-5", sequence_index=5), 201)
        validate_success(
            _add_milestone(api, ctx["plan"]["id"], ctx["owner_headers"],
                           milestone_name="auto-next"), 201)
        m_gap = validate_success(
            _add_milestone(api, ctx["plan"]["id"], ctx["owner_headers"],
                           milestone_name="fill-gap", sequence_index=1), 201)
        assert m_gap["sequence_index"] == 1
        roster, _ = validate_paginated(
            api.list_remediation_milestones(ctx["plan"]["id"], RAM,
                                            params={"limit": 100}))
        assert {1, 2, 5, 6} <= {m["sequence_index"] for m in roster}


class TestPlanRevisionLoop:
    def _setup_rejected_plan(self, api):
        ctx = setup_exam_remediation()
        bundle = create_plan_with_milestone(ctx["issue"]["id"], ctx["owner_headers"])
        submit = api.submit_remediation_plan(
            bundle["plan"]["id"], ctx["owner_headers"])
        validate_success(submit)
        reject = api.reject_remediation_plan(
            bundle["plan"]["id"], {"rejection_reason": "incomplete root cause"},
            ctx["reviewer_headers"])
        validate_success(reject)
        ctx["plan"] = get_plan(bundle["plan"]["id"])
        return ctx

    def test_rejected_plan_revises_back_to_draft(self, api):
        """PRD §3.6: "Rejection requires a non-empty `rejection_reason` and
        moves the plan to `REJECTED`, from which the owner may revise it
        straight back to `DRAFT` for another attempt."

        Design: Difficulty/non_linear_state_machine/remediation_plan_revision_loop_and_supersede
        """
        ctx = self._setup_rejected_plan(api)
        assert ctx["plan"]["status"] == "REJECTED"
        revised = validate_success(
            api.revise_remediation_plan(ctx["plan"]["id"], ctx["owner_headers"]))
        assert revised["status"] == "DRAFT", "REJECTED -> DRAFT revision loop"

    def test_revised_plan_completes_cycle_back_to_active(self, api):
        """PRD §3.6: "Rejection requires a non-empty `rejection_reason` and
        moves the plan to `REJECTED`, from which the owner may revise it
        straight back to `DRAFT` for another attempt."
        PRD §3.6: "Approval stamps `approved_at`, moves the plan `SUBMITTED` →
        `APPROVED`, and — when the issue is still `OPEN` — walks the issue
        `OPEN` → `REMEDIATION_PLANNED`; both the plan's and the issue's
        `version` increment."
        PRD §3.6: "Activation moves an `APPROVED` plan to `ACTIVE` provided the
        issue stands `REMEDIATION_PLANNED`, `IN_PROGRESS`, or `OVERDUE`."

        After revision, the same plan re-submits, re-approves (walking the issue
        OPEN -> REMEDIATION_PLANNED), and activates.

        Design: Difficulty/non_linear_state_machine/remediation_plan_revision_loop_and_supersede
        """
        ctx = self._setup_rejected_plan(api)
        validate_success(api.revise_remediation_plan(ctx["plan"]["id"],
                                                     ctx["owner_headers"]))
        plan = drive_plan_to_status(ctx["plan"]["id"], "ACTIVE", ctx)
        assert plan["status"] == "ACTIVE"
        issue = get_issue(ctx["issue"]["id"])
        assert issue["status"] == "REMEDIATION_PLANNED"


class TestPlanVersionMonotonicInvariant:
    def _setup_rejected_v1(self, api):
        ctx = setup_exam_remediation()
        bundle = create_plan_with_milestone(ctx["issue"]["id"], ctx["owner_headers"])
        validate_success(api.submit_remediation_plan(bundle["plan"]["id"],
                                                     ctx["owner_headers"]))
        validate_success(api.reject_remediation_plan(
            bundle["plan"]["id"], {"rejection_reason": "r"}, ctx["reviewer_headers"]))
        ctx["plan_v1"] = bundle["plan"]
        return ctx

    def test_plan_version_increments_per_issue(self, api):
        """PRD §3.6: "the server stamps it with a `plan_version`: a one-based
        superseding index computed as the count of prior plans on the same
        issue plus one"

        The first plan is stamped 1; a second plan on the same issue is stamped
        exactly one higher.

        Design: Difficulty/compensating_invariant/plan_version_monotonic_invariant_under_revise_cycle
        """
        ctx = self._setup_rejected_v1(api)
        assert ctx["plan_v1"]["plan_version"] == 1
        validate_success(api.revise_remediation_plan(ctx["plan_v1"]["id"],
                                                     ctx["owner_headers"]))
        v2 = validate_success(
            api.create_remediation_plan(
                ctx["issue"]["id"],
                create_remediation_plan_payload(owner_user_id=ctx["officer"]["id"]),
                ctx["owner_headers"]),
            201)
        assert v2["plan_version"] == 2, "exactly +1 over the previous maximum"

    def test_revise_preserves_plan_version_and_roster(self, api):
        """PRD §3.6: "Rejection requires a non-empty `rejection_reason` and
        moves the plan to `REJECTED`, from which the owner may revise it
        straight back to `DRAFT` for another attempt."
        PRD §3.6: "the server stamps it with a `plan_version`: a one-based
        superseding index computed as the count of prior plans on the same
        issue plus one"

        The revise cycle returns the same plan resource to DRAFT without
        consuming a new plan_version; no plan is deleted by reject/revise.

        Design: Difficulty/compensating_invariant/plan_version_monotonic_invariant_under_revise_cycle
        """
        ctx = self._setup_rejected_v1(api)
        validate_success(api.revise_remediation_plan(ctx["plan_v1"]["id"],
                                                     ctx["owner_headers"]))
        v1_after = get_plan(ctx["plan_v1"]["id"])
        assert v1_after["plan_version"] == 1, "revise does not bump plan_version"
        assert v1_after["status"] == "DRAFT"
        validate_success(
            api.create_remediation_plan(
                ctx["issue"]["id"],
                create_remediation_plan_payload(owner_user_id=ctx["officer"]["id"]),
                ctx["owner_headers"]),
            201)
        plans, meta = validate_paginated(
            api.list_remediation_plans(ctx["issue"]["id"], RAM))
        assert meta["total_count"] == 2, "reject/revise never deletes a plan"


class TestMilestoneStartRequiresActivePlan:
    def test_start_blocked_when_plan_draft(self, api):
        """PRD §3.6: "Starting a milestone requires it to be `PENDING`, requires
        its parent plan to be `ACTIVE` — a start or completion attempted while
        the plan is anything else is rejected with `ERR_NO_ACTIVE_PLAN`"

        Design: Difficulty/cross_entity_state_dependency/milestone_start_blocked_when_plan_not_active
        """
        ctx = setup_exam_remediation()
        bundle = create_plan_with_milestone(ctx["issue"]["id"], ctx["owner_headers"])
        assert bundle["plan"]["status"] == "DRAFT"
        resp = api.start_remediation_milestone(
            bundle["milestone"]["id"], ctx["owner_headers"])
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_PLAN)
        milestone = validate_success(
            api.get_remediation_milestone(bundle["milestone"]["id"], RAM))
        assert milestone["status"] == "PENDING"

    @pytest.mark.parametrize("plan_state", ["SUBMITTED", "APPROVED"])
    def test_start_blocked_when_plan_submitted_or_approved(self, api, plan_state):
        """PRD §3.6: "Starting a milestone requires it to be `PENDING`, requires
        its parent plan to be `ACTIVE` — a start or completion attempted while
        the plan is anything else is rejected with `ERR_NO_ACTIVE_PLAN`"

        The plan standing SUBMITTED (respectively APPROVED) is "anything else"
        than ACTIVE, so the start is rejected.

        Design: Difficulty/cross_entity_state_dependency/milestone_start_blocked_when_plan_not_active
        """
        ctx = setup_exam_remediation()
        bundle = create_plan_with_milestone(ctx["issue"]["id"], ctx["owner_headers"])
        drive_plan_to_status(bundle["plan"]["id"], plan_state, ctx)
        resp = api.start_remediation_milestone(
            bundle["milestone"]["id"], ctx["owner_headers"])
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_PLAN)


class TestMilestoneOCC:
    def test_stale_plan_version_rejected_on_milestone_create(self, api):
        """PRD §2.7: "adding a milestone to a remediation plan
        (`POST /regulatory-exams/remediation-plans/{id}/milestones`) requires
        `expected_plan_version`, the client-observed `version` of the plan"
        PRD §2.7: "In all three cases the expected-version field is
        non-optional, and a mismatch with the parent entity's current `version`
        is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        The first milestone creation advances the plan version; the second
        creation carries the stale observed version.

        Design: Corner/endpoints/occ_stale_version_on_milestone_create
        """
        ctx = setup_exam_remediation()
        plan = validate_success(
            api.create_remediation_plan(
                ctx["issue"]["id"],
                create_remediation_plan_payload(owner_user_id=ctx["officer"]["id"]),
                ctx["owner_headers"]),
            201)
        observed_v = plan["version"]
        validate_success(
            _add_milestone(api, plan["id"], ctx["owner_headers"],
                           milestone_name="m1"), 201)
        resp = api.create_remediation_milestone(
            plan["id"],
            create_milestone_payload(expected_plan_version=observed_v,
                                     milestone_name="m2",
                                     due_date="2026-08-15T00:00:00Z"),
            ctx["owner_headers"])
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestMriaCertificationGate:
    def test_mria_plan_approval_requires_l3_reviewer(self, api):
        """PRD §2.10: "Whenever the underlying issue carries `classification`
        `MRIA`, the acting reviewer's `certification_level` must be `L3`; for an
        `MRA`, any of `L1`, `L2`, or `L3` suffices. The gate applies to
        remediation-plan approval and to closure-request approval, and a
        shortfall is rejected with `ERR_CERTIFICATION_INSUFFICIENT` (HTTP 422)."

        The plan belongs to an MRIA issue and the acting reviewer holds only L1.

        Design: Corner/validations/mria_approve_requires_l3_reviewer
        """
        ctx = setup_exam_remediation(
            issue_overrides={"issue_ref": "MRIA-CG", "classification": "MRIA",
                             "severity": "CRITICAL"},
            reviewer_level="L1")
        bundle = create_plan_with_milestone(ctx["issue"]["id"], ctx["owner_headers"])
        validate_success(api.submit_remediation_plan(bundle["plan"]["id"],
                                                     ctx["owner_headers"]))
        resp = api.approve_remediation_plan(
            bundle["plan"]["id"], ctx["reviewer_headers"])
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_INSUFFICIENT)
