"""Performances: scheduling gates, caps, curtain gap, marking (PRD §3.4)."""
from test_helpers import (
    PRODUCER,
    TOUR_MANAGER,
    TREASURER,
    ApiErrorId,
    add_stop,
    advance_stop,
    cancel_performance,
    contract_stop,
    create_performance_payload,
    create_tour,
    create_venue,
    get_stop,
    get_stop_settlement,
    get_success_data,
    play_performance,
    schedule_performance,
    setup_advanced_stop,
    setup_ready_stop,
    validate_error,
    validate_success,
)


def test_performance_schedule_on_advanced_stop_rejected(api):
    """PRD §3.4: "Once a stop stands at `READY` (or is already `PLAYING`), a
    `TourManager` schedules performances"
    PRD §3.4: "Scheduling against a stop in any other booking state is rejected
    with `ERR_STOP_NOT_SCHEDULABLE`."

    Design: Difficulty/cross_entity_state_dependency/performance_requires_stop_ready_or_playing
    """
    ctx = setup_advanced_stop()
    resp = api.create_performance(
        ctx["stop"]["id"], create_performance_payload(), TOUR_MANAGER)
    validate_error(resp, ApiErrorId.ERR_STOP_NOT_SCHEDULABLE)


def test_performance_schedule_on_ready_and_playing_ok(api):
    """PRD §3.4: "Once a stop stands at `READY` (or is already `PLAYING`), a
    `TourManager` schedules performances"
    PRD §3.4: "The first `PLAYED` performance of a stop flips the stop from
    `READY` to `PLAYING`."

    Design: Difficulty/cross_entity_state_dependency/performance_requires_stop_ready_or_playing
    """
    ctx = setup_ready_stop()
    stop = ctx["stop"]

    perf1 = schedule_performance(stop["id"], perf_date="2026-09-08")
    assert perf1["status"] == "SCHEDULED"
    # A second still-SCHEDULED show keeps the stop open: with only one
    # performance, marking it PLAYED resolves every performance and the stop
    # would close in the same request (PRD §3.4 auto-close).
    schedule_performance(stop["id"], perf_date="2026-09-09")

    play_performance(perf1["id"], 750_000)
    assert get_stop(stop["id"])["booking_status"] == "PLAYING"

    # Scheduling remains legal once the stop is PLAYING.
    perf3 = schedule_performance(stop["id"], perf_date="2026-09-10")
    assert perf3["status"] == "SCHEDULED"


def test_weekly_cap_eighth_show_allowed(api):
    """PRD §3.4: "The week is capped at eight shows: the count of performances in
    `SCHEDULED` or `PLAYED` whose `perf_date` lies within the play week must be
    below eight before a new one is added — the eighth is allowed, the ninth is
    rejected with `ERR_WEEKLY_SHOW_CAP`."

    Design: Difficulty/boundary_precision_check/weekly_cap_eighth_ok_ninth_fails
    """
    ctx = setup_ready_stop()
    stop_id = ctx["stop"]["id"]
    dates = ["2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10",
             "2026-09-11", "2026-09-12"]
    for d in dates:
        resp = api.create_performance(
            stop_id, create_performance_payload(perf_date=d), TOUR_MANAGER)
        validate_success(resp, 201)
    validate_success(api.create_performance(
        stop_id, create_performance_payload(perf_date="2026-09-13", curtain_time="14:00"),
        TOUR_MANAGER), 201)
    # Eighth show shares Sunday with a legal 270-minute gap (14:00 + 150 + 120
    # = 16:30 <= 19:00).
    eighth = api.create_performance(
        stop_id,
        create_performance_payload(perf_date="2026-09-13", curtain_time="19:00"),
        TOUR_MANAGER,
    )
    validate_success(eighth, 201)


