"""Season arc: suspend/resume cycle, close cascade, close/reconcile blockers,
run-sweep window checkpoint (PRD §3.1)."""
import pytest

from test_helpers import (
    ApiErrorId,
    collect_confirmed_run,
    create_filling_batch,
    create_sap_run_payload,
    declare_window,
    draw_from_run,
    finish_batch,
    grade_lot,
    make_fieldcrew_headers,
    open_window,
    record_evaluation,
    set_clock,
    setup_live_operation,
    setup_open_season,
    setup_ungraded_lot,
    start_boil,
    validate_error,
    validate_success,
)


def test_collection_rejected_while_suspended(api, manager_headers):
    """PRD §3.1: "suspending moves `OPEN → SUSPENDED` with no further
    preconditions, and while suspended the season blocks sap-run creation and
    weather-window opening."
    PRD §3.3: "the season must be `OPEN` (`ERR_SEASON_NOT_OPEN` /
    `ERR_SEASON_SUSPENDED`)"

    Design: Difficulty/non_linear_state_machine/season_suspend_resume_cycle
    """
    ctx = setup_live_operation()
    suspended = validate_success(api.suspend_season(ctx["season"]["id"], manager_headers), 200)
    assert suspended["status"] == "SUSPENDED"

    res = api.create_sap_run(
        create_sap_run_payload(ctx["bush"]["id"], ctx["window"]["id"],
                               ctx["tapper"]["id"], gallons_collected=10.0),
        make_fieldcrew_headers(ctx["tapper"]["id"]))
    validate_error(res, ApiErrorId.ERR_SEASON_SUSPENDED)


def test_resume_restores_collection(api, manager_headers):
    """PRD §3.1: "Resuming moves `SUSPENDED → OPEN`, again requiring the clock
    date to be within the season's dates."
    PRD §3.3: "A new run begins in `DRAFT`."

    Design: Difficulty/non_linear_state_machine/season_suspend_resume_cycle
    """
    ctx = setup_live_operation()
    validate_success(api.suspend_season(ctx["season"]["id"], manager_headers), 200)
    resumed = validate_success(api.resume_season(ctx["season"]["id"], manager_headers), 200)
    assert resumed["status"] == "OPEN"

    res = api.create_sap_run(
        create_sap_run_payload(ctx["bush"]["id"], ctx["window"]["id"],
                               ctx["tapper"]["id"], gallons_collected=10.0),
        make_fieldcrew_headers(ctx["tapper"]["id"]))
    run = validate_success(res, 201)
    assert run["status"] == "DRAFT"

    season = validate_success(api.get_season(ctx["season"]["id"], manager_headers), 200)
    assert season["status"] == "OPEN"


def test_season_close_cascades_crew_window_run(api, manager_headers):
    """PRD §3.1: "Closing cascades: every crew member of the season in `ACTIVE`
    moves to `RELEASED`; every weather window of the season in `FORECAST` or
    `OPEN` moves to `CLOSED`; and every sap run of the season still in `DRAFT`
    moves to `VOIDED`."

    Design: Corner/state_machines/season_close_cascades_crew_release
    """
    ctx = setup_live_operation()
    run = validate_success(
        api.create_sap_run(
            create_sap_run_payload(ctx["bush"]["id"], ctx["window"]["id"],
                                   ctx["tapper"]["id"], gallons_collected=10.0),
            make_fieldcrew_headers(ctx["tapper"]["id"])),
        201)

    closed = validate_success(api.close_season(ctx["season"]["id"], manager_headers), 200)
    assert closed["status"] == "CLOSED"

    crew = validate_success(api.get_crew_member(ctx["tapper"]["id"], manager_headers), 200)
    assert crew["status"] == "RELEASED"
    run_after = validate_success(api.get_sap_run(run["id"], manager_headers), 200)
    assert run_after["status"] == "VOIDED"
    window = validate_success(api.get_weather_window(ctx["window"]["id"], manager_headers), 200)
    assert window["status"] == "CLOSED"


def test_season_close_blocked_by_boiling_batch(api, manager_headers):
    """PRD §3.1: "Closing a season — from either `OPEN` or `SUSPENDED` —
    requires that no evaporator batch of the season is still in `FILLING` or
    `BOILING` (otherwise `ERR_SEASON_HAS_OPEN_BATCHES`)."

    Design: Corner/state_machines/season_close_blocked_by_boiling_batch
    """
    ctx = setup_live_operation()
    run = collect_confirmed_run(ctx, 10.0, 2.0)
    batch = create_filling_batch(ctx, capacity=200)
    draw_from_run(ctx, batch["id"], run["id"], 10.0)
    start_boil(ctx, batch["id"])

    res = api.close_season(ctx["season"]["id"], manager_headers)
    validate_error(res, ApiErrorId.ERR_SEASON_HAS_OPEN_BATCHES)

    finish_batch(ctx, batch["id"], 66.5, 0.22)
    closed = validate_success(api.close_season(ctx["season"]["id"], manager_headers), 200)
    assert closed["status"] == "CLOSED"


def test_reconcile_blocked_by_ungraded_lot(api, manager_headers):
    """PRD §3.1: "Reconciling a closed season moves `CLOSED → RECONCILED` and
    is blocked when any syrup lot of the season is still `UNGRADED` or `HELD`,
    or when any packaging run against a lot of the season is still `PLANNED`;
    either blocker surfaces as `ERR_RECONCILE_BLOCKED`."

    Design: Corner/state_machines/reconcile_blocked_by_ungraded_lot
    """
    ctx = setup_ungraded_lot(measured_syrup_gallons=3.60, with_grader=True)
    # Evaluation must be recorded while the grader is still ACTIVE — the
    # season-close cascade releases all ACTIVE crew (PRD §3.1), and evaluation
    # requires an ACTIVE evaluator (PRD §3.5).
    record_evaluation(ctx, ctx["lot"]["id"], 80)

    closed = validate_success(api.close_season(ctx["season"]["id"], manager_headers), 200)
    assert closed["status"] == "CLOSED"

    res = api.reconcile_season(ctx["season"]["id"], manager_headers)
    validate_error(res, ApiErrorId.ERR_RECONCILE_BLOCKED)

    lot = grade_lot(ctx, ctx["lot"]["id"], 76.0)
    assert lot["status"] == "GRADED"

    reconciled = validate_success(
        api.reconcile_season(ctx["season"]["id"], manager_headers), 200)
    assert reconciled["status"] == "RECONCILED"


def test_window_auto_close_via_sweep(api, manager_headers):
    """PRD §3.1: "a manager-only run-sweep against a season closes every
    weather window whose `closes_at` is at or before the logical clock (both
    `OPEN → CLOSED` and the missed-window `FORECAST → CLOSED` path)"

    Design: Corner/state_machines/window_auto_close_via_sweep
    """
    season = setup_open_season()
    window = declare_window(season["id"], season["version"])
    open_window(window["id"], "2027-03-02T08:00:00Z")

    set_clock("2027-03-10T00:00:00Z")  # == closes_at
    validate_success(api.run_sweep(season["id"], manager_headers), 200)

    after = validate_success(api.get_weather_window(window["id"], manager_headers), 200)
    assert after["status"] == "CLOSED"
