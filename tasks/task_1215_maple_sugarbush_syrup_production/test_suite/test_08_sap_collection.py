"""Sap collection gates, run lifecycle, season sap aggregates
(PRD §2.7, §2.8, §3.3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    activate_line,
    api_client,
    begin_tapping,
    collect_confirmed_run,
    create_bush,
    create_filling_batch,
    create_line,
    create_sap_run_payload,
    declare_window,
    draw_from_run,
    hire_active_crew,
    make_fieldcrew_headers,
    open_window,
    set_clock,
    setup_live_operation,
    setup_open_season,
    validate_error,
    validate_success,
)


def create_draft_run(ctx, gallons=10.0, brix=2.0):
    """POST a sap run as the ctx tapper (entity-backed FieldCrew caller)."""
    return api_client.create_sap_run(
        create_sap_run_payload(ctx["bush"]["id"], ctx["window"]["id"],
                               ctx["tapper"]["id"], gallons_collected=gallons,
                               measured_brix=brix),
        make_fieldcrew_headers(ctx["tapper"]["id"]))


def test_state_error_beats_temporal_on_sap_run_create(api, manager_headers):
    """PRD §2.7: "When a single request violates several rules, the server
    reports the violation whose category has the lowest priority number" —
    category 5 ("5. **State precondition** — the target resource is not in a
    valid from-state, covering `ERR_INVALID_STATE` and the specific state-gate
    errors `ERR_SEASON_NOT_OPEN`, `ERR_SEASON_SUSPENDED`,
    `ERR_SUGARBUSH_NOT_LIVE`, `ERR_WINDOW_NOT_OPEN`, `ERR_CREW_NOT_ACTIVE`,
    `ERR_TAP_LINES_NOT_READY`, `ERR_VACUUM_STILL_LOW`, `ERR_BATCH_EMPTY`,
    `ERR_EVAPORATOR_BUSY`, `ERR_LOT_NOT_GRADED`, and `ERR_LOT_NOT_GRADABLE`.")
    beats category 7 ("7. **Clock-vs-window gates** — temporal checks
    (`ERR_OUTSIDE_PRODUCTION_WINDOW`, `ERR_COLLECTED_OUTSIDE_WINDOW`,
    `ERR_AUDIT_NOT_DUE`).").
    PRD §3.3: "Collection is gated on four conditions: the season must be
    `OPEN` (`ERR_SEASON_NOT_OPEN` / `ERR_SEASON_SUSPENDED`); the sugarbush must
    be `LIVE` (`ERR_SUGARBUSH_NOT_LIVE`); the referenced weather window must be
    `OPEN` (`ERR_WINDOW_NOT_OPEN`); and the clock at collection must be
    strictly before the window's `closes_at` (`ERR_COLLECTED_OUTSIDE_WINDOW`)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_sap_run_create
    """
    season = setup_open_season()
    bush = create_bush(season["id"])
    begin_tapping(bush["id"])
    activate_line(create_line(bush["id"])["id"])  # ACTIVE line, but never go-live
    window = declare_window(season["id"], season["version"])
    tapper = hire_active_crew(season["id"], "Tammy Tapper", "TAPPER")
    open_window(window["id"], "2027-03-02T08:00:00Z")

    set_clock("2027-03-11T00:00:00Z")  # at/after closes_at 2027-03-10T00:00:00Z
    ctx = {"season": season, "bush": bush, "window": window, "tapper": tapper}
    res = create_draft_run(ctx, 10.0, 2.0)
    validate_error(res, ApiErrorId.ERR_SUGARBUSH_NOT_LIVE, expected_status=409)


def test_collected_outside_window_when_only_temporal_violated(api, manager_headers):
    """PRD §3.3: "the clock at collection must be strictly before the window's
    `closes_at` (`ERR_COLLECTED_OUTSIDE_WINDOW`)." With the bush LIVE and every
    other gate satisfied, the temporal violation surfaces alone.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_sap_run_create
    """
    ctx = setup_live_operation()
    set_clock("2027-03-11T00:00:00Z")  # at/after closes_at 2027-03-10T00:00:00Z
    res = create_draft_run(ctx, 10.0, 2.0)
    validate_error(res, ApiErrorId.ERR_COLLECTED_OUTSIDE_WINDOW, expected_status=422)


def test_window_not_open_for_sap_run(api, manager_headers):
    """PRD §3.3: "the referenced weather window must be `OPEN`
    (`ERR_WINDOW_NOT_OPEN`)"

    Design: Corner/errors/window_not_open_for_sap_run
    """
    ctx = setup_live_operation(open_the_window=False)  # window stays FORECAST
    set_clock("2027-03-02T08:00:00Z")  # inside the window interval
    res = create_draft_run(ctx, 10.0, 2.0)
    validate_error(res, ApiErrorId.ERR_WINDOW_NOT_OPEN)


def test_voided_run_confirm_terminal_lockdown(api, manager_headers):
    """PRD §3.3: "Confirming a run moves `DRAFT → CONFIRMED`, requires the
    season to be `OPEN`, and makes the run eligible to be drawn into a batch;
    confirming recomputes the season's `total_sap_gallons`." — a VOIDED run is
    not in DRAFT, so confirming it is rejected.
    PRD §2.7: "5. **State precondition** — the target resource is not in a
    valid from-state, covering `ERR_INVALID_STATE` and the specific state-gate
    errors `ERR_SEASON_NOT_OPEN`, `ERR_SEASON_SUSPENDED`,
    `ERR_SUGARBUSH_NOT_LIVE`, `ERR_WINDOW_NOT_OPEN`, `ERR_CREW_NOT_ACTIVE`,
    `ERR_TAP_LINES_NOT_READY`, `ERR_VACUUM_STILL_LOW`, `ERR_BATCH_EMPTY`,
    `ERR_EVAPORATOR_BUSY`, `ERR_LOT_NOT_GRADED`, and `ERR_LOT_NOT_GRADABLE`."

    Design: Corner/state_machines/voided_run_confirm_terminal_lockdown
    """
    ctx = setup_live_operation()
    run = validate_success(create_draft_run(ctx, 10.0, 2.0), 201)
    validate_success(api.void_sap_run(run["id"], manager_headers), 200)

    res = api.confirm_sap_run(run["id"], make_fieldcrew_headers(ctx["tapper"]["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    after = validate_success(api.get_sap_run(run["id"], manager_headers), 200)
    assert after["status"] == "VOIDED"


def test_void_run_with_draws_rejected(api, manager_headers):
    """PRD §3.3: "Voiding a run moves it to `VOIDED`: from `DRAFT`
    unconditionally, but from `CONFIRMED` only when the run has never been
    drawn — that is, when `gallons_remaining` still equals `gallons_collected`
    because no intake of a non-cancelled batch has touched it; otherwise the
    void is rejected with `ERR_RUN_HAS_DRAWS`."

    Design: Corner/errors/void_run_with_draws_rejected
    """
    ctx = setup_live_operation()
    run = collect_confirmed_run(ctx, 10.0, 2.0)
    batch = create_filling_batch(ctx, capacity=200)
    draw_from_run(ctx, batch["id"], run["id"], 4.0)

    res = api.void_sap_run(run["id"], manager_headers)
    validate_error(res, ApiErrorId.ERR_RUN_HAS_DRAWS)

    # Cancelling the FILLING batch returns the drawn gallons (PRD §3.6), so the
    # run is again never-drawn and the void succeeds.
    validate_success(api.cancel_batch(batch["id"], manager_headers), 200)
    voided = validate_success(api.void_sap_run(run["id"], manager_headers), 200)
    assert voided["status"] == "VOIDED"


def test_season_aggregates_status_filter(api, manager_headers):
    """PRD §2.8: "A season's `total_sap_gallons` is the sum of
    `gallons_collected` over its sap runs in status `CONFIRMED` only — runs in
    `DRAFT` or `VOIDED` never count."

    Design: Corner/calculations/season_aggregates_status_filter
    """
    ctx = setup_live_operation()
    run = validate_success(create_draft_run(ctx, 10.0, 2.0), 201)

    season = validate_success(api.get_season(ctx["season"]["id"], manager_headers), 200)
    assert season["total_sap_gallons"] == pytest.approx(0.0, abs=0.004)

    validate_success(
        api.confirm_sap_run(run["id"], make_fieldcrew_headers(ctx["tapper"]["id"])),
        200)
    season = validate_success(api.get_season(ctx["season"]["id"], manager_headers), 200)
    assert season["total_sap_gallons"] == pytest.approx(10.0, abs=0.004)

    validate_success(api.void_sap_run(run["id"], manager_headers), 200)
    season = validate_success(api.get_season(ctx["season"]["id"], manager_headers), 200)
    assert season["total_sap_gallons"] == pytest.approx(0.0, abs=0.004)