def test_weekly_cap_ninth_show_rejected(api):
    """PRD §3.4: "The week is capped at eight shows: the count of performances in
    `SCHEDULED` or `PLAYED` whose `perf_date` lies within the play week must be
    below eight before a new one is added — the eighth is allowed, the ninth is
    rejected with `ERR_WEEKLY_SHOW_CAP`."

    Design: Difficulty/boundary_precision_check/weekly_cap_eighth_ok_ninth_fails
    """
    ctx = setup_ready_stop()
    stop_id = ctx["stop"]["id"]
    dates = ["2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10",
             "2026-09-11", "2026-09-12"]
    for d in dates:
        validate_success(api.create_performance(
            stop_id, create_performance_payload(perf_date=d), TOUR_MANAGER), 201)
    validate_success(api.create_performance(
        stop_id, create_performance_payload(perf_date="2026-09-13", curtain_time="14:00"),
        TOUR_MANAGER), 201)
    validate_success(api.create_performance(
        stop_id,
        create_performance_payload(perf_date="2026-09-13", curtain_time="19:00"),
        TOUR_MANAGER), 201)

    # Ninth show on a single-show day (Friday) with a legal curtain gap
    # (19:30 + 150 + 120 = 22:00), so only the weekly cap can fire.
    resp = api.create_performance(
        stop_id,
        create_performance_payload(perf_date="2026-09-11", curtain_time="22:00"),
        TOUR_MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_WEEKLY_SHOW_CAP)


def test_curtain_gap_below_minimum_rejected(api):
    """PRD §3.4: "And when two performances share a date, the later `curtain_time` must be at least the earlier curtain time plus the earlier show’s `duration_minutes` plus 120 minutes of turnaround; equality passes, anything shorter is rejected with `ERR_CURTAIN_GAP_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/same_day_curtain_gap
    """
    ctx = setup_ready_stop()
    stop_id = ctx["stop"]["id"]
    schedule_performance(stop_id, perf_date="2026-09-08", curtain_time="14:00",
                         duration_minutes=150)

    # 14:00 + 150 + 120 = 16:50; 16:49 is one minute short.
    resp = api.create_performance(
        stop_id,
        create_performance_payload(perf_date="2026-09-08", curtain_time="16:49"),
        TOUR_MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_CURTAIN_GAP_CONFLICT)


def test_curtain_gap_exact_equality_passes(api):
    """PRD §3.4: "And when two performances share a date, the later `curtain_time` must be at least the earlier curtain time plus the earlier show’s `duration_minutes` plus 120 minutes of turnaround; equality passes, anything shorter is rejected with `ERR_CURTAIN_GAP_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/same_day_curtain_gap
    """
    ctx = setup_ready_stop()
    stop_id = ctx["stop"]["id"]
    schedule_performance(stop_id, perf_date="2026-09-08", curtain_time="14:00",
                         duration_minutes=150)

    # Exactly 18:30 == 14:00 + 150 minutes + 120 minutes: equality passes.
    resp = api.create_performance(
        stop_id,
        create_performance_payload(perf_date="2026-09-08", curtain_time="18:30"),
        TOUR_MANAGER,
    )
    validate_success(resp, 201)


def test_daily_cap_third_show_returns_error(api):
    """PRD §3.4: "A single day hosts at most two performances: a third
    performance on the same `perf_date` is rejected with `ERR_DAILY_SHOW_CAP`."

    Design: Corner/validations/daily_cap_third_show_returns_error
    """
    ctx = setup_ready_stop()
    stop_id = ctx["stop"]["id"]
    schedule_performance(stop_id, perf_date="2026-09-08", curtain_time="12:00",
                         duration_minutes=60)
    # Gap exactly legal: 12:00 + 60 + 120 = 15:00.
    schedule_performance(stop_id, perf_date="2026-09-08", curtain_time="15:00",
                         duration_minutes=60)

    # Third same-date show, gap-legal (15:00 + 60 + 120 = 17:00) but count-capped.
    resp = api.create_performance(
        stop_id,
        create_performance_payload(perf_date="2026-09-08", curtain_time="17:00",
                                   duration_minutes=60),
        TOUR_MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_DAILY_SHOW_CAP)


def test_performance_outside_week_returns_error(api):
    """PRD §3.4: "The date must fall within the play week — on or after
    `play_week_start` and on or before `play_week_end`, both ends inclusive —
    else `ERR_PERFORMANCE_OUTSIDE_WEEK`."

    Design: Corner/validations/performance_outside_week_returns_error
    """
    ctx = setup_ready_stop()
    # Play week is 2026-09-07..2026-09-13 inclusive; 2026-09-14 is one day past.
    resp = api.create_performance(
        ctx["stop"]["id"],
        create_performance_payload(perf_date="2026-09-14"),
        TOUR_MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_PERFORMANCE_OUTSIDE_WEEK)


