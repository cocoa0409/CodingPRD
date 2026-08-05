"""Clearance assembly: psych evaluations, nutrition, milestones, supervised diet,
and finalization gating.

Covers difficulty queue A (cross-entity finalize dependency, diet-month boundary,
psych defer/reevaluate cycle) and corner queue B (invalid state, not-found,
duplicate constraints, reverse-reachability listing).
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    create_clearance_in_progress_program, create_insurance_clearance_ready_except_diet,
    create_insurance_plan,
    add_psych_cleared, add_psych_deferred, add_nutrition_cleared, add_all_milestones,
    add_diet_visit, get_program,
    create_psych_evaluation_payload, create_diet_visit_payload, create_milestone_payload,
)

PC = TEST_USERS["program_coordinator_headers"]
DT = TEST_USERS["dietitian_headers"]
BH = TEST_USERS["behavioral_health_headers"]


# ---------------- Difficulty A: finalize depends on psych CLEARED ----------------

def test_finalize_fails_while_psych_deferred(api):
    """PRD §3.3: "The derived clearances_complete gate is true exactly when all four
    conditions hold at once: the program has a CLEARED psychological evaluation, it has
    a CLEARED nutrition clearance, every one of the four required education milestones
    exists and is completed, and — for an INSURANCE program — the supervised-diet-month
    requirement is met."
    PRD §3.3: "If the program is in CLEARANCE_IN_PROGRESS but the gate is not satisfied,
    finalization is rejected with ERR_CLEARANCES_INCOMPLETE (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/finalize_clearance_depends_on_psych_cleared
    """
    prog = create_clearance_in_progress_program(api, payment_pathway="SELF_PAY",
                                                sex="MALE", height_cm=175, baseline_weight_kg=135)
    pid = prog["id"]
    add_nutrition_cleared(api, pid)
    add_all_milestones(api, pid)
    add_psych_deferred(api, pid)
    validate_error(api.finalize_clearance(pid, PC), ApiErrorId.ERR_CLEARANCES_INCOMPLETE.value)


def test_finalize_succeeds_after_psych_cleared(api):
    """PRD §3.3: "When the coordinator finalizes clearance, the system recomputes this
    gate and, if it holds, moves the program from CLEARANCE_IN_PROGRESS to CLEARED,
    incrementing its version."
    PRD §3.3: "An evaluation counts as satisfying the psychological requirement only once
    it reaches CLEARED."

    Design: Difficulty/cross_entity_state_dependency/finalize_clearance_depends_on_psych_cleared
    """
    prog = create_clearance_in_progress_program(api, payment_pathway="SELF_PAY",
                                                sex="MALE", height_cm=175, baseline_weight_kg=135)
    pid = prog["id"]
    add_nutrition_cleared(api, pid)
    add_all_milestones(api, pid)
    pe = add_psych_deferred(api, pid)
    validate_error(api.finalize_clearance(pid, PC), ApiErrorId.ERR_CLEARANCES_INCOMPLETE.value)
    validate_success(api.psych_reevaluate(pe["id"], BH))
    validate_success(api.psych_decision(pe["id"], {"decision": "CLEARED"}, BH))
    data = validate_success(api.finalize_clearance(pid, PC))
    assert data["status"] == "CLEARED", f"expected CLEARED, got {data['status']}"


# ---------------- Difficulty A: supervised-diet month-count boundary ----------------

def test_finalize_fails_with_two_of_three_diet_months(api):
    """PRD §3.3: "The diet requirement is met when the number of distinct month_index
    values — counted only among visits that were attended and whose month_index falls
    between 1 and the required count inclusive — is at least the required count. A program
    that is one qualifying month short does not meet the requirement."

    Design: Difficulty/boundary_precision_check/supervised_diet_exact_month_count_boundary
    """
    prog, _plan = create_insurance_clearance_ready_except_diet(api, required_supervised_diet_months=3)
    pid = prog["id"]
    add_diet_visit(api, pid, month_index=1, visit_date="2026-02-01", weight_kg=119)
    add_diet_visit(api, pid, month_index=2, visit_date="2026-03-01", weight_kg=118)
    validate_error(api.finalize_clearance(pid, PC), ApiErrorId.ERR_CLEARANCES_INCOMPLETE.value)


def test_finalize_succeeds_after_third_diet_month(api):
    """PRD §3.3: "Insurance payers require a run of consecutive attended monthly visits
    before they will authorize surgery; the plan states how many via
    required_supervised_diet_months ... the number of distinct month_index values ... is
    at least the required count."

    Design: Difficulty/boundary_precision_check/supervised_diet_exact_month_count_boundary
    """
    prog, _plan = create_insurance_clearance_ready_except_diet(api, required_supervised_diet_months=3)
    pid = prog["id"]
    add_diet_visit(api, pid, month_index=1, visit_date="2026-02-01", weight_kg=119)
    add_diet_visit(api, pid, month_index=2, visit_date="2026-03-01", weight_kg=118)
    validate_error(api.finalize_clearance(pid, PC), ApiErrorId.ERR_CLEARANCES_INCOMPLETE.value)
    add_diet_visit(api, pid, month_index=3, visit_date="2026-04-01", weight_kg=117)
    data = validate_success(api.finalize_clearance(pid, PC))
    assert data["status"] == "CLEARED", f"expected CLEARED, got {data['status']}"


# ---------------- Difficulty A: psych defer -> reevaluate cycle ----------------

def test_reevaluate_returns_deferred_psych_to_pending(api):
    """PRD §3.3: "A deferred evaluation is not a dead end: the clinician may re-open it,
    moving it from DEFERRED back to PENDING, which increments its reevaluation_count and
    clears the stored deferral_reason."

    Design: Difficulty/non_linear_state_machine/psych_defer_then_reevaluate_cycle
    """
    prog = create_clearance_in_progress_program(api, payment_pathway="SELF_PAY",
                                                sex="MALE", height_cm=175, baseline_weight_kg=130)
    pe = validate_success(api.create_psych_evaluation(prog["id"], create_psych_evaluation_payload(), BH),
                          expected_status=201)
    validate_success(api.psych_decision(pe["id"], {"decision": "DEFERRED",
                                                   "deferral_reason": "needs 8 weeks therapy"}, BH))
    data = validate_success(api.psych_reevaluate(pe["id"], BH))
    assert data["status"] == "PENDING", f"expected PENDING, got {data['status']}"


def test_reevaluate_increments_count_and_clears_reason(api):
    """PRD §3.3: "the clinician may re-open it, moving it from DEFERRED back to PENDING,
    which increments its reevaluation_count and clears the stored deferral_reason."

    Design: Difficulty/non_linear_state_machine/psych_defer_then_reevaluate_cycle
    """
    prog = create_clearance_in_progress_program(api, payment_pathway="SELF_PAY",
                                                sex="MALE", height_cm=175, baseline_weight_kg=130)
    pe = validate_success(api.create_psych_evaluation(prog["id"], create_psych_evaluation_payload(), BH),
                          expected_status=201)
    validate_success(api.psych_decision(pe["id"], {"decision": "DEFERRED",
                                                   "deferral_reason": "needs 8 weeks therapy"}, BH))
    data = validate_success(api.psych_reevaluate(pe["id"], BH))
    assert data["reevaluation_count"] == 1, f"expected 1, got {data['reevaluation_count']}"
    assert data["deferral_reason"] is None, f"expected null deferral_reason, got {data['deferral_reason']}"


# ---------------- Corner B: invalid psych state ----------------

def test_reevaluate_pending_psych_returns_invalid_state(api):
    """PRD §3.3: "Re-evaluation is valid only from DEFERRED; from any other state it is
    rejected with the same ERR_INVALID_PSYCH_STATE (HTTP 409)."

    Design: Corner/state_machines/reevaluate_pending_psych_returns_invalid_state
    """
    prog = create_clearance_in_progress_program(api, payment_pathway="SELF_PAY")
    pe = validate_success(api.create_psych_evaluation(prog["id"], create_psych_evaluation_payload(), BH),
                          expected_status=201)
    validate_error(api.psych_reevaluate(pe["id"], BH), ApiErrorId.ERR_INVALID_PSYCH_STATE.value)


# ---------------- Corner B: not-found ----------------

def test_psych_evaluation_not_found_on_decision(api):
    """PRD §2.8: "a psychological evaluation ERR_PSYCH_EVALUATION_NOT_FOUND ... each with
    HTTP status 404."

    Design: Corner/state_machines/psych_evaluation_not_found_on_decision_returns_404
    """
    validate_error(api.psych_decision(NON_EXISTENT_UUID, {"decision": "CLEARED"}, BH),
                   ApiErrorId.ERR_PSYCH_EVALUATION_NOT_FOUND.value)


# ---------------- Corner B: duplicate constraints ----------------

def test_duplicate_milestone_code_returns_409(api):
    """PRD §3.3: "A given milestone_code may be recorded only once per program; a
    duplicate code is rejected with ERR_DUPLICATE_MILESTONE (HTTP 409)."

    Design: Corner/errors/duplicate_milestone_code_returns_409
    """
    prog = create_clearance_in_progress_program(api, payment_pathway="SELF_PAY")
    validate_success(api.create_milestone(prog["id"], create_milestone_payload("NUTRITION_CLASS"), PC),
                     expected_status=201)
    validate_error(api.create_milestone(prog["id"], create_milestone_payload("NUTRITION_CLASS"), PC),
                   ApiErrorId.ERR_DUPLICATE_MILESTONE.value)


def test_duplicate_diet_month_returns_409(api):
    """PRD §3.3: "Only one visit may claim any given month_index for a program; a second
    visit reusing an existing month_index is rejected with ERR_DUPLICATE_DIET_MONTH
    (HTTP 409)."

    Design: Corner/errors/duplicate_diet_month_returns_409
    """
    plan = create_insurance_plan(api, required_supervised_diet_months=6)
    prog = create_clearance_in_progress_program(api, payment_pathway="INSURANCE",
                                                insurance_plan_id=plan["id"])
    validate_success(api.create_diet_visit(
        prog["id"], create_diet_visit_payload(1, visit_date="2026-02-01", weight_kg=119), DT),
        expected_status=201)
    validate_error(api.create_diet_visit(
        prog["id"], create_diet_visit_payload(1, visit_date="2026-02-15", weight_kg=118), DT),
        ApiErrorId.ERR_DUPLICATE_DIET_MONTH.value)


# ---------------- Corner B: reverse-reachability listing ----------------

def test_diet_visits_reverse_reachability_list(api):
    """PRD §4 (endpoint): GET /programs/{id}/diet-visits — "List a program's
    supervised-diet visits". PRD §3.3: "A Dietitian logs a supervised-diet visit against
    the program, recording the month_index it satisfies".

    Design: Corner/endpoints/diet_visits_reverse_reachability_list
    """
    plan = create_insurance_plan(api, required_supervised_diet_months=6)
    prog = create_clearance_in_progress_program(api, payment_pathway="INSURANCE",
                                                insurance_plan_id=plan["id"])
    dv = add_diet_visit(api, prog["id"], month_index=1, visit_date="2026-02-01", weight_kg=119)
    data = validate_success(api.list_diet_visits(prog["id"], DT))
    assert any(v["id"] == dv["id"] and v["month_index"] == 1 for v in data), \
        "logged diet visit must appear under the program"
