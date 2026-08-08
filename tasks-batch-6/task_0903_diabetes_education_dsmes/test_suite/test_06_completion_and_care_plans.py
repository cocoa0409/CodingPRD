"""Auto-completion cascade to care-plan projection, and the dual projected vs
measured A1c outcome.

Queue A (Difficulty): transitive_cascade (complete→auto-complete→projection),
dual_variant_calc (projected vs measured A1c).
"""
from test_helpers import (
    validate_success, get_success_data, TEST_USERS,
    setup_active_enrollment,
)
import test_helpers as th

COORD = TEST_USERS["coordinator_headers"]


# --- tc_complete_autocomplete_careplan_depth3 ---
def test_completion_auto_completes_enrollment(api):
    """PRD §3.6: "If, after that recomputation, `final_hours_used` is at least
    `required_curriculum_hours`, the enrollment automatically transitions from
    `ACTIVE` to the terminal `COMPLETED` state".

    A curriculum requiring 1.0h and a single 60-min completion (final 1.0h)
    auto-completes the enrollment.

    Design: Difficulty/transitive_cascade/tc_complete_autocomplete_careplan_depth3
    """
    ctx = setup_active_enrollment(api, required_hours=1.0)
    th.make_care_plan(api, ctx, goal_description="Reach A1c 7", target_a1c=7.0)
    sess = th.schedule_individual_session_ok(api, ctx, "2026-05-14T09:00:00Z", "2026-05-14T10:00:00Z")
    th.complete(api, ctx, sess["id"], 60)
    enr = th.get_enrollment(api, ctx["enrollment_id"])
    assert enr["final_hours_used"] == 1.0, f"final_hours_used must be 1.0, got {enr['final_hours_used']}"
    assert enr["status"] == "COMPLETED", f"enrollment must auto-COMPLETE, got {enr['status']}"


def test_auto_completion_recomputes_open_care_plan_projection(api):
    """PRD §3.6: "that transition in turn recomputes `projected_a1c_delta` on each
    `OPEN` care plan of the enrollment from the new `final_hours_used`."
    PRD §3.9: "it is the enrollment's `final_hours_used` multiplied by 0.1
    percentage points of reduction per completed hour".

    After auto-completion at 1.0 final hours the OPEN plan's projected_a1c_delta
    becomes 1.0 * 0.1 = 0.1.

    Design: Difficulty/transitive_cascade/tc_complete_autocomplete_careplan_depth3
    """
    ctx = setup_active_enrollment(api, required_hours=1.0)
    plan = th.make_care_plan(api, ctx, goal_description="Reach A1c 7", target_a1c=7.0)
    sess = th.schedule_individual_session_ok(api, ctx, "2026-05-14T09:00:00Z", "2026-05-14T10:00:00Z")
    th.complete(api, ctx, sess["id"], 60)
    updated = th.get_care_plan(api, plan["id"])
    assert updated["projected_a1c_delta"] == 0.1, \
        f"projected_a1c_delta must be recomputed to 0.1, got {updated['projected_a1c_delta']}"


# --- dv_projected_vs_measured_a1c ---
def test_projected_a1c_delta_from_hours_capped(api):
    """PRD §3.9: "it is the enrollment's `final_hours_used` multiplied by 0.1
    percentage points of reduction per completed hour, but never more than the
    room between the patient's `baseline_a1c` and a clinical floor of 6.5 — that
    is, it is capped at `baseline_a1c` minus 6.5".

    With 4.0 final hours and baseline 8.0, projected = min(4.0*0.1, 8.0-6.5) =
    min(0.4, 1.5) = 0.4.

    Design: Difficulty/dual_variant_calc/dv_projected_vs_measured_a1c
    """
    ctx = setup_active_enrollment(api, baseline_a1c=8.0)
    sess = th.schedule_individual_session_ok(api, ctx, "2026-05-06T09:00:00Z", "2026-05-06T13:00:00Z")
    th.complete(api, ctx, sess["id"], 240)
    plan = th.make_care_plan(api, ctx, goal_description="Lower A1c below 7", target_a1c=7.0)
    assert plan["projected_a1c_delta"] == 0.4, \
        f"projected_a1c_delta must be 0.4, got {plan['projected_a1c_delta']}"


def test_final_a1c_delta_from_measured_lab_on_close(api):
    """PRD §3.9: "in both cases `measured_a1c` is recorded and `final_a1c_delta`
    is set to the patient's `baseline_a1c` minus the `measured_a1c`, carried to
    one decimal with round-half-up."

    Closing MET with measured 7.2 against baseline 8.0 yields final_a1c_delta 0.8.

    Design: Difficulty/dual_variant_calc/dv_projected_vs_measured_a1c
    """
    ctx = setup_active_enrollment(api, baseline_a1c=8.0)
    sess = th.schedule_individual_session_ok(api, ctx, "2026-05-06T09:00:00Z", "2026-05-06T13:00:00Z")
    th.complete(api, ctx, sess["id"], 240)
    plan = th.make_care_plan(api, ctx, goal_description="Lower A1c below 7", target_a1c=7.0)
    closed = validate_success(
        api.close_care_plan(plan["id"], {"outcome": "MET", "measured_a1c": 7.2}, ctx["diet"]), 200
    )
    assert closed["final_a1c_delta"] == 0.8, \
        f"final_a1c_delta must be 0.8, got {closed['final_a1c_delta']}"
    assert closed["status"] == "MET", f"plan must be MET, got {closed['status']}"
