"""Faire-day lifecycle: sales, holds, gates, completion, and weather cancellation."""
from test_helpers import (
    ApiErrorId,
    create_ticket_order_payload,
    create_volunteer_shift_payload,
    get_day,
    get_season,
    make_build_task,
    make_faire_day,
    make_build_season,
    make_season,
    set_clock,
    setup_paid_day_order,
    setup_weather_cascade_scenario,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import OPERATOR, ANY, VOLUNTEER_CO
from test_helpers.test_users import make_guest_headers, make_volunteer_headers


def test_faire_day_initial_state_scheduled(api, operator_headers):
    """PRD §3.6: "The operator schedules each faire day against a `season_id` and a
    `date` that must fall within the season's `opening_date` to `closing_date` span
    inclusive — a date outside the season is an `ERR_INVALID_REQUEST` — while the
    season is `PLANNING` or `BUILD`, else `ERR_SEASON_INVALID_STATE`. The day opens in
    `SCHEDULED` with `tickets_sold_count` at zero."

    Design: Corner/state_machines/faire_day_initial_state_scheduled
    """
    season = make_season(name="Init Revel")
    day = validate_success(
        api.create_faire_day(
            {"season_id": season["id"], "date": "2026-06-06T00:00:00Z"},
            operator_headers,
        ),
        201,
    )
    assert day["status"] == "SCHEDULED"
    assert day["tickets_sold_count"] == 0


def test_faire_day_hold_release_cycle(api, operator_headers, any_headers):
    """PRD §3.6: "Weather management then brackets the sales window: placing the day
    on weather hold moves `OPEN_FOR_SALES` → `WEATHER_HOLD` (else
    `ERR_DAY_NOT_HOLDABLE`), and releasing the hold returns `WEATHER_HOLD` →
    `OPEN_FOR_SALES` (else `ERR_DAY_NOT_ON_HOLD`)."

    Design: Corner/state_machines/faire_day_hold_release_cycle
    """
    season = make_build_season(name="Hold Revel")
    day = make_faire_day(season["id"], "2026-06-06T00:00:00Z")
    validate_success(api.open_sales(day["id"], operator_headers), 200)

    held = validate_success(api.weather_hold(day["id"], operator_headers), 200)
    assert held["status"] == "WEATHER_HOLD"
    released = validate_success(api.release_hold(day["id"], operator_headers), 200)
    assert released["status"] == "OPEN_FOR_SALES"

    # Sales work again after the cycle.
    order = validate_success(
        api.create_ticket_order(
            create_ticket_order_payload(season["id"], faire_day_id=day["id"]),
            make_guest_headers("g-h@example.com"),
        ),
        201,
    )
    assert order["faire_day_id"] == day["id"]


def test_day_sales_and_hold_state_guards(api, operator_headers):
    """PRD §3.6: "Opening sales moves the day `SCHEDULED` → `OPEN_FOR_SALES` (from
    any other state, `ERR_DAY_NOT_OPENABLE`)"
    PRD §3.6: "placing the day on weather hold moves `OPEN_FOR_SALES` →
    `WEATHER_HOLD` (else `ERR_DAY_NOT_HOLDABLE`), and releasing the hold returns
    `WEATHER_HOLD` → `OPEN_FOR_SALES` (else `ERR_DAY_NOT_ON_HOLD`)."

    Design: Corner/errors/day_sales_and_hold_state_guards
    """
    season = make_build_season(name="DayGuard Revel")
    day_open = make_faire_day(season["id"], "2026-06-06T00:00:00Z")
    day_sched = make_faire_day(season["id"], "2026-06-07T00:00:00Z")
    validate_success(api.open_sales(day_open["id"], operator_headers), 200)

    res = api.open_sales(day_open["id"], operator_headers)
    validate_error(res, ApiErrorId.ERR_DAY_NOT_OPENABLE, expected_status=409)

    res = api.weather_hold(day_sched["id"], operator_headers)
    validate_error(res, ApiErrorId.ERR_DAY_NOT_HOLDABLE, expected_status=409)

    res = api.release_hold(day_open["id"], operator_headers)
    validate_error(res, ApiErrorId.ERR_DAY_NOT_ON_HOLD, expected_status=409)


def test_day_operation_error_ladder(api, operator_headers, volunteer_coordinator_headers):
    """PRD §3.6: "The day must be in `OPEN_FOR_SALES` (else `ERR_DAY_NOT_OPENABLE`),
    the season must be `OPEN` (else `ERR_SEASON_NOT_OPEN`), and the logical clock's
    calendar date must equal the day's `date` (else `ERR_DAY_NOT_TODAY`)."
    PRD §3.6: "Completing the day moves `OPERATING` → `COMPLETED`: the day must be
    `OPERATING` (else `ERR_DAY_NOT_COMPLETABLE`) and every volunteer shift of the day
    must already stand in a terminal state — `WORKED`, `NO_SHOW`, or `CANCELLED` —
    else `ERR_OPEN_SHIFTS_EXIST`."
    PRD §3.8: "The faire day must be `SCHEDULED` or `OPEN_FOR_SALES` — staffing a day
    already holding, operating, or finished fails with `ERR_DAY_NOT_STAFFABLE`"

    Design: Corner/validations/day_operation_error_ladder
    """
    set_clock()
    season = make_build_season(name="Ladder Revel", volunteer_min_hours=0)
    day = make_faire_day(season["id"], "2026-06-06T00:00:00Z")
    season = validate_success(api.open_season(season["id"], OPERATOR), 200)
    validate_success(api.open_sales(day["id"], OPERATOR), 200)
    shift = validate_success(
        api.create_volunteer_shift(
            create_volunteer_shift_payload(season["id"], day["id"]),
            make_volunteer_headers("vol-k"),
        ),
        201,
    )
    validate_success(api.confirm_shift(shift["id"], VOLUNTEER_CO), 200)

    # Rung 1: complete requires OPERATING.
    res = api.complete_day(day["id"], OPERATOR)
    validate_error(res, ApiErrorId.ERR_DAY_NOT_COMPLETABLE, expected_status=409)

    # Rung 2: open-gates requires the day's own calendar date.
    res = api.open_gates(day["id"], OPERATOR)
    validate_error(res, ApiErrorId.ERR_DAY_NOT_TODAY, expected_status=409)

    # On the day itself the gates open.
    set_clock("2026-06-06T07:00:00Z")
    operating = validate_success(api.open_gates(day["id"], OPERATOR), 200)
    assert operating["status"] == "OPERATING"

    # Rung 3: staffing an OPERATING day is rejected.
    res = api.create_volunteer_shift(
        create_volunteer_shift_payload(
            season["id"], day["id"], role="INFO",
            start_time="2026-06-06T13:00:00Z", end_time="2026-06-06T17:00:00Z",
        ),
        make_volunteer_headers("vol-l"),
    )
    validate_error(res, ApiErrorId.ERR_DAY_NOT_STAFFABLE, expected_status=409)

    # Rung 4: completion requires all shifts terminal.
    res = api.complete_day(day["id"], OPERATOR)
    validate_error(res, ApiErrorId.ERR_OPEN_SHIFTS_EXIST, expected_status=409)

    validate_success(
        api.close_out_shift(shift["id"], {"outcome": "WORKED"}, VOLUNTEER_CO), 200
    )
    completed = validate_success(api.complete_day(day["id"], OPERATOR), 200)
    assert completed["status"] == "COMPLETED"


def test_cancel_terminal_day_returns_invalid_state(api, operator_headers, any_headers):
    """PRD §3.6: "Weather cancellation is the day's exceptional exit, callable from
    `OPEN_FOR_SALES` or `WEATHER_HOLD` — from any other state it fails with
    `ERR_DAY_NOT_CANCELLABLE`"
    PRD §2.10: "A season's `outstanding_admissions` equals the count of its tickets
    in `VALID` status plus the count of its rain checks in `ISSUED` status."

    Design: Corner/state_machines/cancel_terminal_day_returns_invalid_state
    """
    set_clock()
    season, day, order = setup_paid_day_order(quantity=1, buyer_email="g-t@example.com")
    validate_success(api.cancel_weather(day["id"], OPERATOR), 200)

    # CANCELLED_WEATHER is terminal: a second cancellation is rejected.
    res = api.cancel_weather(day["id"], OPERATOR)
    validate_error(res, ApiErrorId.ERR_DAY_NOT_CANCELLABLE, expected_status=409)

    # The cascade did not re-fire: exactly one rain check stands ISSUED.
    season_after = get_season(season["id"])
    assert season_after["outstanding_admissions"] == 1


def test_weather_call_at_deadline_rejected(api, operator_headers):
    """PRD §3.6: "the call must land strictly before the day's `date` plus the
    season's `weather_call_deadline_hour` hours, and a call at or after that instant
    is rejected with `ERR_WEATHER_CALL_TOO_LATE`."

    Design: Corner/validations/weather_call_at_deadline_rejected
    """
    set_clock()
    season = make_build_season(name="Deadline Revel", weather_call_deadline_hour=6)
    day = make_faire_day(season["id"], "2026-06-06T00:00:00Z")
    validate_success(api.open_sales(day["id"], OPERATOR), 200)

    # Exactly date + 6 hours: the deadline instant itself is already too late.
    set_clock("2026-06-06T06:00:00Z")
    res = api.cancel_weather(day["id"], OPERATOR)
    validate_error(res, ApiErrorId.ERR_WEATHER_CALL_TOO_LATE, expected_status=409)
    assert get_day(day["id"])["status"] == "OPEN_FOR_SALES"


def test_open_sales_blocked_by_pending_build_task(api, operator_headers):
    """PRD §2.6: "If any BuildTask of the season with `phase` `BUILD` has a `status`
    other than `DONE`, the posture is `BLOCKED`."
    PRD §3.6: "Opening sales moves the day `SCHEDULED` → `OPEN_FOR_SALES` (from any
    other state, `ERR_DAY_NOT_OPENABLE`) and is gated on the season twice over: the
    season must be in `BUILD` or `OPEN` (else `ERR_SEASON_INVALID_STATE`), and its
    readiness posture must not be `BLOCKED` (else `ERR_SEASON_POSTURE_BLOCKED`)."

    Design: Difficulty/cross_entity_state_dependency/faire_day_sales_gated_by_season_posture
    """
    set_clock()
    season = make_season(name="Gated Revel", volunteer_min_hours=0)
    task = make_build_task(season["id"], name="Erect main stage", phase="BUILD")
    day = make_faire_day(season["id"], "2026-06-06T00:00:00Z")
    validate_success(api.begin_build(season["id"], OPERATOR), 200)

    assert get_season(season["id"])["readiness_posture"] == "BLOCKED"
    res = api.open_sales(day["id"], OPERATOR)
    validate_error(res, ApiErrorId.ERR_SEASON_POSTURE_BLOCKED, expected_status=409)
    assert get_day(day["id"])["status"] == "SCHEDULED"


def test_open_sales_unblocked_after_build_task_done(api, operator_headers):
    """PRD §2.6: "If none of those conditions hold, the posture is `READY`."
    PRD §3.1: "Completing a `BUILD`-phase task re-derives the posture, which may
    unblock the season."
    PRD §3.6: "Opening sales moves the day `SCHEDULED` → `OPEN_FOR_SALES` (from any
    other state, `ERR_DAY_NOT_OPENABLE`) and is gated on the season twice over: the
    season must be in `BUILD` or `OPEN` (else `ERR_SEASON_INVALID_STATE`), and its
    readiness posture must not be `BLOCKED` (else `ERR_SEASON_POSTURE_BLOCKED`)."

    Design: Difficulty/cross_entity_state_dependency/faire_day_sales_gated_by_season_posture
    """
    set_clock()
    season = make_season(name="Gated Revel", volunteer_min_hours=0)
    task = make_build_task(season["id"], name="Erect main stage", phase="BUILD")
    day = make_faire_day(season["id"], "2026-06-06T00:00:00Z")
    validate_success(api.begin_build(season["id"], OPERATOR), 200)

    validate_success(api.advance_task(task["id"], {"to": "IN_PROGRESS"}, OPERATOR), 200)
    validate_success(api.advance_task(task["id"], {"to": "DONE"}, OPERATOR), 200)
    assert get_season(season["id"])["readiness_posture"] == "READY"

    opened = validate_success(api.open_sales(day["id"], OPERATOR), 200)
    assert opened["status"] == "OPEN_FOR_SALES"


def test_weather_cancellation_cancels_shifts_and_hours(api, operator_headers, any_headers):
    """PRD §3.6: "Second, every volunteer shift of the day in `SIGNED_UP` or
    `CONFIRMED` is cancelled, and the season's `volunteer_confirmed_hours` is
    recomputed with the hours of the cancelled `CONFIRMED` shifts removed."
    PRD §2.6: "The `volunteer_confirmed_hours` figure itself is the sum of `hours`
    over the season's volunteer shifts whose `status` is `CONFIRMED` or `WORKED`;
    shifts in any other status contribute nothing."

    Design: Difficulty/transitive_cascade/weather_cancellation_cascade_shift_hours_posture
    """
    ctx = setup_weather_cascade_scenario()
    before = get_season(ctx["season_id"])
    assert before["volunteer_confirmed_hours"] == 8.0
    assert before["readiness_posture"] == "READY"

    validate_success(api.cancel_weather(ctx["day_id"], OPERATOR), 200)

    for shift_id in ctx["shift_ids"]:
        shift = validate_success(api.get_volunteer_shift(shift_id, ANY), 200)
        assert shift["status"] == "CANCELLED"
    after = get_season(ctx["season_id"])
    assert after["volunteer_confirmed_hours"] == 0


def test_weather_cancellation_flips_posture_and_gates_opening(api, operator_headers):
    """PRD §3.6: "Third, the readiness posture is re-derived from the new
    confirmed-hours figure."
    PRD §2.6: "the season's `volunteer_confirmed_hours` is strictly below its
    `volunteer_min_hours`" yields `CONDITIONAL`, and "Two outward gates read the
    posture: opening the season requires `READY`, and opening sales on any faire day
    is forbidden while the posture is `BLOCKED`."
    PRD §3.1: "Opening the season moves `BUILD` → `OPEN`: it requires the season to
    be in `BUILD` (else `ERR_SEASON_INVALID_STATE`) and the readiness posture to be
    `READY` (else `ERR_SEASON_NOT_READY`)."

    Design: Difficulty/transitive_cascade/weather_cancellation_cascade_shift_hours_posture
    """
    ctx = setup_weather_cascade_scenario()
    validate_success(api.cancel_weather(ctx["day_id"], OPERATOR), 200)

    after = get_season(ctx["season_id"])
    assert after["volunteer_confirmed_hours"] == 0
    assert after["readiness_posture"] == "CONDITIONAL"

    # The L3 posture flip gates the season's own opening.
    res = api.open_season(ctx["season_id"], OPERATOR)
    validate_error(res, ApiErrorId.ERR_SEASON_NOT_READY, expected_status=409)
