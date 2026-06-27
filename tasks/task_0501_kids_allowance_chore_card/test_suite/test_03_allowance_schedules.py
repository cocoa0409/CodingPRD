"""Scheduled allowance transfers: conservation, sweep outcomes, spacing, lifecycle.

Covers difficulty queue (compensating_invariant allowance run, resource_temporal_overlap schedule
buffer) and corner queue (calculations, state_machines, validations, scheduled_actions) instances
rooted in PRD Sections 3.4, 2.9.
"""
from test_helpers import (
    validate_success, validate_error,
    setup_due_schedule, setup_family_with_child, create_schedule, run_due_allowances,
    set_clock,
)
from test_helpers.factories import create_schedule_payload


# ─── compensating_invariant: allowance run conserves wallet + jars ──────────
def test_executed_allowance_run_conserves_money(api):
    """PRD 3.4: "if the family's `funding_balance_cents` is at least the schedule's `amount_cents`, the run debits the funding wallet, credits the schedule's payout jar, and records `EXECUTED"
    PRD 3.4: "An executed run conserves money exactly: the family wallet plus the sum of all of a child's jar balances after the run equals the same total before the run — a run only moves money between the wallet and the jars and never creates it."

    Design: Difficulty/compensating_invariant/allowance_run_conserves_family_wallet_plus_jars
    """
    fam, child, sched, spend_jar_id, ph = setup_due_schedule(
        deposit_cents=10_000, amount_cents=2500, clock_iso="2026-03-01T00:00:00Z",
        next_run_at="2026-03-01T00:00:00Z", cadence_days=7, payout_jar_type="SPEND")

    run_due_allowances()

    fam_after = validate_success(api.get_family(fam["id"], ph), 200)
    jar_after = validate_success(api.get_jar(spend_jar_id, ph), 200)
    assert fam_after["funding_balance_cents"] == 7500
    assert jar_after["balance_cents"] == 2500


def test_executed_run_records_executed_outcome(api):
    """PRD 3.4: "The sweep finds every schedule whose `status` is `ACTIVE` and whose `next_run_at` is at or before the current clock, and for each due schedule whose family is `ACTIVE` it records an `AllowanceRun`."
    PRD 3.4: "if the family's `funding_balance_cents` is at least the schedule's `amount_cents`, the run debits the funding wallet, credits the schedule's payout jar, and records `EXECUTED"

    Design: Difficulty/compensating_invariant/allowance_run_conserves_family_wallet_plus_jars
    """
    fam, child, sched, spend_jar_id, ph = setup_due_schedule(
        deposit_cents=10_000, amount_cents=2500, clock_iso="2026-03-01T00:00:00Z",
        next_run_at="2026-03-01T00:00:00Z", cadence_days=7, payout_jar_type="SPEND")

    run_due_allowances()
    runs = validate_success(api.list_runs(sched["id"], ph), 200)
    assert len(runs) == 1
    assert runs[0]["outcome"] == "EXECUTED"


# ─── resource_temporal_overlap: schedule closed-buffer conflict ─────────────
def test_schedule_within_seven_day_buffer_rejected(api):
    """PRD 3.4: "a new active schedule must be spaced from every existing active schedule on the same child that shares the same `payout_jar_type`: the absolute gap between the new schedule's `next_run_at` and each such existing schedule's `next_run_at` must be at least seven days, measured as a closed buffer so that schedules positioned exactly seven days apart are accepted while anything tighter is rejected with `ERR_SCHEDULE_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/allowance_schedule_closed_buffer_conflict_rejected
    """
    set_clock("2026-03-01T00:00:00Z")
    fam, child, ph = setup_family_with_child(deposit_cents=0)
    create_schedule(child["id"], ph, 1000, 30, "2026-03-10T00:00:00Z", payout_jar_type="SPEND")

    # gap to 2026-03-15 is 5 days < 7 -> conflict
    res = api.create_allowance_schedule(
        child["id"],
        create_schedule_payload(500, 30, "2026-03-15T00:00:00Z", payout_jar_type="SPEND"),
        ph)
    validate_error(res, "ERR_SCHEDULE_WINDOW_CONFLICT")


def test_schedule_exactly_seven_days_apart_accepted(api):
    """PRD 3.4: "measured as a closed buffer so that schedules positioned exactly seven days apart are accepted while anything tighter is rejected with `ERR_SCHEDULE_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/allowance_schedule_closed_buffer_conflict_rejected
    """
    set_clock("2026-03-01T00:00:00Z")
    fam, child, ph = setup_family_with_child(deposit_cents=0)
    create_schedule(child["id"], ph, 1000, 30, "2026-03-10T00:00:00Z", payout_jar_type="SPEND")

    # gap to 2026-03-17 is exactly 7 days -> accepted
    sched2 = validate_success(api.create_allowance_schedule(
        child["id"],
        create_schedule_payload(500, 30, "2026-03-17T00:00:00Z", payout_jar_type="SPEND"),
        ph), 201)
    assert sched2["status"] == "ACTIVE"


