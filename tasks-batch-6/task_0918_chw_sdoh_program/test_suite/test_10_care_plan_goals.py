"""Care-plan goals: the two progress directions, the closure outcomes and the
disenrolment cascade that defers whatever is still active."""

from test_helpers import (
    assert_pct,
    assert_same_instant,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import SUPERVISOR


def test_progress_diverges_between_the_two_direction_variants(api):
    """PRD §3.6: "Under `INCREASE_GOOD`, the raw percentage is 100 multiplied by
    the amount the current value has risen above baseline, divided by the total
    rise from baseline to target. Under `DECREASE_GOOD`, both the numerator and
    the denominator invert: the raw percentage is 100 multiplied by the amount
    the current value has fallen below baseline, divided by the total fall from
    baseline to target."
    PRD §3.6: "Each measurement recomputes `progress_pct` under the goal's
    direction variant and resets `review_due_at` to the current logical clock
    plus `review_cycle_days` days."

    Design: Corner/calculations/goal_progress_direction_variants_diverge_on_same_numbers
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-01T00:00:00Z", employee_code="C-020",
        mrn="MRN-C20", full_name="Direction Case",
    )
    increasing = fx.create_goal(
        chw_headers, patient["id"], domain="EMPLOYMENT",
        direction="INCREASE_GOOD", baseline_value=40, target_value=60,
        review_cycle_days=30,
    )
    decreasing = fx.create_goal(
        chw_headers, patient["id"], domain="HEALTH_LITERACY",
        direction="DECREASE_GOOD", baseline_value=60, target_value=40,
        review_cycle_days=30,
    )

    rising = validate_success(
        api.record_goal_progress(increasing["id"], {"current_value": 45}, chw_headers)
    )
    falling = validate_success(
        api.record_goal_progress(decreasing["id"], {"current_value": 45}, chw_headers)
    )

    assert_pct(rising["progress_pct"], 25.0, "INCREASE_GOOD progress_pct")
    assert_pct(falling["progress_pct"], 75.0, "DECREASE_GOOD progress_pct")
    assert rising["current_value"] == 45
    assert falling["current_value"] == 45
    assert_same_instant(
        rising["review_due_at"], "2026-07-01T00:00:00Z", "goal.review_due_at"
    )
    assert rising["status"] == "ACTIVE"


def test_closing_a_goal_unmet_opens_an_escalation_and_reopening_counts(api):
    """PRD §3.6: "`NOT_MET` carries a consequence: it opens an escalation with
    `source_flag` of `GOAL_NOT_MET`, `patient_id` naming this goal's patient,
    `status` of `OPEN_TIER_1` and — unlike the system-opened escalations
    elsewhere in this document — `opened_by_user_id` set to the acting caller's
    `X-User-ID`, because a person made this call."
    PRD §3.6: "Re-opening sets `status` back to `ACTIVE`, clears `closed_at` to
    null, increments `reopen_count` by 1, and recomputes `review_due_at` as the
    current logical clock plus `review_cycle_days` days."

    Design: Corner/state_machines/goal_close_not_met_then_reopen_increments_reopen_count
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-01T00:00:00Z", employee_code="C-011",
        mrn="MRN-C11", full_name="Goal Case",
    )
    goal = fx.create_goal(
        chw_headers, patient["id"], domain="FOOD", direction="INCREASE_GOOD",
        baseline_value=2, target_value=10, review_cycle_days=30,
    )
    fx.close_goal(chw_headers, goal["id"], "NOT_MET")

    fx.set_clock("2026-06-15T00:00:00Z")
    reopened = validate_success(api.reopen_goal(goal["id"], chw_headers))

    assert reopened["status"] == "ACTIVE"
    assert reopened["closed_at"] is None
    assert reopened["reopen_count"] == 1
    assert_same_instant(
        reopened["review_due_at"], "2026-07-15T00:00:00Z", "goal.review_due_at"
    )
    assert_pct(reopened["progress_pct"], 0.0, "goal.progress_pct")

    rows, meta = validate_paginated(
        api.list_escalations(chw_headers, params={"patient_id": patient["id"]})
    )
    assert meta["total_count"] == 1, (
        f"closing the goal unmet opens exactly one escalation, got {meta['total_count']}"
    )
    assert rows[0]["source_flag"] == "GOAL_NOT_MET"


def test_disenrolment_defers_active_goals_and_leaves_closed_ones_alone(api):
    """PRD §3.1: "`DISENROLL` moves a patient from `ENROLLED` to `DISENROLLED`
    and, as a cascade, sets every one of that patient's care-plan goals
    currently in `ACTIVE` to `DEFERRED`, stamping each goal's `closed_at` with
    the current logical clock."
    PRD §3.6: "Closure takes an `outcome` of `MET`, `NOT_MET` or `DEFERRED`, and
    all three apply only from `ACTIVE`, stamping `closed_at` with the current
    logical clock. `MET` additionally requires `progress_pct` to be exactly
    100.0; a goal short of full achievement cannot be marked met and is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/patient_disenroll_cascade_defers_active_goals
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-01T00:00:00Z", employee_code="C-013",
        mrn="MRN-C13", full_name="Cascade Case",
    )
    active_goal = fx.create_goal(
        chw_headers, patient["id"], domain="HOUSING",
        direction="INCREASE_GOOD", baseline_value=0, target_value=4,
    )
    met_goal = fx.create_goal(
        chw_headers, patient["id"], domain="TRANSPORT",
        direction="DECREASE_GOOD", baseline_value=8, target_value=2,
    )
    fx.record_progress(chw_headers, met_goal["id"], 2)
    fx.close_goal(chw_headers, met_goal["id"], "MET")

    disenrolled = validate_success(
        api.update_patient(
            patient["id"], {"enrollment_action": "DISENROLL"}, SUPERVISOR
        )
    )
    assert disenrolled["enrollment_status"] == "DISENROLLED"

    deferred = fx.read_goal(active_goal["id"])
    assert deferred["status"] == "DEFERRED", (
        f"the disenrolment cascade defers an ACTIVE goal, got {deferred['status']}"
    )
    assert_same_instant(
        deferred["closed_at"], "2026-06-01T00:00:00Z", "deferred goal.closed_at"
    )

    untouched = fx.read_goal(met_goal["id"])
    assert untouched["status"] == "MET", (
        "a goal already closed is not re-closed by the cascade"
    )
    assert_pct(untouched["progress_pct"], 100.0, "met goal.progress_pct")
