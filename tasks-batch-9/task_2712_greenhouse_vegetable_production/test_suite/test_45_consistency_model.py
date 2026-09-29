"""Immediate visibility of the pest-lock cascade.

One scouting round takes the compartment to LOCKED, and the very next read of the
labor task, the compartment and the crop cycle already shows every hop of the
cascade the lock fired.
"""

from test_helpers import (
    assert_money,
    create_labor_task,
    create_scout_worker,
    create_worker,
    file_observation,
    read_crop_cycle,
    read_labor_task,
    read_worker,
    read_zone,
    setup_transplanted_cycle,
)


def _zone_at_scout_alert_with_a_scheduled_harvest_task():
    """A compartment holding one SCHEDULED future harvest task and one open pest alert.

    The harvest task commits 156.00 US dollars of the compartment's 20000.00 budget,
    and one at-or-above whitefly round has already taken the pest gate to SCOUT_ALERT.
    """
    state = setup_transplanted_cycle(clock="2026-08-06T00:00:00Z")
    state["harvest_worker"] = create_worker(
        full_name="Petra Lund", hourly_rate_usd=19.50, productivity_index=1.00
    )
    state["scout"] = create_scout_worker()
    state["task"] = create_labor_task(
        state["zone"]["id"],
        state["cycle"]["id"],
        state["harvest_worker"]["id"],
        task_type="HARVEST",
        window_start="2026-08-07T07:00:00Z",
        window_end="2026-08-07T16:00:00Z",
        planned_units=4000,
        standard_units_per_hour=500,
    )
    assert_money(state["task"]["planned_cost_usd"], 156.00, "planned_cost_usd")

    state["first_round"] = file_observation(
        state["zone"]["id"],
        state["cycle"]["id"],
        state["scout"]["id"],
        observed_at="2026-08-06T07:00:00Z",
        pest_code="WHITEFLY",
        pest_count_per_plant=0.800,
    )
    mid = read_zone(state["zone"]["id"])
    assert mid["ipm_posture"] == "SCOUT_ALERT", (
        f"one open alert reads SCOUT_ALERT, got {mid['ipm_posture']}"
    )
    assert_money(
        mid["labor_budget_committed_usd"], 156.00, "labor_budget_committed_usd"
    )
    return state


def _file_the_locking_round(state):
    """File the second at-or-above round, which takes the pest gate to LOCKED."""
    locking_round = file_observation(
        state["zone"]["id"],
        state["cycle"]["id"],
        state["scout"]["id"],
        observed_at="2026-08-06T08:00:00Z",
        pest_code="THRIPS",
        pest_count_per_plant=1.100,
    )
    assert locking_round["threshold_status"] == "ABOVE", (
        f"1.100 is above the thrips threshold of 1.000, got {locking_round['threshold_status']}"
    )
    return locking_round


def test_the_pest_lock_cancels_the_scheduled_harvest_on_the_very_next_read(api):
    """PRD §3.6: "Its second hop, caused by the locked posture rather than by the observation, transitions every labor task in that compartment whose status is `SCHEDULED`, whose `task_type` is `HARVEST`, and whose `window_start` is at or after the current logical clock, to `CANCELLED` with `cancel_reason` set to the literal `IPM_POSTURE_LOCK`."

    Design: Corner/consistency_model/immediate_consistency_makes_the_ipm_lock_cascade_visible_on_the_next_read
    """
    state = _zone_at_scout_alert_with_a_scheduled_harvest_task()
    assert state["task"]["status"] == "SCHEDULED", (
        f"the picking shift is still scheduled, got {state['task']['status']}"
    )

    _file_the_locking_round(state)

    # No wait, no retry and no polling: the first read after the round already
    # shows every hop the lock fired.
    task = read_labor_task(state["task"]["id"])
    assert task["status"] == "CANCELLED", (
        f"the locked compartment cancels the future picking shift, got {task['status']}"
    )
    assert task["cancel_reason"] == "IPM_POSTURE_LOCK", (
        f"the cancellation is attributed to the pest lock, got {task['cancel_reason']}"
    )

    zone = read_zone(state["zone"]["id"])
    assert zone["ipm_posture"] == "LOCKED", (
        f"the second open alert locks the compartment, got {zone['ipm_posture']}"
    )
    assert zone["open_pest_alert_count"] == 2, (
        f"two alerts are open, got {zone['open_pest_alert_count']}"
    )


def test_the_cancelled_shift_repays_the_budget_and_flags_the_cycle_at_once(api):
    """PRD §3.6: "Its third hop, caused by each of those cancellations, sets the owning cycle's `labor_shortfall_flag` to true and returns that task's `planned_cost_usd` to the compartment's `labor_budget_remaining_usd` exactly as a manual cancellation would."

    Design: Corner/consistency_model/immediate_consistency_makes_the_ipm_lock_cascade_visible_on_the_next_read
    """
    state = _zone_at_scout_alert_with_a_scheduled_harvest_task()

    _file_the_locking_round(state)

    zone = read_zone(state["zone"]["id"])
    assert_money(zone["labor_budget_committed_usd"], 0.00, "labor_budget_committed_usd")
    assert_money(
        zone["labor_budget_remaining_usd"], 20000.00, "labor_budget_remaining_usd"
    )

    cycle = read_crop_cycle(state["cycle"]["id"])
    assert cycle["labor_shortfall_flag"] is True, (
        f"the cancelled picking shift flags the cycle short of labor, got {cycle['labor_shortfall_flag']}"
    )

    worker = read_worker(state["harvest_worker"]["id"])
    assert worker["committed_hours"] == 0.00, (
        f"the picker's committed hours are released too, got {worker['committed_hours']}"
    )
