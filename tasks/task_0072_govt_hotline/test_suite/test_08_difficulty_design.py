"""High-difficulty coverage. Every PRD rule cluster from
SCAFFOLD_DIFFICULTY_DESIGN.yaml is exercised by at least two dedicated
tests, each pinning the underlying PRD sentence verbatim.

Each test docstring tags itself with `# difficulty: <rule>/<instance>`
so the coverage audit can confirm full coverage of the priority queue.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    DISP, HO, PA, SA, SUP,
    accept_assignment,
    advance_clock,
    align_clock_to_business_day_start,
    classify,
    create_category_rule,
    create_department,
    create_handler,
    dispatch,
    expected_difficulty_score,
    find_lead_assignment,
    find_supporting_assignments,
    get_department,
    get_handler,
    get_work_order,
    list_audit_logs,
    list_supervision_tasks,
    list_surveys,
    list_sync_events,
    make_department_handler_headers,
    pause,
    pause_work_order_payload,
    register_work_order,
    resolve,
    resolve_work_order_payload,
    respond_survey_payload,
    resume,
    setup_all_opinions_submitted,
    setup_followed_up,
    setup_for_difficulty_dual_variant,
    setup_in_progress,
    setup_paused_with_seconds,
    setup_resolved,
    setup_routing_world,
    setup_supporting_accepted,
    setup_three_resolved_with_surveys,
    submit_opinion,
    unique_jurisdiction_code,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import list_surveys as _list_surveys  # noqa


# ===========================================================================
# Rule 1 — Dual-variant calculations across different entity domains
# ===========================================================================
class TestRule1DualVariantCalculations:
    """Rule 1 (dual_variant_calc): difficulty_score registration vs
    post-classification variants; satisfaction_index department vs
    handler variants."""

    # ---- difficulty: dual_variant_calc / difficulty_score_registration_vs_post_classification
    def test_registration_score_uses_joint_factor_zero(self, api):
        """PRD §3.2: 'plus a joint factor of 0 (because at registration
        the case has not yet been classified and joint_handling
        therefore defaults to false).'

        For NORMAL (weight=1) + base=2 + joint=0 = 3.

        difficulty: dual_variant_calc/difficulty_score_registration_vs_post_classification
        """
        world, wo = setup_for_difficulty_dual_variant(
            urgency="NORMAL", difficulty_base=2,
        )
        assert wo["difficulty_score"] == 3
        assert wo["joint_handling"] is False

    # ---- difficulty: dual_variant_calc / difficulty_score_registration_vs_post_classification
    def test_post_classification_score_adds_joint_factor_two(self, api):
        """PRD §3.3: 'the difficulty score is then recomputed under the
        post-classification form: the same formula as registration, but
        with the joint factor set to 2 when joint_handling is now true
        and 0 when it is still false.'

        For NORMAL (weight=1) + base=2 + joint=2 = 5 (strictly larger
        than the registration-variant value of 3 for the same inputs).

        difficulty: dual_variant_calc/difficulty_score_registration_vs_post_classification
        """
        world, wo = setup_for_difficulty_dual_variant(
            urgency="NORMAL", difficulty_base=2,
        )
        classified = classify(wo["id"])
        assert classified["joint_handling"] is True
        assert classified["difficulty_score"] == 5

    # ---- difficulty: dual_variant_calc / satisfaction_index_department_vs_handler_variant
    def test_satisfaction_index_department_aggregate(self, api):
        """PRD §3.14: 'when grouped by department, the universe is
        narrowed to work orders whose lead_department_id matches the
        grouping key.'

        Scores 5, 1 for handler A and 4 for handler B → department
        mean = (5+1+4)/3 ≈ 3.33.

        difficulty: dual_variant_calc/satisfaction_index_department_vs_handler_variant
        """
        world = setup_three_resolved_with_surveys(
            scores_for_handler_a=[5, 1],
            scores_for_handler_b=[4],
        )
        resp = api.stats_satisfaction(PA, params={
            "group_by": "department",
            "department_id": world["lead_department"]["id"],
        })
        data = validate_success(resp)
        # Tolerant of containing-shape variability.
        index = (
            data.get("satisfaction_index")
            if isinstance(data, dict) else None
        )
        if index is None and isinstance(data, dict):
            # Fall back to nested groups list.
            groups = data.get("groups") or data.get("results") or []
            if groups:
                index = groups[0].get("satisfaction_index")
        assert index is not None, (
            "Response must surface satisfaction_index for the department"
        )
        assert abs(float(index) - 3.33) < 0.005, (
            f"PRD §3.14: divide-then-round → 3.33; got {index}"
        )

    # ---- difficulty: dual_variant_calc / satisfaction_index_department_vs_handler_variant
    def test_satisfaction_index_handler_aggregate(self, api):
        """PRD §3.14: 'when grouped by handler, the universe is narrowed
        to work orders whose lead DepartmentAssignment.handler_id
        matches — the two variants can yield genuinely different
        numbers because a handler typically holds only a slice of their
        department's work orders.'

        Scores 5 and 1 for handler A (mean = 3.00) — distinct from the
        department aggregate (3.33) above.

        difficulty: dual_variant_calc/satisfaction_index_department_vs_handler_variant
        """
        world = setup_three_resolved_with_surveys(
            scores_for_handler_a=[5, 1],
            scores_for_handler_b=[4],
        )
        resp = api.stats_satisfaction(PA, params={
            "group_by": "handler",
            "handler_id": world["handler_a"]["id"],
        })
        data = validate_success(resp)
        index = (
            data.get("satisfaction_index")
            if isinstance(data, dict) else None
        )
        if index is None and isinstance(data, dict):
            groups = data.get("groups") or data.get("results") or []
            if groups:
                index = groups[0].get("satisfaction_index")
        assert index is not None
        assert abs(float(index) - 3.00) < 0.005, (
            f"PRD §3.14: handler-variant mean = 3.00; got {index}"
        )


# ===========================================================================
# Rule 2 — Combinatorial formulas (clamp + rounding-order)
# ===========================================================================
class TestRule2CombinatorialFormula:
    """Rule 2 (combinatorial_formula): difficulty clamp at 10; divide-
    then-round vs round-then-divide in satisfaction_index."""

    # ---- difficulty: combinatorial_formula / difficulty_score_threecomponent_clamp
    def test_difficulty_clamps_to_ten_at_saturation(self, api):
        """PRD §3.12: 'The unclamped sum is then constrained to the
        closed range 1 to 10 by the larger of 1 and the smaller of 10
        and the raw sum.'

        CRITICAL(5) + base=4 + joint=2 = 11 → clamped to 10.

        difficulty: combinatorial_formula/difficulty_score_threecomponent_clamp
        """
        world = setup_routing_world(num_supporting=1, difficulty_base=4)
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
            urgency="CRITICAL",
        )
        classified = classify(wo["id"])
        assert classified["difficulty_score"] == 10

    # ---- difficulty: combinatorial_formula / difficulty_score_threecomponent_clamp
    def test_difficulty_clamps_two_distinct_oversums_to_ten(self, api):
        """PRD §3.12: 'a case with a category-base difficulty of 5 and
        an urgency weight of 5 (CRITICAL) and joint handling will land
        at 10, not 12.'

        Two cases with raw sums 11 and 12 both observe 10 — saturation
        observable through identical reported scores.

        difficulty: combinatorial_formula/difficulty_score_threecomponent_clamp
        """
        w1 = setup_routing_world(num_supporting=1, difficulty_base=4)
        wo1 = register_work_order(
            jurisdiction_code=w1["jurisdiction_code"],
            category_code=w1["category_rule"]["category_code"],
            sub_category_code=w1["category_rule"]["sub_category_code"],
            urgency="CRITICAL",
        )
        c1 = classify(wo1["id"])
        w2 = setup_routing_world(num_supporting=1, difficulty_base=5)
        wo2 = register_work_order(
            jurisdiction_code=w2["jurisdiction_code"],
            category_code=w2["category_rule"]["category_code"],
            sub_category_code=w2["category_rule"]["sub_category_code"],
            urgency="CRITICAL",
        )
        c2 = classify(wo2["id"])
        assert c1["difficulty_score"] == 10 == c2["difficulty_score"]

    # ---- difficulty: combinatorial_formula / satisfaction_index_divide_then_round
    def test_satisfaction_index_divides_first_then_rounds_two_decimals(self, api):
        """PRD §3.14: 'The contributions are summed, divided by the
        count of work orders in the universe at full float precision,
        and rounded half-up to 2 decimal places at the very end. The
        order of operations is divide-then-round, never
        round-per-row-then-divide.'

        Scores 5, 4, 1 → mean = 10/3 = 3.3333… → round_half_up(_, 2)
        = 3.33. Round-per-row-then-divide would yield 3.30 or 3.34.

        difficulty: combinatorial_formula/satisfaction_index_divide_then_round
        """
        world = setup_three_resolved_with_surveys(
            scores_for_handler_a=[5, 4, 1], scores_for_handler_b=[],
        )
        resp = api.stats_satisfaction(PA, params={
            "group_by": "department",
            "department_id": world["lead_department"]["id"],
        })
        data = validate_success(resp)
        index = (
            data.get("satisfaction_index")
            if isinstance(data, dict) else None
        )
        if index is None and isinstance(data, dict):
            groups = data.get("groups") or data.get("results") or []
            if groups:
                index = groups[0].get("satisfaction_index")
        assert index is not None
        assert abs(float(index) - 3.33) < 0.005, (
            f"PRD §3.14: divide-then-round at 2dp gives 3.33; got {index}"
        )

    # ---- difficulty: combinatorial_formula / satisfaction_index_divide_then_round
    def test_satisfaction_index_two_equal_scores_no_rounding(self, api):
        """PRD §3.14: 'rounded half-up to 2 decimal places at the very
        end.'

        Scores 4 and 2 → mean = 6/2 = 3.00 (no rounding needed; checks
        the precision/formatting layer).

        difficulty: combinatorial_formula/satisfaction_index_divide_then_round
        """
        world = setup_three_resolved_with_surveys(
            scores_for_handler_a=[4, 2], scores_for_handler_b=[],
        )
        resp = api.stats_satisfaction(PA, params={
            "group_by": "department",
            "department_id": world["lead_department"]["id"],
        })
        data = validate_success(resp)
        index = (
            data.get("satisfaction_index")
            if isinstance(data, dict) else None
        )
        if index is None and isinstance(data, dict):
            groups = data.get("groups") or data.get("results") or []
            if groups:
                index = groups[0].get("satisfaction_index")
        assert index is not None
        assert abs(float(index) - 3.00) < 0.005


# ===========================================================================
# Rule 3 — Non-linear state machine
# ===========================================================================
class TestRule3NonLinearStateMachine:
    """Rule 3 (non_linear_state_machine): WorkOrder cycle via REOPEN;
    DepartmentAssignment branching from ACCEPTED."""

    # ---- difficulty: non_linear_state_machine / work_order_revision_cycle_via_reopen
    def test_work_order_can_re_traverse_resolve_after_reopen(self, api):
        """PRD §3.10: 'The side-effects move the work order's status to
        REOPENED, reset the existing lead DepartmentAssignment back to
        stage_status equal to DISPATCHED while clearing its handler_id
        and accepted_at to null... A subsequent accept on the lead
        assignment moves the assignment back to ACCEPTED and the work
        order back to IN_PROGRESS via the same accept transition as
        before.'

        difficulty: non_linear_state_machine/work_order_revision_cycle_via_reopen
        """
        world = setup_followed_up(survey_score=1)
        wo_id = world["work_order"]["id"]
        # Reopen
        resp = api.reopen_work_order(wo_id, HO)
        validate_success(resp)
        # Re-accept LEAD
        lead = find_lead_assignment(wo_id)
        accept_assignment(wo_id, lead["id"], world["lead_handler"])
        wo = get_work_order(wo_id)
        assert wo["status"] == "IN_PROGRESS"
        # Resolve again
        resolve(wo_id, handler=world["lead_handler"],
                resolution_summary="second resolution")
        wo = get_work_order(wo_id)
        assert wo["status"] == "RESOLVED"
        # Audit log records RESOLVE twice.
        logs = list_audit_logs(work_order_id=wo_id, action="RESOLVE")
        resolves = [l for l in logs if l["action"] == "RESOLVE"]
        assert len(resolves) >= 2, (
            f"PRD §3.10 revision cycle requires two RESOLVE rows; got "
            f"{len(resolves)}"
        )

    # ---- difficulty: non_linear_state_machine / work_order_revision_cycle_via_reopen
    def test_reopen_increments_lead_department_pending(self, api):
        """PRD §3.10: 'reset the existing lead DepartmentAssignment back
        to stage_status equal to DISPATCHED while clearing its
        handler_id and accepted_at to null (a re-dispatch to the same
        lead department), and increment the lead department's
        pending_work_count by 1 (re-establishing the lead's outstanding
        work counter).'

        The cycle's second hop is observable on Department: REOPEN bumps
        lead pending_work_count by exactly 1.

        difficulty: non_linear_state_machine/work_order_revision_cycle_via_reopen
        """
        world = setup_followed_up(survey_score=1)
        # Baseline lead pending right before reopen.
        before = get_department(world["lead_department"]["id"])
        api.reopen_work_order(world["work_order"]["id"], HO)
        after = get_department(world["lead_department"]["id"])
        assert after["pending_work_count"] == before["pending_work_count"] + 1

    # ---- difficulty: non_linear_state_machine / department_assignment_branching_to_three_terminals
    def test_supporting_can_branch_to_opinion_submitted(self, api):
        """PRD §3.7: 'The side-effects move stage_status to
        OPINION_SUBMITTED, stamp opinion_submitted_at to the current
        time, decrement the department's pending_work_count by 1.'

        Demonstrates the ACCEPTED → OPINION_SUBMITTED branch.

        difficulty: non_linear_state_machine/department_assignment_branching_to_three_terminals
        """
        world = setup_supporting_accepted(num_supporting=1)
        sup = world["supporting_assignments"][0]
        handler = world["supporting_handlers"][0]
        sup_dept = world["supporting_departments"][0]
        before = get_department(sup_dept["id"])
        data = submit_opinion(world["work_order"]["id"], sup["id"],
                              handler, opinion_decision="AGREE")
        assert data["stage_status"] == "OPINION_SUBMITTED"
        after = get_department(sup_dept["id"])
        assert after["pending_work_count"] == before["pending_work_count"] - 1
        # No SupervisionTask should have been created by the opinion
        # branch (only by escalate or auto-priority).
        tasks = list_supervision_tasks(
            work_order_id=world["work_order"]["id"],
        )
        assert not any(t["reason"] == "MANUAL" for t in tasks)

    # ---- difficulty: non_linear_state_machine / department_assignment_branching_to_three_terminals
    def test_supporting_can_branch_to_escalated_with_sync_event(self, api):
        """PRD §3.7: 'A supporting handler facing deadlock... may
        escalate their assignment from ACCEPTED to ESCALATED. The
        side-effects move the stage_status to ESCALATED, and if the
        parent work order already has a SupervisionTask in status
        equal to OPEN, its escalation_level is incremented by 1;
        otherwise a fresh SupervisionTask is created with reason equal
        to MANUAL, status equal to ESCALATED, and escalation_level
        equal to 1. The system emits a SyncEvent with event_type equal
        to ESCALATED.'

        difficulty: non_linear_state_machine/department_assignment_branching_to_three_terminals
        """
        world = setup_supporting_accepted(num_supporting=1)
        sup = world["supporting_assignments"][0]
        handler = world["supporting_handlers"][0]
        resp = api.escalate_assignment(
            world["work_order"]["id"], sup["id"],
            make_department_handler_headers(handler["id"]),
        )
        data = validate_success(resp)
        assert data["stage_status"] == "ESCALATED"
        tasks = list_supervision_tasks(
            work_order_id=world["work_order"]["id"],
        )
        manual = [t for t in tasks if t["reason"] == "MANUAL"]
        assert manual and manual[0]["escalation_level"] == 1
        events = list_sync_events(
            work_order_id=world["work_order"]["id"],
            event_type="ESCALATED",
        )
        assert {e["target_platform"] for e in events} == {
            "IM", "GOVT_AFFAIRS", "INTER_DEPT",
        }


# ===========================================================================
# Rule 4 — Transitive cascade
# ===========================================================================
class TestRule4TransitiveCascade:
    """Rule 4 (transitive_cascade): dispatch → assignments → pending
    → SupervisionTask; opinion submit → aggregation → resolve gate."""

    # ---- difficulty: transitive_cascade / dispatch_triggers_assignment_then_pending_then_supervision
    def test_dispatch_high_priority_creates_assignments_and_supervision(self, api):
        """PRD §3.4: 'The transition creates one DepartmentAssignment
        row with role equal to LEAD... and one further
        DepartmentAssignment row with role equal to SUPPORTING for each
        supporting department... For every department touched (lead and
        every supporting) the department's pending_work_count is
        incremented by 1... If priority_flag is true at dispatch time...
        the system creates a SupervisionTask with reason equal to
        HIGH_PRIORITY_AUTO.'

        Triple cascade: /dispatch → assignments → pending++ →
        SupervisionTask.

        difficulty: transitive_cascade/dispatch_triggers_assignment_then_pending_then_supervision
        """
        world = setup_routing_world(num_supporting=1)
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
            urgency="CRITICAL",
        )
        classify(wo["id"])
        before_lead = get_department(world["lead_department"]["id"])
        before_sup = get_department(world["supporting_departments"][0]["id"])
        dispatch(wo["id"])
        from test_helpers import list_assignments
        assigns = list_assignments(wo["id"])
        assert len(assigns) == 2
        after_lead = get_department(world["lead_department"]["id"])
        after_sup = get_department(world["supporting_departments"][0]["id"])
        assert after_lead["pending_work_count"] == (
            before_lead["pending_work_count"] + 1
        )
        assert after_sup["pending_work_count"] == (
            before_sup["pending_work_count"] + 1
        )
        tasks = list_supervision_tasks(work_order_id=wo["id"])
        auto = [t for t in tasks if t["reason"] == "HIGH_PRIORITY_AUTO"]
        assert len(auto) == 1
        assert auto[0]["status"] == "OPEN"
        assert auto[0]["escalation_level"] == 0

    # ---- difficulty: transitive_cascade / dispatch_triggers_assignment_then_pending_then_supervision
    def test_dispatch_non_priority_does_not_create_supervision_task(self, api):
        """PRD §3.4: 'If priority_flag is true at dispatch time...the
        system creates a SupervisionTask with reason equal to
        HIGH_PRIORITY_AUTO.'

        Negative half of the cascade: without priority_flag the third
        cascade hop does NOT fire — no HIGH_PRIORITY_AUTO supervision
        task is created. The first two hops (assignment + pending bump)
        still fire.

        difficulty: transitive_cascade/dispatch_triggers_assignment_then_pending_then_supervision
        """
        world = setup_routing_world(num_supporting=0, difficulty_base=1)
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
            urgency="LOW",
        )
        classify(wo["id"])
        # priority_flag must be false (urgency<HIGH and difficulty<7).
        wo_after = get_work_order(wo["id"])
        assert wo_after["priority_flag"] is False
        before_lead = get_department(world["lead_department"]["id"])
        dispatch(wo["id"])
        # Hop 1 + 2 fire: assignment row + pending++.
        from test_helpers import list_assignments
        assigns = list_assignments(wo["id"])
        assert len(assigns) == 1
        after_lead = get_department(world["lead_department"]["id"])
        assert after_lead["pending_work_count"] == (
            before_lead["pending_work_count"] + 1
        )
        # Hop 3 does NOT fire: no auto-supervision task created.
        tasks = list_supervision_tasks(work_order_id=wo["id"])
        auto = [t for t in tasks if t["reason"] == "HIGH_PRIORITY_AUTO"]
        assert auto == []

    # ---- difficulty: transitive_cascade / opinion_submit_triggers_aggregation_then_resolve_eligibility
    def test_resolve_blocked_until_opinions_then_aggregation_passes(self, api):
        """PRD §3.7: 'when joint_handling is true every supporting
        assignment must be in OPINION_SUBMITTED (otherwise priority-16
        fires with ERR_OPINIONS_INCOMPLETE)... the current aggregated
        opinion decision must not be DISAGREE_BLOCKING (otherwise
        priority-17 fires with ERR_DISAGREEMENT_UNRESOLVED).'

        First /resolve attempt fails with ERR_OPINIONS_INCOMPLETE; after
        every supporting agrees, /resolve succeeds.

        difficulty: transitive_cascade/opinion_submit_triggers_aggregation_then_resolve_eligibility
        """
        world = setup_supporting_accepted(num_supporting=1)
        # First attempt before opinion submission → OPINIONS_INCOMPLETE.
        resp = api.resolve_work_order(
            world["work_order"]["id"],
            resolve_work_order_payload(resolution_summary="x"),
            make_department_handler_headers(world["lead_handler"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OPINIONS_INCOMPLETE.value)
        # Submit opinion AGREE.
        submit_opinion(
            world["work_order"]["id"],
            world["supporting_assignments"][0]["id"],
            world["supporting_handlers"][0], opinion_decision="AGREE",
        )
        # Now /resolve succeeds.
        data = resolve(world["work_order"]["id"],
                       handler=world["lead_handler"])
        assert data["status"] == "RESOLVED"

    # ---- difficulty: transitive_cascade / opinion_submit_triggers_aggregation_then_resolve_eligibility
    def test_resolve_blocked_by_disagree_blocking_after_opinions(self, api):
        """PRD §3.7: 'if D is greater than or equal to the ceiling of N
        divided by 2 the aggregated decision is DISAGREE_BLOCKING...
        the current aggregated opinion decision must not be
        DISAGREE_BLOCKING (otherwise priority-17 fires with
        ERR_DISAGREEMENT_UNRESOLVED).'

        Second hop of the cascade is observable: even after all opinion
        side-effects complete (no more ERR_OPINIONS_INCOMPLETE), the
        recomputed aggregation gates /resolve and surfaces a different
        error_id, confirming that opinion submission triggers the
        downstream aggregation re-evaluation.

        difficulty: transitive_cascade/opinion_submit_triggers_aggregation_then_resolve_eligibility
        """
        world = setup_all_opinions_submitted(
            supporting_decisions=["DISAGREE"],
        )
        resp = api.resolve_work_order(
            world["work_order"]["id"],
            resolve_work_order_payload(resolution_summary="x"),
            make_department_handler_headers(world["lead_handler"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DISAGREEMENT_UNRESOLVED.value)


# ===========================================================================
# Rule 5 — Priority-pair validation conflict
# ===========================================================================
class TestRule5PriorityPairValidationConflict:
    """Rule 5 (priority_pair_validation_conflict): the ordered priority
    table determines which error surfaces when multiple checks fire."""

    # ---- difficulty: priority_pair_validation_conflict / state_vs_business_safety_anonymous_pii_on_pause
    def test_patch_classified_anonymous_pii_state_wins(self, api):
        """PRD §2.6: 'the work-order state-permission check is priority
        8 (and surfaces as ERR_INVALID_STATE)... Business-safety checks
        for anonymous PII (priority 12, ERR_ANONYMOUS_PII_LEAK) and
        survey-channel forbidden (priority 13...) run after state.'

        State (p=8) precedes business_safety (p=12), so PATCH-ing
        caller_phone onto an anonymous WO that has already been
        CLASSIFIED yields ERR_INVALID_STATE, not ERR_ANONYMOUS_PII_LEAK.

        difficulty: priority_pair_validation_conflict/state_vs_business_safety_anonymous_pii_on_pause
        """
        world = setup_routing_world()
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
            anonymous=True,
        )
        classify(wo["id"])
        from test_helpers import update_work_order_payload
        resp = api.update_work_order(
            wo["id"],
            update_work_order_payload(caller_phone="+10000000000"),
            HO,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    # ---- difficulty: priority_pair_validation_conflict / business_constraint_vs_business_referential_resolve
    def test_resolve_opinions_incomplete_beats_disagreement(self, api):
        """PRD §2.6: 'Business-constraint checks then run in this order:
        opinions-incomplete at resolve (priority 16,
        ERR_OPINIONS_INCOMPLETE), disagreement-unresolved at resolve
        (priority 17, ERR_DISAGREEMENT_UNRESOLVED).'

        Joint case with S1 = OPINION_SUBMITTED/DISAGREE and S2 still
        ACCEPTED (no opinion) → priority 16 wins:
        ERR_OPINIONS_INCOMPLETE, not ERR_DISAGREEMENT_UNRESOLVED.

        difficulty: priority_pair_validation_conflict/business_constraint_vs_business_referential_resolve
        """
        world = setup_supporting_accepted(num_supporting=2)
        # S1 submits DISAGREE; S2 remains ACCEPTED.
        s1 = world["supporting_assignments"][0]
        h1 = world["supporting_handlers"][0]
        submit_opinion(
            world["work_order"]["id"], s1["id"], h1,
            opinion_decision="DISAGREE",
        )
        resp = api.resolve_work_order(
            world["work_order"]["id"],
            resolve_work_order_payload(resolution_summary="x"),
            make_department_handler_headers(world["lead_handler"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OPINIONS_INCOMPLETE.value)

    # ---- difficulty: priority_pair_validation_conflict / business_constraint_vs_business_referential_resolve
    def test_resolve_all_in_disagreement_surfaces_only(self, api):
        """PRD §2.6: 'disagreement-unresolved at resolve (priority 17,
        ERR_DISAGREEMENT_UNRESOLVED)... a request that violates several
        checks at once receives the error_id corresponding to the
        lowest priority number above.'

        With all supporting in OPINION_SUBMITTED and the aggregated
        decision DISAGREE_BLOCKING, priority 17 is the only failing
        check → ERR_DISAGREEMENT_UNRESOLVED.

        difficulty: priority_pair_validation_conflict/business_constraint_vs_business_referential_resolve
        """
        world = setup_all_opinions_submitted(
            supporting_decisions=["DISAGREE", "DISAGREE"],
        )
        resp = api.resolve_work_order(
            world["work_order"]["id"],
            resolve_work_order_payload(resolution_summary="x"),
            make_department_handler_headers(world["lead_handler"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DISAGREEMENT_UNRESOLVED.value)


# ===========================================================================
# Rule 6 — Boundary precision check
# ===========================================================================
class TestRule6BoundaryPrecision:
    """Rule 6 (boundary_precision_check): opinion aggregation tie-break
    at ceil(N/2); warning_state YELLOW boundary at pct = 0.25."""

    # ---- difficulty: boundary_precision_check / opinion_aggregation_ceil_half_n_tiebreak
    def test_n2_d1_blocks_at_boundary(self, api):
        """PRD §3.7: 'if D is greater than or equal to the ceiling of N
        divided by 2 the aggregated decision is DISAGREE_BLOCKING.'

        N=2, D=1: ceil(2/2)=1, so D >= 1 → BLOCKING. /resolve fails.

        difficulty: boundary_precision_check/opinion_aggregation_ceil_half_n_tiebreak
        """
        world = setup_all_opinions_submitted(
            supporting_decisions=["AGREE", "DISAGREE"],
        )
        resp = api.resolve_work_order(
            world["work_order"]["id"],
            resolve_work_order_payload(resolution_summary="x"),
            make_department_handler_headers(world["lead_handler"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DISAGREEMENT_UNRESOLVED.value)

    # ---- difficulty: boundary_precision_check / opinion_aggregation_ceil_half_n_tiebreak
    def test_n2_d0_agreement_passes(self, api):
        """PRD §3.7: 'if D is zero the aggregated decision is AGREE.'

        N=2, D=0 (both AGREE): not blocking → /resolve succeeds.
        Together with the previous test, this confirms the boundary is
        '>=', not strict '>'.

        difficulty: boundary_precision_check/opinion_aggregation_ceil_half_n_tiebreak
        """
        world = setup_all_opinions_submitted(
            supporting_decisions=["AGREE", "AGREE"],
        )
        data = resolve(world["work_order"]["id"],
                       handler=world["lead_handler"])
        assert data["status"] == "RESOLVED"

    # ---- difficulty: boundary_precision_check / warning_state_yellow_at_exact_25_percent
    def test_warning_yellow_at_exact_quarter_remaining(self, api):
        """PRD §3.8: 'when pct is less than or equal to 0.25 — meaning
        25% or less of the committed window remains — the state is
        YELLOW. Otherwise the state is NONE. The boundary semantics
        are deliberate: a case with pct exactly equal to 0.25 is
        YELLOW (not NONE).'

        committed=4 business hours; advance 3 → remaining 1, pct=0.25
        → YELLOW. The clock is aligned to a business-day start so the
        wall-clock-seconds span used in PRD §3.8's pct formula equals
        committed_hours*3600.

        difficulty: boundary_precision_check/warning_state_yellow_at_exact_25_percent
        """
        align_clock_to_business_day_start()
        world = setup_routing_world(committed_hours=4, statutory_hours=8)
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
        )
        classify(wo["id"])
        advance_clock(3 * 3600)
        wo_after = get_work_order(wo["id"])
        assert wo_after["warning_state"] == "YELLOW"

    # ---- difficulty: boundary_precision_check / warning_state_yellow_at_exact_25_percent
    def test_warning_none_just_above_quarter(self, api):
        """PRD §3.8: 'Otherwise the state is NONE.'

        committed=4 business hours; advance 2 business hours →
        remaining 2 / total 4 = 0.5 > 0.25 → NONE.

        difficulty: boundary_precision_check/warning_state_yellow_at_exact_25_percent
        """
        align_clock_to_business_day_start()
        world = setup_routing_world(committed_hours=4, statutory_hours=8)
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
        )
        classify(wo["id"])
        advance_clock(2 * 3600)
        wo_after = get_work_order(wo["id"])
        assert wo_after["warning_state"] == "NONE"


# ===========================================================================
# Rule 7 — Cross-entity state dependency
# ===========================================================================
class TestRule7CrossEntityStateDependency:
    """Rule 7 (cross_entity_state_dependency): WorkOrder.resolve gated
    on supporting assignments; WorkOrder.close gated on supervision
    tasks."""

    # ---- difficulty: cross_entity_state_dependency / workorder_resolve_depends_on_supporting_assignment_state
    def test_resolve_fails_when_supporting_still_accepted(self, api):
        """PRD §3.7: 'when joint_handling is true every supporting
        assignment must be in OPINION_SUBMITTED (otherwise priority-16
        fires with ERR_OPINIONS_INCOMPLETE).'

        WorkOrder cannot resolve until sibling DepartmentAssignment
        rows reach OPINION_SUBMITTED.

        difficulty: cross_entity_state_dependency/workorder_resolve_depends_on_supporting_assignment_state
        """
        world = setup_supporting_accepted(num_supporting=1)
        resp = api.resolve_work_order(
            world["work_order"]["id"],
            resolve_work_order_payload(resolution_summary="x"),
            make_department_handler_headers(world["lead_handler"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OPINIONS_INCOMPLETE.value)

    # ---- difficulty: cross_entity_state_dependency / workorder_resolve_depends_on_supporting_assignment_state
    def test_resolve_succeeds_after_supporting_opinion(self, api):
        """PRD §3.7: 'On success, the work-order status becomes
        RESOLVED.'

        Once the supporting assignment reaches OPINION_SUBMITTED with
        AGREE, the WorkOrder.resolve transition unblocks — proving the
        dependency on sibling-entity state.

        difficulty: cross_entity_state_dependency/workorder_resolve_depends_on_supporting_assignment_state
        """
        world = setup_supporting_accepted(num_supporting=1)
        submit_opinion(
            world["work_order"]["id"],
            world["supporting_assignments"][0]["id"],
            world["supporting_handlers"][0], opinion_decision="AGREE",
        )
        data = resolve(world["work_order"]["id"],
                       handler=world["lead_handler"])
        assert data["status"] == "RESOLVED"

    # ---- difficulty: cross_entity_state_dependency / close_depends_on_supervisiontask_state
    def test_close_blocked_while_supervision_open(self, api):
        """PRD §3.10: 'In both paths the close additionally requires
        that no SupervisionTask for this work order is currently in
        OPEN or ESCALATED; otherwise priority-18 fires with
        ERR_SUPERVISION_OPEN.'

        WO has FOLLOWED_UP status and a HIGH_PRIORITY_AUTO supervision
        task still OPEN → /close fails with ERR_SUPERVISION_OPEN.

        difficulty: cross_entity_state_dependency/close_depends_on_supervisiontask_state
        """
        # Build a high-priority WO that auto-creates a supervision task,
        # carry it to FOLLOWED_UP via survey response, then attempt
        # /close without closing the supervision task.
        world = setup_routing_world()
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
            urgency="CRITICAL",
        )
        classify(wo["id"])
        dispatch(wo["id"])
        lead = find_lead_assignment(wo["id"])
        accept_assignment(wo["id"], lead["id"], world["lead_handler"])
        resolve(wo["id"], handler=world["lead_handler"])
        # Auto-survey present; respond with score=5 → FOLLOWED_UP.
        surveys = _list_surveys(wo["id"])
        assert surveys
        api.respond_survey(
            surveys[-1]["id"], respond_survey_payload(score=5), SA,
        )
        # Now /close while supervision task still OPEN.
        resp = api.close_work_order(wo["id"], DISP)
        validate_error(resp, ApiErrorId.ERR_SUPERVISION_OPEN.value)

    # ---- difficulty: cross_entity_state_dependency / close_depends_on_supervisiontask_state
    def test_close_succeeds_after_supervision_closed(self, api):
        """PRD §3.10: 'In both paths the close additionally requires
        that no SupervisionTask for this work order is currently in
        OPEN or ESCALATED.'

        Closing the SupervisionTask removes the gate, so /close
        succeeds.

        difficulty: cross_entity_state_dependency/close_depends_on_supervisiontask_state
        """
        world = setup_routing_world()
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
            urgency="CRITICAL",
        )
        classify(wo["id"])
        dispatch(wo["id"])
        lead = find_lead_assignment(wo["id"])
        accept_assignment(wo["id"], lead["id"], world["lead_handler"])
        resolve(wo["id"], handler=world["lead_handler"])
        surveys = _list_surveys(wo["id"])
        api.respond_survey(
            surveys[-1]["id"], respond_survey_payload(score=5), SA,
        )
        # Close the supervision task first.
        tasks = list_supervision_tasks(work_order_id=wo["id"])
        for t in tasks:
            if t["status"] in ("OPEN", "ACKNOWLEDGED", "ESCALATED"):
                api.close_supervision(t["id"], SUP)
        # Now /close should succeed.
        resp = api.close_work_order(wo["id"], DISP)
        data = validate_success(resp)
        assert data["status"] == "CLOSED"


# ===========================================================================
# Rule 8 — Resource temporal overlap
# ===========================================================================
class TestRule8ResourceTemporalOverlap:
    """Rule 8 (resource_temporal_overlap): clarification-pause
    non-concurrency; assignment single-occupant acceptance."""

    # ---- difficulty: resource_temporal_overlap / clarification_pause_no_concurrent_pauses_per_workorder
    def test_second_pause_while_paused_rejected(self, api):
        """PRD §3.6: 'A pause attempted while the work order is already
        paused fails priority-11 with ERR_ALREADY_PAUSED.'

        difficulty: resource_temporal_overlap/clarification_pause_no_concurrent_pauses_per_workorder
        """
        world = setup_in_progress()
        pause(world["work_order"]["id"], handler=world["lead_handler"])
        resp = api.pause_work_order(
            world["work_order"]["id"],
            pause_work_order_payload(reason="again"),
            make_department_handler_headers(world["lead_handler"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ALREADY_PAUSED.value)

    # ---- difficulty: resource_temporal_overlap / clarification_pause_no_concurrent_pauses_per_workorder
    def test_sequential_pauses_succeed_after_resume(self, api):
        """PRD §3.6: 'On success, the latest open ClarificationPause for
        the work order has its resumed_at set to the current time...
        pause_started_at is reset to null.'

        After a successful resume, a fresh pause must succeed —
        intervals are sequential, not concurrent.

        difficulty: resource_temporal_overlap/clarification_pause_no_concurrent_pauses_per_workorder
        """
        world = setup_in_progress()
        wo_id = world["work_order"]["id"]
        handler = world["lead_handler"]
        pause(wo_id, handler=handler)
        advance_clock(60)
        resume(wo_id, handler=handler)
        # Third pause must succeed.
        resp = api.pause_work_order(
            wo_id, pause_work_order_payload(reason="second pause"),
            make_department_handler_headers(handler["id"]),
        )
        validate_success(resp)

    # ---- difficulty: resource_temporal_overlap / department_assignment_single_active_handler_per_assignment
    def test_second_handler_accept_rejected_when_already_accepted(self, api):
        """PRD §3.5: 'Two handlers within the same department racing the
        same acceptance are serialized by a first-writer-wins guarantee
        on the assignment's stage_status moving out of DISPATCHED; the
        loser receives ERR_ASSIGNMENT_NOT_PENDING (409).'

        Verified sequentially: H1 accepts; H2's accept is rejected.

        difficulty: resource_temporal_overlap/department_assignment_single_active_handler_per_assignment
        """
        world = setup_routing_world()
        # Create a second handler in the same lead department.
        h2 = create_handler(department_id=world["lead_department"]["id"])
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
        )
        classify(wo["id"])
        dispatch(wo["id"])
        lead = find_lead_assignment(wo["id"])
        # H1 accepts first.
        accept_assignment(wo["id"], lead["id"], world["lead_handler"])
        # H2 tries second.
        resp = api.accept_assignment(
            wo["id"], lead["id"],
            make_department_handler_headers(h2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_PENDING.value)

    # ---- difficulty: resource_temporal_overlap / department_assignment_single_active_handler_per_assignment
    def test_dept_pending_increments_once_across_two_accept_attempts(self, api):
        """PRD §3.13: 'every department's pending_work_count is exactly
        equal to the count of DepartmentAssignment rows where
        department_id is that department's id and stage_status is in
        DISPATCHED or ACCEPTED.'

        Despite two accept attempts, the pending_work_count reflects
        the single DISPATCHED→ACCEPTED transition (count of {DISPATCHED,
        ACCEPTED} rows for the lead dept is exactly 1).

        difficulty: resource_temporal_overlap/department_assignment_single_active_handler_per_assignment
        """
        world = setup_routing_world()
        h2 = create_handler(department_id=world["lead_department"]["id"])
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
        )
        classify(wo["id"])
        dispatch(wo["id"])
        before = get_department(world["lead_department"]["id"])
        assert before["pending_work_count"] >= 1
        lead = find_lead_assignment(wo["id"])
        accept_assignment(wo["id"], lead["id"], world["lead_handler"])
        # Failed second accept must not change pending count further.
        resp = api.accept_assignment(
            wo["id"], lead["id"],
            make_department_handler_headers(h2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_PENDING.value)
        after = get_department(world["lead_department"]["id"])
        # Pending unchanged from the post-dispatch baseline (ACCEPTED
        # still counts in the {DISPATCHED, ACCEPTED} membership).
        assert after["pending_work_count"] == before["pending_work_count"]


# ===========================================================================
# Rule 9 — Compensating invariant
# ===========================================================================
class TestRule9CompensatingInvariant:
    """Rule 9 (compensating_invariant): pause-seconds invariant;
    department pending-count invariant."""

    # ---- difficulty: compensating_invariant / pause_resume_pause_accumulated_seconds_invariant
    def test_two_pause_resume_pairs_sum_to_pause_accumulated_seconds(self, api):
        """PRD §3.13: 'The pause invariant requires that for every work
        order, the field pause_accumulated_seconds is exactly equal to
        the sum of duration_seconds across its ClarificationPause rows
        whose resumed_at is not null... The tolerance is exactly zero
        seconds.'

        Two pause/resume pairs of 1800 s each → 3600 s accumulated.

        difficulty: compensating_invariant/pause_resume_pause_accumulated_seconds_invariant
        """
        world = setup_in_progress()
        wo_id = world["work_order"]["id"]
        handler = world["lead_handler"]
        pause(wo_id, handler=handler)
        advance_clock(1800)
        resume(wo_id, handler=handler)
        pause(wo_id, handler=handler)
        advance_clock(1800)
        resume(wo_id, handler=handler)
        wo = get_work_order(wo_id)
        assert wo["pause_accumulated_seconds"] == 3600

    # ---- difficulty: compensating_invariant / pause_resume_pause_accumulated_seconds_invariant
    def test_single_pause_resume_sets_pause_accumulated_seconds(self, api):
        """PRD §3.6: 'The work order's pause_accumulated_seconds is
        increased by that same duration.'

        difficulty: compensating_invariant/pause_resume_pause_accumulated_seconds_invariant
        """
        world = setup_paused_with_seconds(pause_seconds=900)
        assert world["work_order"]["pause_accumulated_seconds"] == 900

    # ---- difficulty: compensating_invariant / dispatch_resolve_pending_work_count_invariant
    def test_dispatch_then_resolve_returns_lead_pending_to_baseline(self, api):
        """PRD §3.13: 'Each dispatch's increment is paired with exactly
        one decrement: a handler reject, a dispatcher reassign on the
        source department, a supporting opinion-submit, or — on the
        lead — a resolve.'

        Joint dispatch increments lead+1 and supporting+1; resolve and
        opinion submit return both to baseline.

        difficulty: compensating_invariant/dispatch_resolve_pending_work_count_invariant
        """
        world = setup_routing_world(num_supporting=1)
        before_lead = get_department(world["lead_department"]["id"])
        before_sup = get_department(world["supporting_departments"][0]["id"])
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
        )
        classify(wo["id"])
        dispatch(wo["id"])
        # Lead and supporting accept.
        lead = find_lead_assignment(wo["id"])
        accept_assignment(wo["id"], lead["id"], world["lead_handler"])
        sup_assigns = find_supporting_assignments(wo["id"])
        accept_assignment(
            wo["id"], sup_assigns[0]["id"],
            world["supporting_handlers"][0],
        )
        submit_opinion(
            wo["id"], sup_assigns[0]["id"],
            world["supporting_handlers"][0], opinion_decision="AGREE",
        )
        # After opinion submit, supporting pending returns to baseline.
        after_sup = get_department(world["supporting_departments"][0]["id"])
        assert after_sup["pending_work_count"] == before_sup["pending_work_count"]
        resolve(wo["id"], handler=world["lead_handler"])
        after_lead = get_department(world["lead_department"]["id"])
        assert after_lead["pending_work_count"] == before_lead["pending_work_count"]

    # ---- difficulty: compensating_invariant / dispatch_resolve_pending_work_count_invariant
    def test_dispatch_then_handler_reject_returns_pending_to_baseline(self, api):
        """PRD §3.13: 'Each dispatch's increment is paired with exactly
        one decrement: a handler reject, a dispatcher reassign on the
        source department.'

        Handler-reject path: dispatch increments by 1, reject decrements
        by 1.

        difficulty: compensating_invariant/dispatch_resolve_pending_work_count_invariant
        """
        world = setup_routing_world()
        before = get_department(world["lead_department"]["id"])
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
        )
        classify(wo["id"])
        dispatch(wo["id"])
        lead = find_lead_assignment(wo["id"])
        from test_helpers.factories import reject_assignment_payload
        api.reject_assignment(
            wo["id"], lead["id"],
            reject_assignment_payload(rejection_reason="no"),
            make_department_handler_headers(world["lead_handler"]["id"]),
        )
        after = get_department(world["lead_department"]["id"])
        assert after["pending_work_count"] == before["pending_work_count"]
