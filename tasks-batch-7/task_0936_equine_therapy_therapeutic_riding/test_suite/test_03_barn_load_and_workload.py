"""The barn: derived load ceiling, capacity ledgers, intervals and holds."""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_horse,
    book_session,
    read_horse,
    read_rider,
    session_payload,
    set_clock,
    setup_active_rider,
    setup_horse_week_at_240,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, CLERK, INTAKE


def test_horse_registration_derives_max_load_lb(api):
    """PRD 3.3: "From `body_weight_lb` the server immediately derives
    `max_load_lb` as one fifth of the horse's body weight — twenty per cent —
    rounded half-up to 2 decimal places. A new horse is `AVAILABLE`, with
    `hold_release_at` and `hold_reason` both null."

    Design: Corner/entities/horse_create_computes_max_load_and_ignores_input_system_fields
    """
    set_clock("2026-05-01T00:00:00Z")

    horse = validate_success(
        api.create_horse(
            {"name": "Pebble", "body_weight_lb": 987.5, "tack_weight_lb": 28.25}, ADMIN
        ),
        expected_status=201,
    )
    assert_horse(horse)
    assert horse["max_load_lb"] == pytest.approx(197.5, abs=0.001)
    assert horse["status"] == "AVAILABLE"
    assert horse["hold_release_at"] is None
    assert horse["hold_reason"] is None
    assert horse["current_week_committed_minutes"] == 0
    assert horse["current_day_session_count"] == 0
    assert horse["version"] == 1


def test_effective_load_exactly_at_the_ceiling_is_admitted(api):
    """PRD 3.3: "**Effective load** is what the horse actually carries: a rider
    weight, plus the horse's own `tack_weight_lb`, plus 140.0 pounds when the
    rider's `backriding_required` flag is true and 0 pounds otherwise, with the
    total rounded half-up to 2 decimal places."
    PRD 3.3: "Booking compares that figure against `max_load_lb` and permits it
    when it is at most `max_load_lb` — a load exactly equal to the ceiling
    passes, and only a strictly greater load is refused with
    `ERR_HORSE_LOAD_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/effective_load_exactly_equal_to_max_load_is_admitted
    """
    scenario = setup_active_rider(
        rider={"weight_lb": 190},
        assessment={"rider_weight_lb": 190},
    )
    assert scenario["horse"]["max_load_lb"] == pytest.approx(220.0, abs=0.001)

    booked = validate_success(
        api.create_session(
            session_payload(
                scenario["rider_id"], scenario["horse_id"], scenario["instructor_id"]
            ),
            scenario["instructor_headers"],
        ),
        expected_status=201,
    )
    assert booked["effective_load_lb"] == pytest.approx(220.0, abs=0.001)
    assert booked["schedule_status"] == "CREW_PENDING"


