"""Session completion and goal progress: chronological per-goal latest vs the
forward-looking plan roll-up, the weighted non-linear combination, discontinued
goal exclusion, and completion preconditions.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    TEST_USERS, make_therapist_headers,
    set_clock, create_child, create_therapist, create_finalized_evaluation,
    create_active_plan, create_authorization, add_goal,
    setup_active_care, setup_two_goal_plan, book_appointment_ok, complete_appointment,
    get_goal, get_plan, get_appointment,
)

ADMIN = TEST_USERS["clinic_admin_headers"]


def _ctx_with_one_goal(clock, discipline, weight, baseline, target,
                       authorized_visits=3, planned=60):
    """Build an active-care ctx with a single OPEN goal; return (ctx, goal)."""
    ctx = setup_active_care(clock=clock, discipline=discipline,
                            authorized_visits=authorized_visits, planned_weekly_minutes=planned)
    goal = add_goal(ctx["plan"]["id"], ctx["therapist"]["id"],
                    description="Articulate /r/", weight=weight,
                    baseline_pct=baseline, target_pct=target)
    return ctx, goal


# ─── dual_variant_calc / goal_progress_forward_vs_chronological_divergence ───

def test_latest_progress_uses_session_time_not_insertion_order(api):
    """PRD §2.8: "a back-dated note for an earlier slot does not override the
    value recorded for a later session even if it was entered afterward." A 06-15
    session recording 55 (completed first) keeps `latest_progress_pct` at 55 even
    after a back-dated 06-01 session recording 70 is completed afterward.

    Design: Difficulty/dual_variant_calc/goal_progress_forward_vs_chronological_divergence
    """
    ctx, goal = _ctx_with_one_goal("2026-06-20T12:00:00Z", "SLP", weight=1,
                                   baseline=10, target=60)
    appt_late = book_appointment_ok(ctx, "2026-06-15T09:00:00Z", "2026-06-15T09:45:00Z")
    appt_early = book_appointment_ok(ctx, "2026-06-01T09:00:00Z", "2026-06-01T09:45:00Z")
    # Complete the LATER-dated slot first, recording 55.
    get_success_data(complete_appointment(
        appt_late["id"], ctx["therapist"]["id"],
        narrative="Later dated session.",
        goal_progress_entries=[{"goal_id": goal["id"], "recorded_pct": 55}]))
    # Then complete the EARLIER-dated slot, recording 70 (back-dated).
    get_success_data(complete_appointment(
        appt_early["id"], ctx["therapist"]["id"],
        narrative="Earlier dated session, recorded later.",
        goal_progress_entries=[{"goal_id": goal["id"], "recorded_pct": 70}]))

    assert get_goal(goal["id"])["latest_progress_pct"] == 55, get_goal(goal["id"])


def test_overall_progress_rolls_up_chronological_latest(api):
    """PRD §2.8: "This roll-up is forward-looking: it aggregates the current
    `latest_progress_pct` of every `OPEN` or `MET` goal regardless of the order
    progress was recorded". PRD §2.8: "an attainment ratio is computed as
    `latest_progress_pct` minus `baseline_pct`, divided by `target_pct` minus
    `baseline_pct`, clamped to lie between 0 and 1 inclusive." With latest 55,
    baseline 10, target 60: ratio 0.9 -> 90.0.

    Design: Difficulty/dual_variant_calc/goal_progress_forward_vs_chronological_divergence
    """
    ctx, goal = _ctx_with_one_goal("2026-06-20T12:00:00Z", "SLP", weight=1,
                                   baseline=10, target=60)
    appt_late = book_appointment_ok(ctx, "2026-06-15T09:00:00Z", "2026-06-15T09:45:00Z")
    appt_early = book_appointment_ok(ctx, "2026-06-01T09:00:00Z", "2026-06-01T09:45:00Z")
    get_success_data(complete_appointment(
        appt_late["id"], ctx["therapist"]["id"], narrative="Later dated session.",
        goal_progress_entries=[{"goal_id": goal["id"], "recorded_pct": 55}]))
    get_success_data(complete_appointment(
        appt_early["id"], ctx["therapist"]["id"],
        narrative="Earlier dated session, recorded later.",
        goal_progress_entries=[{"goal_id": goal["id"], "recorded_pct": 70}]))

    assert get_plan(ctx["plan"]["id"])["overall_progress_pct"] == pytest.approx(90.0, abs=0.01)


# ─── combinatorial_formula / goal_progress_weighted_nonlinear_three_inputs ───

def test_weighted_rollup_combines_weight_clamp_and_status(api):
    """PRD §2.8: "The roll-up is 100 multiplied by the sum over the included goals
    of `weight` times that goal's clamped ratio, divided by the sum over the
    included goals of `weight`, with the final result rounded half-up to 2 decimal
    places." Goal A (w2, 20->70) at 45 gives ratio 0.5; Goal B (w3, 0->50) at 50
    gives 1.0: 100*(2*0.5 + 3*1.0)/5 = 80.0.

    Design: Difficulty/combinatorial_formula/goal_progress_weighted_nonlinear_three_inputs
    """
    ctx = setup_two_goal_plan(clock="2026-06-20T12:00:00Z", discipline="OT", severity_score=72)
    appt = book_appointment_ok(ctx, "2026-06-10T09:00:00Z", "2026-06-10T09:45:00Z")
    get_success_data(complete_appointment(
        appt["id"], ctx["therapist"]["id"], narrative="Two-goal session note.",
        goal_progress_entries=[
            {"goal_id": ctx["goal_a"]["id"], "recorded_pct": 45},
            {"goal_id": ctx["goal_b"]["id"], "recorded_pct": 50},
        ]))
    assert get_goal(ctx["goal_a"]["id"])["latest_progress_pct"] == 45
    assert get_plan(ctx["plan"]["id"])["overall_progress_pct"] == pytest.approx(80.0, abs=0.01)


def test_goal_reaching_target_auto_transitions_to_met(api):
    """PRD §3.6: "any goal whose `latest_progress_pct` reaches or exceeds its
    `target_pct` auto-transitions from `OPEN` to `MET`." PRD §2.8: "A `MET` goal
    contributes at full weight because its clamped ratio is 1." Goal B (target 50)
    recorded at exactly 50 becomes MET.

    Design: Difficulty/combinatorial_formula/goal_progress_weighted_nonlinear_three_inputs
    """
    ctx = setup_two_goal_plan(clock="2026-06-20T12:00:00Z", discipline="OT", severity_score=72)
    appt = book_appointment_ok(ctx, "2026-06-10T09:00:00Z", "2026-06-10T09:45:00Z")
    get_success_data(complete_appointment(
        appt["id"], ctx["therapist"]["id"], narrative="Two-goal session note.",
        goal_progress_entries=[
            {"goal_id": ctx["goal_a"]["id"], "recorded_pct": 45},
            {"goal_id": ctx["goal_b"]["id"], "recorded_pct": 50},
        ]))
    assert get_goal(ctx["goal_b"]["id"])["status"] == "MET", get_goal(ctx["goal_b"]["id"])


# ─── Corner: overall_progress_excludes_discontinued_goal ─────────────────────

def test_discontinuing_goal_excludes_it_from_rollup(api):
    """PRD §3.3: "An `Evaluator` or a `Therapist` may discontinue a goal that is
    `OPEN` (otherwise `ERR_INVALID_STATE`), moving it to `DISCONTINUED` and
    removing it from both the numerator and denominator of the plan's
    `overall_progress_pct`, which is then recomputed." With A discontinued only the
    MET goal B remains: 100*(3*1.0)/3 = 100.0.

    Design: Corner/calculations/overall_progress_excludes_discontinued_goal
    """
    ctx = setup_two_goal_plan(clock="2026-06-20T12:00:00Z", discipline="OT", severity_score=72)
    appt = book_appointment_ok(ctx, "2026-06-10T09:00:00Z", "2026-06-10T09:45:00Z")
    get_success_data(complete_appointment(
        appt["id"], ctx["therapist"]["id"], narrative="Recorded both goals.",
        goal_progress_entries=[
            {"goal_id": ctx["goal_a"]["id"], "recorded_pct": 45},
            {"goal_id": ctx["goal_b"]["id"], "recorded_pct": 50},
        ]))
    res = api.discontinue_goal(ctx["goal_a"]["id"], make_therapist_headers(ctx["therapist"]["id"]))
    discontinued = validate_success(res, 200)
    assert discontinued["status"] == "DISCONTINUED"
    assert get_plan(ctx["plan"]["id"])["overall_progress_pct"] == pytest.approx(100.0, abs=0.01)


# ─── Corner: goal_plan_mismatch_on_complete ──────────────────────────────────

def test_complete_with_foreign_goal_rejected(api):
    """PRD §3.6: "`goal_progress_entries`, an array of objects each holding a
    `goal_id` and a `recorded_pct` from 0 to 100, where every `goal_id` must
    belong to the appointment's plan of care (otherwise `ERR_GOAL_PLAN_MISMATCH`)."

    Design: Corner/validations/goal_plan_mismatch_on_complete
    """
    set_clock("2026-06-20T12:00:00Z")
    th = create_therapist(discipline="SLP", max_caseload=9)
    # Plan 1 for child 1, with the appointment under test.
    child1 = create_child(full_name="Child 1")
    ev1 = create_finalized_evaluation(child1["id"], th["id"], discipline="SLP")
    plan1 = create_active_plan(child1["id"], ev1["id"], th["id"])
    # Plan 2 for child 2, owning the foreign goal.
    child2 = create_child(full_name="Child 2")
    ev2 = create_finalized_evaluation(child2["id"], th["id"], discipline="SLP")
    plan2 = create_active_plan(child2["id"], ev2["id"], th["id"])
    goal2 = add_goal(plan2["id"], th["id"], description="Plan-2 goal", weight=1,
                     baseline_pct=0, target_pct=50)
    auth1 = create_authorization(child1["id"], discipline="SLP", authorized_visits=3)
    ctx = {"child": child1, "therapist": th, "auth": auth1, "plan": plan1}
    appt = book_appointment_ok(ctx, "2026-06-10T09:00:00Z", "2026-06-10T09:45:00Z")
    res = complete_appointment(
        appt["id"], th["id"], narrative="Wrong-plan goal entry.",
        goal_progress_entries=[{"goal_id": goal2["id"], "recorded_pct": 30}])
    validate_error(res, "ERR_GOAL_PLAN_MISMATCH")
    assert get_appointment(appt["id"])["status"] == "SCHEDULED"


# ─── Corner: complete_already_completed_appointment_returns_not_scheduled ────

def test_complete_already_completed_rejected(api):
    """PRD §3.6: "A `Therapist` completes a `SCHEDULED` appointment (otherwise
    `ERR_APPOINTMENT_NOT_SCHEDULED`)". A second completion of an already-COMPLETED
    appointment is rejected and no second visit is committed.

    Design: Corner/state_machines/complete_already_completed_appointment_returns_not_scheduled
    """
    ctx = setup_active_care(clock="2026-06-20T12:00:00Z", discipline="SLP", authorized_visits=3)
    appt = book_appointment_ok(ctx, "2026-06-10T09:00:00Z", "2026-06-10T09:45:00Z")
    get_success_data(complete_appointment(appt["id"], ctx["therapist"]["id"],
                                          narrative="First completion."))
    res = complete_appointment(appt["id"], ctx["therapist"]["id"],
                               narrative="Second completion attempt.")
    validate_error(res, "ERR_APPOINTMENT_NOT_SCHEDULED")
    from test_helpers import get_authorization
    assert get_authorization(ctx["auth"]["id"])["committed_visits"] == 1


# ─── Corner: complete_future_appointment_rejected ────────────────────────────

def test_complete_future_appointment_rejected(api):
    """PRD §3.6: "which is allowed only once the logical clock has reached or
    passed `start_time` — a future appointment cannot be completed, and an attempt
    to do so is `ERR_APPOINTMENT_IN_FUTURE`."

    Design: Corner/state_machines/complete_future_appointment_rejected
    """
    # Clock at 2026-06-05; appointment slot at 2026-06-10 (future).
    ctx = setup_active_care(clock="2026-06-05T12:00:00Z", discipline="SLP", authorized_visits=3)
    appt = book_appointment_ok(ctx, "2026-06-10T09:00:00Z", "2026-06-10T09:45:00Z")
    res = complete_appointment(appt["id"], ctx["therapist"]["id"],
                               narrative="Trying to complete future appt.")
    validate_error(res, "ERR_APPOINTMENT_IN_FUTURE")
