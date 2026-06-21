"""Permanency-action error corners: plan completion, TPR gate, hearing prereq, goal mismatch.

Queue B — corner section: errors.
"""
from test_helpers import (
    get_success_data, validate_success, validate_error,
    setup_workers, open_case_with_child, setup_placed_child, set_clock,
    create_active_case_plan, set_plan_compliance, schedule_and_hold_hearing,
)


def test_complete_plan_below_full_compliance_rejected(api):
    """PRD §3.8: "An `ACTIVE` plan may be **completed** only when its `compliance_pct` is at least 100 — every objective met — and a completion attempt on a plan below that mark is rejected with `ERR_PLAN_NOT_COMPLETE`."
    Plan at 4 of 5 = 80.00 (< 100) cannot complete.

    Design: Corner/errors/complete_plan_below_full_compliance_rejected
    """
    w = setup_workers(need_licensing=False)
    set_clock("2026-01-01T00:00:00Z")
    case, child = open_case_with_child(w)
    plan = create_active_case_plan(w, case["id"], objectives_total=5)
    after = set_plan_compliance(w, plan["id"], 4)
    assert after["compliance_pct"] == 80.0
    resp = api.complete_case_plan(plan["id"], w.caseworker)
    validate_error(resp, "ERR_PLAN_NOT_COMPLETE")


def test_end_adopted_without_tpr_rejected(api):
    """PRD §3.7: "An end-to-adoption without the `TERMINATE_RIGHTS` ruling on a `HELD` `TPR` hearing is rejected with `ERR_TPR_NOT_TERMINATED`."
    Goal ADOPTION but no HELD TPR hearing.

    Design: Corner/errors/end_adopted_without_tpr_rejected
    """
    w = setup_workers()
    set_clock("2026-01-01T00:00:00Z")
    case, child, home, placement = setup_placed_child(w)
    # Flip goal to ADOPTION via HELD PERMANENCY hearing; no TPR held.
    # scheduled_at == the clock so the inclusive hold-gate (PRD §3.9) is met.
    schedule_and_hold_hearing(w, case["id"], "PERMANENCY", "CHANGE_GOAL_ADOPTION",
                              scheduled_at="2026-01-01T00:00:00Z")
    resp = api.end_adopted(placement["id"], w.caseworker)
    validate_error(resp, "ERR_TPR_NOT_TERMINATED")


def test_advance_permanency_without_held_hearing_rejected(api):
    """PRD §3.9: "A case advances from `IN_PLACEMENT` to `PERMANENCY_PLANNING` only when a `PERMANENCY` hearing on the case has been `HELD`; without that held permanency hearing the advance is rejected with `ERR_HEARING_PREREQ_MISSING`."

    Design: Corner/errors/advance_permanency_without_held_hearing_rejected
    """
    w = setup_workers()
    set_clock("2026-01-01T00:00:00Z")
    case, child, home, placement = setup_placed_child(w)
    resp = api.advance_permanency(case["id"], w.caseworker)
    validate_error(resp, "ERR_HEARING_PREREQ_MISSING")


def test_end_reunified_with_adoption_goal_mismatch_rejected(api):
    """PRD §3.7: "A caseworker ends an `ACTIVE` placement to reunification when the child's case has `permanency_goal` `REUNIFICATION` and the case's `CasePlan` is `COMPLETED`".
    PRD §3.7: "a goal that does not match the requested action surfaces `ERR_GOAL_MISMATCH`".
    Goal flipped to ADOPTION; end-reunified requires REUNIFICATION.

    Design: Corner/errors/end_reunified_when_goal_is_adoption_goal_mismatch_rejected
    """
    w = setup_workers()
    set_clock("2026-01-01T00:00:00Z")
    case, child, home, placement = setup_placed_child(w, dob="2012-01-01T00:00:00Z")
    # scheduled_at == the clock so the inclusive hold-gate (PRD §3.9) is met.
    schedule_and_hold_hearing(w, case["id"], "PERMANENCY", "CHANGE_GOAL_ADOPTION",
                              scheduled_at="2026-01-01T00:00:00Z")
    case_after = validate_success(api.get_case(case["id"], w.caseworker))
    assert case_after["permanency_goal"] == "ADOPTION"
    resp = api.end_reunified(placement["id"], w.caseworker)
    validate_error(resp, "ERR_GOAL_MISMATCH")
