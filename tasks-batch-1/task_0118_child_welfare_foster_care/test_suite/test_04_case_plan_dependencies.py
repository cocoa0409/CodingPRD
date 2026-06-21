"""Cross-entity state dependencies and the case-plan revise/compliance invariants.

Queue A — difficulty rules: cross_entity_state_dependency, compensating_invariant
(objectives_met_conserved_after_revise_cycle).
"""
from test_helpers import (
    get_success_data, validate_success, validate_error,
    setup_workers, open_case_with_child, setup_placed_child, set_clock,
    create_active_case_plan, set_plan_compliance, advance_to_permanency_planning,
)


# =========================================================================
# Rule 7 — cross_entity_state_dependency / case_close_reunified_requires_completed_plan
# =========================================================================
def test_close_reunified_blocked_by_incomplete_plan(api):
    """PRD §3.9: "Reunification close** (`CLOSED_REUNIFIED`): permitted when `permanency_goal` is `REUNIFICATION`, the case's `CasePlan` is `COMPLETED`, and the child's active placement (if any) has ended as `ENDED_REUNIFIED`. A goal other than `REUNIFICATION` yields `ERR_GOAL_MISMATCH`; an incomplete plan yields `ERR_PLAN_NOT_COMPLETE`."
    Case in PERMANENCY_PLANNING, goal REUNIFICATION, plan ACTIVE (not COMPLETED).

    Design: Difficulty/cross_entity_state_dependency/case_close_reunified_requires_completed_plan
    """
    w = setup_workers()
    set_clock("2026-01-01T00:00:00Z")
    case, child, home, placement = setup_placed_child(w)
    # Plan ACTIVE but not completed (compliance left at 0).
    create_active_case_plan(w, case["id"])
    advance_to_permanency_planning(w, case["id"], ruling="CONTINUE_PLACEMENT")

    resp = api.close_case(case["id"], w.caseworker)
    validate_error(resp, "ERR_PLAN_NOT_COMPLETE")

    case_after = validate_success(api.get_case(case["id"], w.caseworker))
    assert case_after["status"] == "PERMANENCY_PLANNING"


def test_case_plan_completes_only_at_full_compliance(api):
    """PRD §3.8: "An `ACTIVE` plan may be **completed** only when its `compliance_pct` is at least 100 — every objective met — and a completion attempt on a plan below that mark is rejected with `ERR_PLAN_NOT_COMPLETE`."
    A plan whose 5 objectives are all met reads 100.00 and completes.

    Design: Difficulty/cross_entity_state_dependency/case_close_reunified_requires_completed_plan
    """
    w = setup_workers(need_licensing=False)
    set_clock("2026-01-01T00:00:00Z")
    case, child = open_case_with_child(w)
    plan = create_active_case_plan(w, case["id"], objectives_total=5)
    set_plan_compliance(w, plan["id"], 5)
    completed = validate_success(api.complete_case_plan(plan["id"], w.caseworker))
    assert completed["status"] == "COMPLETED"


# =========================================================================
# Rule 7 — cross_entity_state_dependency / child_trial_visit_requires_plan_compliance
# =========================================================================
# NOTE: test_trial_home_visit_blocked_below_80_compliance was DELETED.
# PRD §3.8 states the rule ("permitted only when ... compliance_pct of at least
# 80") but names NO error_id for the below-80 rejection. ERR_INVALID_STATE and
# ERR_PLAN_NOT_COMPLETE (both HTTP 409, both in the error catalog) are each a
# PRD-faithful mapping a reader could pick — the prose does not uniquely
# determine the error_id (ENUM-SILENCE collapse). The PRD names no member of
# the error set, so validate_error_is_one_of([...]) relaxation is not permitted
# either. The positive transition below stays (uniquely PRD-determined).
def test_trial_home_visit_allowed_at_80_compliance(api):
    """PRD §3.8: "the case's `CasePlan` has `compliance_pct` of at least 80. On success the child moves from `PLACED` to `TRIAL_HOME_VISIT` and the child's `version` is bumped."
    Plan at 4 of 5 objectives = 80.00 (>= 80) -> child moves to TRIAL_HOME_VISIT.

    Design: Difficulty/cross_entity_state_dependency/child_trial_visit_requires_plan_compliance
    """
    w = setup_workers()
    set_clock("2026-01-01T00:00:00Z")
    case, child, home, placement = setup_placed_child(w)
    plan = create_active_case_plan(w, case["id"], objectives_total=5)
    plan_after = set_plan_compliance(w, plan["id"], 4)
    assert plan_after["compliance_pct"] == 80.0

    moved = validate_success(api.trial_home_visit(child["id"], w.caseworker))
    assert moved["status"] == "TRIAL_HOME_VISIT"


# =========================================================================
# Rule 9 — compensating_invariant / objectives_met_conserved_after_revise_cycle
# =========================================================================
def test_objectives_met_conserved_across_revise_cycle(api):
    """PRD §3.8: "An `ACTIVE` plan may be sent back for `REVISION` and a plan in `REVISION` is re-activated to `ACTIVE` (this revision cycle does not require the disposition prerequisite a second time)."
    PRD §3.8: "the plan's `compliance_pct` is recomputed as the quotient of `objectives_met` over `objectives_total`, multiplied by 100, rounded half-up to two decimal places."
    objectives_met 4 of 5 = 80.00 before; ACTIVE->REVISION->ACTIVE leaves both intact.

    Design: Difficulty/compensating_invariant/objectives_met_conserved_after_revise_cycle
    """
    w = setup_workers(need_licensing=False)
    set_clock("2026-01-01T00:00:00Z")
    case, child = open_case_with_child(w)
    plan = create_active_case_plan(w, case["id"], objectives_total=5)
    before = set_plan_compliance(w, plan["id"], 4)
    assert before["objectives_met"] == 4
    assert before["compliance_pct"] == 80.0

    get_success_data(api.revise_case_plan(plan["id"], w.caseworker))
    reactivated = validate_success(api.activate_case_plan(plan["id"], w.caseworker))
    assert reactivated["status"] == "ACTIVE"
    assert reactivated["objectives_met"] == 4
    assert reactivated["compliance_pct"] == 80.0


def test_revision_cycle_preserves_compliance_pct(api):
    """PRD §3.8: "A plan with all objectives met reads exactly 100.00; any plan short of its total reads below 100.00."
    A plan at 80.00 (short of total) still reads 80.00 after a revise/activate round-trip.

    Design: Difficulty/compensating_invariant/objectives_met_conserved_after_revise_cycle
    """
    w = setup_workers(need_licensing=False)
    set_clock("2026-01-01T00:00:00Z")
    case, child = open_case_with_child(w)
    plan = create_active_case_plan(w, case["id"], objectives_total=5)
    set_plan_compliance(w, plan["id"], 4)

    get_success_data(api.revise_case_plan(plan["id"], w.caseworker))
    get_success_data(api.activate_case_plan(plan["id"], w.caseworker))
    final = validate_success(api.get_case_plan(plan["id"], w.caseworker))
    assert final["compliance_pct"] == 80.0
    assert final["objectives_met"] == 4