# ─── corner calculations: skipped insufficient funds ────────────────────────
def test_allowance_run_skipped_insufficient_funds(api):
    """PRD 3.4: "otherwise it records `SKIPPED_INSUFFICIENT_FUNDS` and moves no money. Either way the schedule's `next_run_at` advances by `cadence_days`, so a skipped run does not stall the cadence."

    Design: Corner/calculations/allowance_run_skipped_insufficient_funds
    """
    fam, child, sched, spend_jar_id, ph = setup_due_schedule(
        deposit_cents=1000, amount_cents=2500, clock_iso="2026-03-01T00:00:00Z",
        next_run_at="2026-03-01T00:00:00Z", cadence_days=7, payout_jar_type="SPEND")

    run_due_allowances()

    fam_after = validate_success(api.get_family(fam["id"], ph), 200)
    jar_after = validate_success(api.get_jar(spend_jar_id, ph), 200)
    runs = validate_success(api.list_runs(sched["id"], ph), 200)
    assert fam_after["funding_balance_cents"] == 1000
    assert jar_after["balance_cents"] == 0
    assert len(runs) == 1
    assert runs[0]["outcome"] == "SKIPPED_INSUFFICIENT_FUNDS"


# ─── corner state_machines: paused schedule skipped by sweep ────────────────
def test_paused_schedule_skipped_by_run_sweep(api):
    """PRD 3.4: "Pausing moves it from `ACTIVE` to `PAUSED`, and paused schedules are skipped by the run sweep."

    Design: Corner/state_machines/paused_schedule_skipped_by_run_sweep
    """
    fam, child, sched, spend_jar_id, ph = setup_due_schedule(
        deposit_cents=10_000, amount_cents=2500, clock_iso="2026-03-01T00:00:00Z",
        next_run_at="2026-03-01T00:00:00Z", cadence_days=7, payout_jar_type="SPEND")
    validate_success(api.pause_schedule(sched["id"], ph), 200)
    set_clock("2026-03-02T00:00:00Z")

    run_due_allowances()

    fam_after = validate_success(api.get_family(fam["id"], ph), 200)
    runs = validate_success(api.list_runs(sched["id"], ph), 200)
    assert fam_after["funding_balance_cents"] == 10_000
    assert len(runs) == 0


def test_resume_from_active_returns_invalid_state(api):
    """PRD 3.4: "Resuming moves it from `PAUSED` back to `ACTIVE` and leaves `next_run_at` unchanged, making it eligible again."

    A schedule that is already ACTIVE (never paused) cannot be resumed — the transition's source
    state guard rejects with ERR_INVALID_STATE.

    Design: Corner/state_machines/allowance_resume_from_active_returns_invalid_state
    """
    set_clock("2026-03-01T00:00:00Z")
    fam, child, ph = setup_family_with_child(deposit_cents=0)
    sched = create_schedule(child["id"], ph, 1000, 30, "2026-04-01T00:00:00Z", payout_jar_type="SPEND")

    res = api.resume_schedule(sched["id"], ph)
    validate_error(res, "ERR_INVALID_STATE")
    sched_after = validate_success(api.get_allowance_schedule(sched["id"], ph), 200)
    assert sched_after["status"] == "ACTIVE"


# ─── corner scheduled_actions: not-due schedule skipped ─────────────────────
def test_not_due_schedule_skipped_by_sweep(api):
    """PRD 3.4: "The schedule starts `ACTIVE`, and a run is considered due once the logical clock reaches or passes its `next_run_at`."
    PRD 3.4: "The sweep finds every schedule whose `status` is `ACTIVE` and whose `next_run_at` is at or before the current clock"

    Design: Corner/cross_cutting_complexity_layers/scheduled_allowance_not_due_yet_skipped
    """
    fam, child, sched, spend_jar_id, ph = setup_due_schedule(
        deposit_cents=10_000, amount_cents=2500, clock_iso="2026-03-15T00:00:00Z",
        next_run_at="2026-04-01T00:00:00Z", cadence_days=30, payout_jar_type="SPEND")

    run_due_allowances()

    fam_after = validate_success(api.get_family(fam["id"], ph), 200)
    runs = validate_success(api.list_runs(sched["id"], ph), 200)
    assert fam_after["funding_balance_cents"] == 10_000
    assert len(runs) == 0


# ─── corner validations: cadence_days bound ─────────────────────────────────
def test_schedule_cadence_zero_returns_validation(api):
    """PRD 2.9: "the bound checks require that ... cadence_days` is at least one"

    Design: Corner/validations/schedule_cadence_zero_returns_validation
    """
    set_clock("2026-03-01T00:00:00Z")
    fam, child, ph = setup_family_with_child(deposit_cents=0)

    res = api.create_allowance_schedule(
        child["id"],
        create_schedule_payload(1000, 0, "2026-04-01T00:00:00Z", payout_jar_type="SPEND"),
        ph)
    validate_error(res, "ERR_VALIDATION")