def test_performance_double_play_returns_invalid_state(api):
    """PRD §3.4: "Both markings are only legal from `SCHEDULED`; acting on a
    terminal performance draws `ERR_PERFORMANCE_INVALID_STATE`."

    Design: Corner/state_machines/performance_double_play_returns_invalid_state
    """
    ctx = setup_ready_stop()
    stop_id = ctx["stop"]["id"]
    perf1 = schedule_performance(stop_id, perf_date="2026-09-08")
    schedule_performance(stop_id, perf_date="2026-09-09")  # keeps stop PLAYING
    play_performance(perf1["id"], 750_000)

    resp = api.put_performance(perf1["id"], {"status": "PLAYED", "gross_cents": 999_999},
                               TREASURER)
    validate_error(resp, ApiErrorId.ERR_PERFORMANCE_INVALID_STATE)

    perfs = get_success_data(api.list_performances(stop_id, PRODUCER))
    stored = next(p for p in perfs if p["id"] == perf1["id"])
    assert stored["gross_cents"] == 750_000, "Rejected re-marking must not overwrite gross"


def test_auto_close_creates_settlement_with_system_gross(api):
    """PRD §3.4: "And when every performance of the stop has resolved — each `PLAYED` or `CANCELLED` — with at least one performance existing, the stop closes: `booking_status` becomes `CLOSED` and the server auto-creates the stop’s settlement in `DRAFT` with `system_gross_cents` frozen as the sum of `gross_cents` over the stop’s `PLAYED` performances."

    Design: Corner/state_machines/auto_close_creates_settlement_with_system_gross
    """
    ctx = setup_ready_stop()
    stop_id = ctx["stop"]["id"]
    perf1 = schedule_performance(stop_id, perf_date="2026-09-08")
    perf2 = schedule_performance(stop_id, perf_date="2026-09-09")
    play_performance(perf1["id"], 750_000)

    cancel_performance(perf2["id"])

    stop = get_stop(stop_id)
    assert stop["booking_status"] == "CLOSED", (
        "The stop closes once every performance is PLAYED or CANCELLED"
    )
    settlement = get_stop_settlement(stop_id)
    assert settlement is not None, "Auto-close must create the settlement"
    assert settlement["status"] == "DRAFT"
    assert settlement["system_gross_cents"] == 750_000, (
        "The CANCELLED performance contributes nothing to system_gross_cents"
    )


def test_shape_beats_state_on_played_negative_gross(api):
    """PRD §3.4: "The `Treasurer` marks it `PLAYED`, recording the performance’s `gross_cents` — which must be present and non-negative, with 0 a perfectly valid played gross for a papered house."
    PRD §2.8: "Third comes request shape (priority 4): required fields present,
    unknown fields rejected, enums valid, and numeric ranges respected — cents
    non-negative"
    PRD §2.8: "Fourth come state guards (priority 5, all HTTP 409)"

    Design: Difficulty/priority_pair_validation_conflict/shape_beats_state_on_played
    """
    ctx = setup_ready_stop()
    perf = schedule_performance(ctx["stop"]["id"], perf_date="2026-09-08")
    cancel_performance(perf["id"])

    # Both rules fail: negative gross (shape) and terminal source state. The
    # pipeline evaluates shape before state.
    resp = api.put_performance(perf["id"], {"status": "PLAYED", "gross_cents": -5},
                               TREASURER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_shape_beats_state_state_only_valid_gross(api):
    """PRD §3.4: "Both markings are only legal from `SCHEDULED`; acting on a
    terminal performance draws `ERR_PERFORMANCE_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/shape_beats_state_on_played
    """
    ctx = setup_ready_stop()
    perf = schedule_performance(ctx["stop"]["id"], perf_date="2026-09-08")
    schedule_performance(ctx["stop"]["id"], perf_date="2026-09-09")  # keep stop open
    cancel_performance(perf["id"])

    # Valid shape, invalid source state: the state guard fires in isolation.
    resp = api.put_performance(perf["id"], {"status": "PLAYED", "gross_cents": 100},
                               TREASURER)
    validate_error(resp, ApiErrorId.ERR_PERFORMANCE_INVALID_STATE)