def test_one_pound_over_the_ceiling_is_refused(api):
    """PRD 3.3: "Booking compares that figure against `max_load_lb` and permits
    it when it is at most `max_load_lb` — a load exactly equal to the ceiling
    passes, and only a strictly greater load is refused with
    `ERR_HORSE_LOAD_EXCEEDED`."
    PRD 3.3: "The `current_declared` reading uses the rider's `weight_lb`, the
    value the most recent intake update wrote, and this is the reading the
    booking gate uses and the reading the session's own `effective_load_lb` field
    always reports."

    Design: Difficulty/boundary_precision_check/effective_load_exactly_equal_to_max_load_is_admitted
    """
    scenario = setup_active_rider(
        rider={"weight_lb": 190},
        assessment={"rider_weight_lb": 190},
    )
    validate_success(
        api.create_session(
            session_payload(
                scenario["rider_id"], scenario["horse_id"], scenario["instructor_id"]
            ),
            scenario["instructor_headers"],
        ),
        expected_status=201,
    )

    validate_success(api.update_rider(scenario["rider_id"], {"weight_lb": 191}, INTAKE))

    refused = api.create_session(
        session_payload(
            scenario["rider_id"],
            scenario["horse_id"],
            scenario["instructor_id"],
            scheduled_start="2026-05-12T10:00:00Z",
        ),
        scenario["instructor_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_HORSE_LOAD_EXCEEDED.value)

    rows, _ = validate_paginated(
        api.list_sessions(ADMIN, params={"horse_id": scenario["horse_id"]})
    )
    assert all(row["scheduled_start"][:10] != "2026-05-12" for row in rows)


def test_horse_workload_committed_and_delivered_variants_diverge(api):
    """PRD 3.3: "A horse's committed workload counts every session of that horse
    whose `schedule_status` is `CREW_PENDING`, `CONFIRMED` or `COMPLETED`, taking
    each session's booked `duration_minutes`. Its delivered workload counts only
    sessions in `COMPLETED`, taking each session's actually-ridden
    `mounted_minutes`."
    PRD 3.3: "answering with the `horse_id`, the echoed `on_date`, the
    `week_start_date` for that date, the `variant` used, the `day_session_count`,
    the `day_minutes`, the `week_minutes`, and the headroom figures
    `day_remaining_minutes` (150 minus `day_minutes`) and `week_remaining_minutes`
    (240 minus `week_minutes`)."

    Design: Corner/endpoints/horse_workload_delivered_variant_counts_only_completed_mounted_minutes
    """
    scenario = setup_active_rider()
    first = book_session(
        scenario["rider_id"],
        scenario["horse_id"],
        scenario["instructor_id"],
        scheduled_start="2026-05-11T09:00:00Z",
        duration_minutes=60,
    )
    validate_success(api.confirm_session(first["id"], scenario["instructor_headers"]))
    validate_success(
        api.complete_session(
            first["id"], {"mounted_minutes": 45}, scenario["instructor_headers"]
        )
    )
    book_session(
        scenario["rider_id"],
        scenario["horse_id"],
        scenario["instructor_id"],
        scheduled_start="2026-05-11T10:15:00Z",
        duration_minutes=60,
    )

    committed = validate_success(
        api.get_horse_workload(
            scenario["horse_id"],
            ADMIN,
            params={"on_date": "2026-05-11", "variant": "committed"},
        )
    )
    assert committed["day_minutes"] == 120
    assert committed["day_session_count"] == 2
    assert committed["week_start_date"] == "2026-05-11"
    assert committed["week_minutes"] == 120
    assert committed["week_remaining_minutes"] == 120
    assert committed["day_remaining_minutes"] == 30

    delivered = validate_success(
        api.get_horse_workload(
            scenario["horse_id"],
            ADMIN,
            params={"on_date": "2026-05-11", "variant": "delivered"},
        )
    )
    assert delivered["day_minutes"] == 45


def test_horse_daily_minutes_exactly_at_the_cap_is_allowed(api):
    """PRD 3.3: "A horse may carry at most 3 sessions on a calendar date, and at
    most 150 committed minutes on that date; breaching either limb is
    `ERR_HORSE_DAILY_LIMIT_EXCEEDED`."
    PRD 3.3: "Every one of these comparisons permits landing exactly on the
    ceiling and refuses only the value that exceeds it, so a day filled to
    precisely 150 minutes is legal and the next minute is not."

    Design: Corner/calculations/horse_daily_minutes_exactly_at_the_cap_is_allowed_and_one_more_is_not
    """
    scenario = setup_active_rider()
    book_session(
        scenario["rider_id"],
        scenario["horse_id"],
        scenario["instructor_id"],
        scheduled_start="2026-05-11T09:00:00Z",
        duration_minutes=90,
    )

    at_the_cap = validate_success(
        api.create_session(
            session_payload(
                scenario["rider_id"],
                scenario["horse_id"],
                scenario["instructor_id"],
                scheduled_start="2026-05-11T10:45:00Z",
                duration_minutes=60,
            ),
            scenario["instructor_headers"],
        ),
        expected_status=201,
    )
    assert at_the_cap["schedule_status"] == "CREW_PENDING"

    over_the_cap = api.create_session(
        session_payload(
            scenario["rider_id"],
            scenario["horse_id"],
            scenario["instructor_id"],
            scheduled_start="2026-05-11T12:00:00Z",
            duration_minutes=30,
        ),
        scenario["instructor_headers"],
    )
    validate_error(over_the_cap, ApiErrorId.ERR_HORSE_DAILY_LIMIT_EXCEEDED.value)

    workload = validate_success(
        api.get_horse_workload(
            scenario["horse_id"],
            ADMIN,
            params={"on_date": "2026-05-11", "variant": "committed"},
        )
    )
    assert workload["day_minutes"] == 150
    assert workload["day_remaining_minutes"] == 0
    assert workload["day_session_count"] == 2, (
        "Only two sessions exist, so the rejection came from the minutes limb"
    )


def test_touching_horse_intervals_breach_the_rest_buffer(api):
    """PRD 3.3: "A session that starts exactly when another ends does *not*
    overlap."
    PRD 3.3: "the gap between the end of the earlier interval and the start of
    the later one must be at least 15 minutes for every neighbouring live session
    of that horse, and a gap of exactly 15 minutes is allowed. A shorter gap is
    `ERR_HORSE_REST_INTERVAL`."

    Design: Difficulty/resource_temporal_overlap/horse_touching_intervals_clear_overlap_but_breach_rest_buffer
    """
    scenario = setup_active_rider()
    book_session(
        scenario["rider_id"],
        scenario["horse_id"],
        scenario["instructor_id"],
        scheduled_start="2026-05-11T10:00:00Z",
        duration_minutes=60,
    )

    touching = api.create_session(
        session_payload(
            scenario["rider_id"],
            scenario["horse_id"],
            scenario["instructor_id"],
            scheduled_start="2026-05-11T11:00:00Z",
            duration_minutes=30,
        ),
        scenario["instructor_headers"],
    )
    validate_error(touching, ApiErrorId.ERR_HORSE_REST_INTERVAL.value)


def test_a_gap_of_exactly_fifteen_minutes_is_admitted(api):
    """PRD 3.3: "the gap between the end of the earlier interval and the start of
    the later one must be at least 15 minutes for every neighbouring live session
    of that horse, and a gap of exactly 15 minutes is allowed. A shorter gap is
    `ERR_HORSE_REST_INTERVAL`."
    PRD 3.3: "Together these two rules make the horse's occupancy a
    buffer-extended half-open interval, and they are evaluated in that order:
    overlap first, rest interval only if there was none."

    Design: Difficulty/resource_temporal_overlap/horse_touching_intervals_clear_overlap_but_breach_rest_buffer
    """
    scenario = setup_active_rider()
    book_session(
        scenario["rider_id"],
        scenario["horse_id"],
        scenario["instructor_id"],
        scheduled_start="2026-05-11T10:00:00Z",
        duration_minutes=60,
    )
    refused = api.create_session(
        session_payload(
            scenario["rider_id"],
            scenario["horse_id"],
            scenario["instructor_id"],
            scheduled_start="2026-05-11T11:00:00Z",
            duration_minutes=30,
        ),
        scenario["instructor_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_HORSE_REST_INTERVAL.value)

    admitted = validate_success(
        api.create_session(
            session_payload(
                scenario["rider_id"],
                scenario["horse_id"],
                scenario["instructor_id"],
                scheduled_start="2026-05-11T11:15:00Z",
                duration_minutes=30,
            ),
            scenario["instructor_headers"],
        ),
        expected_status=201,
    )
    assert admitted["schedule_status"] == "CREW_PENDING"

    workload = validate_success(
        api.get_horse_workload(
            scenario["horse_id"],
            ADMIN,
            params={"on_date": "2026-05-11", "variant": "committed"},
        )
    )
    assert workload["day_session_count"] == 2
    assert workload["day_minutes"] == 90


def test_horse_hold_blocks_booking_until_released(api):
    """PRD 3.3: "the horse's `status` becomes that hold type, `hold_release_at`
    takes the supplied `release_at` verbatim, and `hold_reason` is recorded as
    the literal string `MANUAL`."
    PRD 3.3: "Any hold moves the horse off `AVAILABLE` and increments its
    `version`, and any of the three holds blocks booking, confirmation and
    completion with `ERR_HORSE_ON_HOLD`."

    Design: Difficulty/cross_entity_state_dependency/session_creation_depends_on_horse_operational_status
    """
    scenario = setup_active_rider()
    held = validate_success(
        api.hold_horse(
            scenario["horse_id"],
            {"hold_type": "FARRIER_HOLD", "release_at": "2026-05-05T00:00:00Z"},
            ADMIN,
        )
    )
    assert held["status"] == "FARRIER_HOLD"
    assert held["hold_reason"] == "MANUAL"

    blocked = api.create_session(
        session_payload(
            scenario["rider_id"], scenario["horse_id"], scenario["instructor_id"]
        ),
        scenario["instructor_headers"],
    )
    validate_error(blocked, ApiErrorId.ERR_HORSE_ON_HOLD.value)

    assert read_rider(scenario["rider_id"])["status"] == "ACTIVE", (
        "The block came only from the horse"
    )


def test_releasing_a_farrier_hold_restores_booking(api):
    """PRD 3.3: "A `ProgramAdmin` releasing a hold moves the horse from
    `VET_HOLD`, `FARRIER_HOLD` or `REST_HOLD` back to `AVAILABLE`, clearing both
    `hold_release_at` and `hold_reason` and incrementing `version`, but only once
    the logical clock has reached `hold_release_at`; an attempt before that
    instant is `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/session_creation_depends_on_horse_operational_status
    """
    scenario = setup_active_rider()
    validate_success(
        api.hold_horse(
            scenario["horse_id"],
            {"hold_type": "FARRIER_HOLD", "release_at": "2026-05-05T00:00:00Z"},
            ADMIN,
        )
    )
    blocked = api.create_session(
        session_payload(
            scenario["rider_id"], scenario["horse_id"], scenario["instructor_id"]
        ),
        scenario["instructor_headers"],
    )
    validate_error(blocked, ApiErrorId.ERR_HORSE_ON_HOLD.value)

    set_clock("2026-05-05T00:00:00Z")
    released = validate_success(api.release_horse_hold(scenario["horse_id"], ADMIN))
    assert released["status"] == "AVAILABLE"
    assert released["hold_release_at"] is None
    assert released["hold_reason"] is None

    booked = validate_success(
        api.create_session(
            session_payload(
                scenario["rider_id"], scenario["horse_id"], scenario["instructor_id"]
            ),
            scenario["instructor_headers"],
        ),
        expected_status=201,
    )
    assert booked["schedule_status"] == "CREW_PENDING"


def test_release_hold_before_hold_release_at_is_refused(api):
    """PRD 3.3: "A `ProgramAdmin` releasing a hold moves the horse from
    `VET_HOLD`, `FARRIER_HOLD` or `REST_HOLD` back to `AVAILABLE`, clearing both
    `hold_release_at` and `hold_reason` and incrementing `version`, but only once
    the logical clock has reached `hold_release_at`; an attempt before that
    instant is `ERR_INVALID_STATE`."

    Design: Corner/state_machines/release_horse_hold_before_hold_release_at_returns_invalid_state
    """
    set_clock("2026-05-01T00:00:00Z")
    horse = validate_success(
        api.create_horse(
            {"name": "Comet", "body_weight_lb": 1100, "tack_weight_lb": 30}, ADMIN
        ),
        expected_status=201,
    )
    validate_success(
        api.hold_horse(
            horse["id"],
            {"hold_type": "FARRIER_HOLD", "release_at": "2026-05-05T00:00:00Z"},
            ADMIN,
        )
    )

    too_early = api.release_horse_hold(horse["id"], ADMIN)
    validate_error(too_early, ApiErrorId.ERR_INVALID_STATE.value)

    set_clock("2026-05-05T00:00:00Z")
    released = validate_success(api.release_horse_hold(horse["id"], ADMIN))
    assert released["status"] == "AVAILABLE", (
        "The boundary is inclusive: standing exactly at hold_release_at is enough"
    )
    after = read_horse(horse["id"])
    assert after["hold_release_at"] is None
    assert after["hold_reason"] is None


def test_weekly_overflow_is_refused_at_240_committed_minutes(api):
    """PRD 3.3: "A horse may carry at most 240 committed minutes in the
    Monday-based week containing the session date; breaching it is
    `ERR_HORSE_WEEKLY_MINUTES_EXCEEDED`."

    Design: Difficulty/compensating_invariant/horse_weekly_committed_minutes_returned_exactly_by_cancellation
    """
    scenario = setup_horse_week_at_240(setup_active_rider())

    workload = validate_success(
        api.get_horse_workload(
            scenario["horse_id"],
            ADMIN,
            params={"on_date": "2026-05-12", "variant": "committed"},
        )
    )
    assert workload["week_minutes"] == 240
    assert workload["week_remaining_minutes"] == 0

    refused = api.create_session(
        session_payload(
            scenario["rider_id"],
            scenario["horse_id"],
            scenario["instructor_id"],
            scheduled_start="2026-05-12T10:45:00Z",
            duration_minutes=30,
        ),
        scenario["instructor_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_HORSE_WEEKLY_MINUTES_EXCEEDED.value)


def test_cancellation_returns_exactly_the_horses_weekly_minutes(api):
    """PRD 2.12: "A horse's `current_week_committed_minutes` always equals the
    sum of `duration_minutes` over that horse's sessions in `CREW_PENDING`,
    `CONFIRMED` or `COMPLETED` whose `scheduled_start` falls in the current week,
    so cancelling a session returns exactly that session's `duration_minutes` of
    daily and weekly capacity — no more and no less, which means a booking
    rejected for weekly overflow succeeds after one cancellation of equal
    duration."
    PRD 3.6: "`WEATHER`, `HORSE_PULLED` and `PROGRAM_CLOSURE` are stored as
    themselves and are never chargeable."

    Design: Difficulty/compensating_invariant/horse_weekly_committed_minutes_returned_exactly_by_cancellation
    """
    scenario = setup_horse_week_at_240(setup_active_rider())
    tuesday_id = scenario["tuesday"]["id"]

    refused = api.create_session(
        session_payload(
            scenario["rider_id"],
            scenario["horse_id"],
            scenario["instructor_id"],
            scheduled_start="2026-05-12T10:45:00Z",
            duration_minutes=30,
        ),
        scenario["instructor_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_HORSE_WEEKLY_MINUTES_EXCEEDED.value)

    cancelled = validate_success(
        api.cancel_session(
            tuesday_id, {"cancellation_reason": "WEATHER"}, scenario["instructor_headers"]
        )
    )
    assert cancelled["schedule_status"] == "CANCELLED"
    assert cancelled["cancellation_reason"] == "WEATHER"

    _, charge_meta = validate_paginated(
        api.list_charges(CLERK, params={"session_id": tuesday_id})
    )
    assert charge_meta["total_count"] == 0, "A weather cancellation is never chargeable"

    retried = validate_success(
        api.create_session(
            session_payload(
                scenario["rider_id"],
                scenario["horse_id"],
                scenario["instructor_id"],
                scheduled_start="2026-05-12T10:45:00Z",
                duration_minutes=30,
            ),
            scenario["instructor_headers"],
        ),
        expected_status=201,
    )
    assert retried["schedule_status"] == "CREW_PENDING"

    workload = validate_success(
        api.get_horse_workload(
            scenario["horse_id"],
            ADMIN,
            params={"on_date": "2026-05-12", "variant": "committed"},
        )
    )
    assert workload["week_minutes"] == 180
    assert workload["week_start_date"] == "2026-05-11"
    assert workload["day_minutes"] == 30
    assert workload["week_remaining_minutes"] == 60
