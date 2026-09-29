"""Two occupation geometries on the same day: buffered stations, bare talent.

A station's window is stretched by its teardown buffer and capped by a
concurrency ceiling; a person's window is stretched by nothing at all.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_STATION_OVERLAP, ERR_TALENT_OVERLAP
from test_helpers.test_users import ADMIN, PRODUCER


# ─── station_buffer_extends_occupation_past_the_scheduled_end ───────────────

def _buffered_bay_occupied_until_half_past_one(api):
    """A 30-minute teardown turns a 09:00-13:00 booking into [09:00, 13:30)."""
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    station = fx.create_station(api, buffer_minutes=30)
    provider = fx.create_provider(api)
    first = fx.create_session(api, station["id"], provider["id"])
    return {"station": station, "provider": provider, "first": first}


def _candidate(api, world, start, end):
    return api.create_shoot_session(
        f.session_payload(
            world["station"]["id"],
            world["provider"]["id"],
            scheduled_start=start,
            scheduled_end=end,
        ),
        PRODUCER,
    )


def test_a_candidate_inside_the_teardown_gap_collides(api):
    """The raw intervals are disjoint; the buffer-extended ones are not.

    PRD: "The system counts how many of those existing occupations the candidate's extended window intersects, and rejects the booking with `ERR_STATION_OVERLAP` when that count reaches or exceeds the concurrency ceiling."

    Design: Difficulty/resource_temporal_overlap/station_buffer_extends_occupation_past_the_scheduled_end
    """
    world = _buffered_bay_occupied_until_half_past_one(api)

    validate_error(
        _candidate(api, world, "2026-08-03T13:15:00Z", "2026-08-03T14:15:00Z"),
        ERR_STATION_OVERLAP,
        409,
    )


def test_a_candidate_starting_at_the_reset_instant_is_admitted(api):
    """Half past one is exactly when the bay frees up, and that is soon enough.

    PRD: "Because the windows are half-open, a session starting at exactly the instant a previous session's buffer runs out does not intersect it."

    Design: Difficulty/resource_temporal_overlap/station_buffer_extends_occupation_past_the_scheduled_end
    """
    world = _buffered_bay_occupied_until_half_past_one(api)
    validate_error(
        _candidate(api, world, "2026-08-03T13:15:00Z", "2026-08-03T14:15:00Z"),
        ERR_STATION_OVERLAP,
        409,
    )

    admitted = validate_success(
        _candidate(api, world, "2026-08-03T13:30:00Z", "2026-08-03T14:30:00Z"), 201
    )

    assert admitted["session_state"] == "BOOKED"
    assert admitted["planned_minutes"] == 60
    assert validate_success(api.get_station(world["station"]["id"], ADMIN))[
        "committed_minutes_today"
    ] == 300


# ─── talent_exclusivity_has_no_buffer_and_permits_exact_adjacency ────────────

def _photographer_confirmed_until_one_oclock(api):
    """Pia Ren is CONFIRMED 09:00-13:00 on MODEL-1; MODEL-2 spans 12:59-17:00."""
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    st1 = fx.create_station(api, station_code="MODEL-1")
    st2 = fx.create_station(api, station_code="MODEL-2")
    provider = fx.create_provider(api)
    photographer = fx.create_photographer(api)
    ses1 = fx.create_session(api, st1["id"], provider["id"])
    bk1 = fx.create_booking(api, ses1["id"], photographer["id"])
    fx.confirm_booking(api, bk1["id"])
    ses2 = fx.create_session(
        api,
        st2["id"],
        provider["id"],
        scheduled_start="2026-08-03T12:59:00Z",
        scheduled_end="2026-08-03T17:00:00Z",
    )
    return {"photographer": photographer, "ses2": ses2}


def _hold(api, world, call_time, wrap_time, expected_version):
    return api.create_talent_booking(
        f.booking_payload(
            world["ses2"]["id"],
            world["photographer"]["id"],
            expected_version,
            call_time=call_time,
            wrap_time=wrap_time,
        ),
        PRODUCER,
    )


def test_a_call_one_minute_before_the_incumbent_wraps_is_refused(api):
    """One minute of genuine overlap is enough to bar the second hold.

    PRD: "The candidate hold is refused with `ERR_TALENT_OVERLAP` when the same person already has a booking whose `booking_state` is `HELD` or `CONFIRMED` that genuinely overlaps it — that is, when the candidate's `call_time` falls strictly before the existing booking's `wrap_time` **and** the existing booking's `call_time` falls strictly before the candidate's `wrap_time`."

    Design: Difficulty/resource_temporal_overlap/talent_exclusivity_has_no_buffer_and_permits_exact_adjacency
    """
    world = _photographer_confirmed_until_one_oclock(api)
    version_before = world["ses2"]["version"]

    validate_error(
        _hold(
            api,
            world,
            "2026-08-03T12:59:00Z",
            "2026-08-03T16:59:00Z",
            version_before,
        ),
        ERR_TALENT_OVERLAP,
        409,
    )

    assert fx.session_version(api, world["ses2"]["id"]) == version_before


def test_a_call_at_exactly_the_wrap_instant_is_permitted(api):
    """Exact adjacency is legal on the talent axis, and the split is clean.

    PRD: "Unlike station occupation, talent occupation carries no buffer at all, and exact adjacency is explicitly permitted: a model wrapping one session at 13:00 may be called to another at exactly 13:00."

    Design: Difficulty/resource_temporal_overlap/talent_exclusivity_has_no_buffer_and_permits_exact_adjacency
    """
    world = _photographer_confirmed_until_one_oclock(api)
    version_before = world["ses2"]["version"]
    validate_error(
        _hold(
            api,
            world,
            "2026-08-03T12:59:00Z",
            "2026-08-03T16:59:00Z",
            version_before,
        ),
        ERR_TALENT_OVERLAP,
        409,
    )

    held = validate_success(
        _hold(
            api,
            world,
            "2026-08-03T13:00:00Z",
            "2026-08-03T17:00:00Z",
            version_before,
        ),
        201,
    )

    assert held["booking_state"] == "HELD"
    assert held["booked_minutes"] == 240
    assert held["regular_minutes"] == 240
    assert held["overtime_minutes"] == 0


def test_the_adjacent_hold_prices_its_regular_leg_and_fills_the_day(api):
    """Four regular hours at 12000 cents an hour, taking the day to 480 minutes.

    PRD: "Third, the two legs are priced separately and each is rounded to a whole cent before they are added: the regular leg is the person's `hourly_rate_cents` multiplied by `regular_minutes` divided by 60, rounded half up; the overtime leg is `hourly_rate_cents` multiplied by one and a half — the studio's overtime premium — then multiplied by `overtime_minutes` divided by 60, and rounded half up."

    Design: Difficulty/resource_temporal_overlap/talent_exclusivity_has_no_buffer_and_permits_exact_adjacency
    """
    world = _photographer_confirmed_until_one_oclock(api)

    held = validate_success(
        _hold(
            api,
            world,
            "2026-08-03T13:00:00Z",
            "2026-08-03T17:00:00Z",
            world["ses2"]["version"],
        ),
        201,
    )

    assert held["charge_cents"] == 48000
    assert validate_success(
        api.get_talent_profile(world["photographer"]["id"], ADMIN)
    )["booked_minutes_today"] == 480


# ─── still_life_station_admits_two_concurrent_occupations_and_refuses_the_third ──

def _still_life_bench_with_two_simultaneous_setups(api):
    """A ceiling of two, already carrying two identical 09:00-13:00 occupations."""
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    station = fx.create_station(
        api,
        station_code="SL-1",
        station_type="STILL_LIFE",
        max_concurrent_sessions=2,
    )
    provider = fx.create_provider(api)
    world = {"station": station, "provider": provider, "sessions": []}
    for _ in range(2):
        world["sessions"].append(
            validate_success(
                _candidate(api, world, "2026-08-03T09:00:00Z", "2026-08-03T13:00:00Z"),
                201,
            )
        )
    return world


def test_the_third_simultaneous_setup_hits_the_concurrency_ceiling(api):
    """Two tabletop setups coexist on the bench; the third has nowhere to stand.

    PRD: "On an exclusive model bay, whose ceiling is one, a single intersection is already fatal; on a still-life bench with a ceiling of four, the candidate is admitted while three existing occupations overlap it and refused when a fourth does."

    Design: Difficulty/resource_temporal_overlap/still_life_station_admits_two_concurrent_occupations_and_refuses_the_third
    """
    world = _still_life_bench_with_two_simultaneous_setups(api)
    assert all(s["session_state"] == "BOOKED" for s in world["sessions"])

    validate_error(
        _candidate(api, world, "2026-08-03T09:00:00Z", "2026-08-03T13:00:00Z"),
        ERR_STATION_OVERLAP,
        409,
    )


def test_a_disjoint_afternoon_setup_is_still_admitted_well_under_capacity(api):
    """The refusal was a concurrency ceiling, not a minute budget.

    PRD: "If the session's `scheduled_start` happens to fall on the current logical clock's UTC date, the station's `committed_minutes_today` rises by the session's `planned_minutes`."

    Design: Difficulty/resource_temporal_overlap/still_life_station_admits_two_concurrent_occupations_and_refuses_the_third
    """
    world = _still_life_bench_with_two_simultaneous_setups(api)
    validate_error(
        _candidate(api, world, "2026-08-03T09:00:00Z", "2026-08-03T13:00:00Z"),
        ERR_STATION_OVERLAP,
        409,
    )

    admitted = validate_success(
        _candidate(api, world, "2026-08-03T13:00:00Z", "2026-08-03T17:00:00Z"), 201
    )

    assert admitted["session_state"] == "BOOKED"
    station = validate_success(api.get_station(world["station"]["id"], ADMIN))
    assert station["committed_minutes_today"] == 720
    assert station["daily_capacity_minutes"] == 1440
