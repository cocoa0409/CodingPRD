"""Two shared resources with two different interval geometries.

The writer's calendar is half-open and unbuffered, so adjacency is legal; the
camera unit's shoot window is closed and buffered on both sides, so adjacency
is not.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import constants as K
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import STUDIO_EXECUTIVE_HEADERS

FIRST_SEAT = ("2026-09-01T00:00:00Z", "2026-09-15T00:00:00Z")
ONE_DAY_OVERLAP = ("2026-09-14T00:00:00Z", "2026-09-28T00:00:00Z")
EXACTLY_ADJACENT = ("2026-09-15T00:00:00Z", "2026-09-29T00:00:00Z")
OVERLAPS_THE_OFFER = ("2026-09-28T00:00:00Z", "2026-09-30T00:00:00Z")
SECOND_WINDOW_START = "2026-08-16T00:00:00Z"

EARLY_SEASON_START = {"production_start_date": "2026-10-01T00:00:00Z"}
FIRST_SHOOT_START = "2026-11-02T00:00:00Z"
ON_THE_BUFFERED_EDGE = "2026-11-11T00:00:00Z"
ONE_DAY_CLEAR = "2026-11-12T00:00:00Z"
BEFORE_THE_FIRST_SHOOT = "2026-10-25T00:00:00Z"


def _seat_payload(world, room_version, dates):
    """An identical exclusive seat offer parameterised only by its interval."""
    return F.build_seat_offer(
        world["w1_id"],
        room_version,
        start_date=dates[0],
        end_date=dates[1],
        episodic_guarantee_count=0,
    )


def _one_confirmed_fortnight(api):
    """W1 holds a confirmed fortnight and a second, still open, window."""
    world = X.build_staffing_room_world(api)
    world["aw2"] = X.seed_window(
        api, world["w1_id"], "NON_EXCLUSIVE", SECOND_WINDOW_START, K.WINDOW_END_DATE
    )
    world["aw2_id"] = world["aw2"]["id"]
    seat = X.seed_seat(
        api,
        world["room_id"],
        world["w1_id"],
        world["sr_headers"],
        expected_room_version=world["room_version"],
        start_date=FIRST_SEAT[0],
        end_date=FIRST_SEAT[1],
        episodic_guarantee_count=0,
    )
    world["s1_id"] = seat["id"]
    X.accept_seat(api, seat["id"], world["w1_id"])
    world["room_version"] = X.current_room_version(api, world["room_id"])
    return world


def _adjacent_offer_outstanding(api):
    """The adjacent seat has been offered but not answered, so it still occupies time."""
    world = _one_confirmed_fortnight(api)
    seat = validate_success(
        api.offer_seat(
            world["room_id"],
            _seat_payload(world, world["room_version"], EXACTLY_ADJACENT),
            world["sr_headers"],
        ),
        expected_status=201,
    )
    world["s2_id"] = seat["id"]
    world["s2"] = seat
    world["room_version"] = X.current_room_version(api, world["room_id"])
    return world


def _season_with_first_shoot(api):
    """One UNIT_A episode shooting 2026-11-02 through 2026-11-09."""
    world = X.build_season_world(api, **EARLY_SEASON_START)
    episode = X.seed_episode(
        api,
        world["season_id"],
        1,
        production_unit="UNIT_A",
        production_start_date=FIRST_SHOOT_START,
        shoot_days=8,
    )
    world["ep1_id"] = episode["id"]
    return world


def _episode_payload(number, unit, start):
    """An eight-day shoot on one unit, parameterised by its start."""
    return F.build_episode(
        number,
        production_unit=unit,
        production_start_date=start,
        shoot_days=8,
    )


def _episodes_of(api, season_id):
    """Every episode ordered onto one season."""
    rows, _ = validate_paginated(
        api.list_episodes(
            STUDIO_EXECUTIVE_HEADERS, {"season_id": season_id, "limit": 100}
        )
    )
    return rows


def test_a_one_day_overlap_collides_but_exact_adjacency_does_not(api):
    """Starting a day before the first seat ends collides; starting on it does not.

    PRD: "Because the intervals are half-open, a new seat starting exactly when an existing seat ends does not overlap it."

    PRD: "A genuine collision is rejected with `ERR_WRITER_WINDOW_CONFLICT`."

    PRD: "Count the whole UTC days in the seat's half-open interval; divide that day count by 7 and take the whole-number quotient as the number of full weeks, with the remainder as the residual days."

    Design: Difficulty/resource_temporal_overlap/writer_seat_intervals_are_half_open_so_adjacency_is_allowed_and_one_day_overlap_is_not
    """
    world = _one_confirmed_fortnight(api)

    validate_error(
        api.offer_seat(
            world["room_id"],
            _seat_payload(world, world["room_version"], ONE_DAY_OVERLAP),
            world["sr_headers"],
        ),
        ApiErrorId.WRITER_WINDOW_CONFLICT,
    )

    adjacent = validate_success(
        api.offer_seat(
            world["room_id"],
            _seat_payload(world, world["room_version"], EXACTLY_ADJACENT),
            world["sr_headers"],
        ),
        expected_status=201,
    )
    A.assert_field_values(adjacent, status="OFFERED")
    A.assert_instant(adjacent["start_date"], EXACTLY_ADJACENT[0], "start_date")
    A.assert_instant(adjacent["end_date"], EXACTLY_ADJACENT[1], "end_date")
    A.assert_cents(
        adjacent["weekly_compensation_cents"], 600000, "weekly_compensation_cents"
    )
    A.assert_cents(
        adjacent["prorated_commitment_cents"], 1200000, "prorated_commitment_cents"
    )


def test_a_merely_offered_seat_still_occupies_the_writers_calendar(api):
    """The occupancy set is OFFERED and CONFIRMED, so the unanswered seat collides.

    PRD: "**Interval exclusivity** compares the new seat's half-open interval against every other seat of the same writer whose status is `OFFERED` or `CONFIRMED`."

    PRD: "The candidate set is every availability window of the seat's writer whose status is `OPEN` and whose interval contains the seat's half-open interval; candidates are ranked by the window's `start_date` ascending, and ties are broken by the window's `created_at` ascending; the first candidate wins."

    Design: Difficulty/resource_temporal_overlap/writer_seat_intervals_are_half_open_so_adjacency_is_allowed_and_one_day_overlap_is_not
    """
    world = _adjacent_offer_outstanding(api)

    validate_error(
        api.offer_seat(
            world["room_id"],
            _seat_payload(world, world["room_version"], OVERLAPS_THE_OFFER),
            world["sr_headers"],
        ),
        ApiErrorId.WRITER_WINDOW_CONFLICT,
    )

    A.assert_field_values(X.read_seat(api, world["s1_id"]), status="CONFIRMED")
    A.assert_field_values(X.read_seat(api, world["s2_id"]), status="OFFERED")
    A.assert_field_values(
        X.read_window(api, world["aw1_id"]),
        status="CONSUMED",
        consumed_by_seat_id=world["s1_id"],
    )
    A.assert_field_values(
        X.read_window(api, world["aw2_id"]), status="OPEN", consumed_by_seat_id=None
    )

    room = X.read_room(api, world["room_id"])
    A.assert_field_values(
        room, filled_seat_count=2, confirmed_seat_count=1, open_seat_count=1
    )
    A.assert_room_burn(
        room, 600000, K.FACILITY_TIER_1, K.ROOM_BURN_EMPTY_IN_PERSON, K.ROOM_BURN_ONE_SEAT_600000
    )
    A.assert_seat_capacity_conserved(room)


def test_the_turnaround_buffer_is_inclusive_on_the_edge_and_scoped_to_one_unit(api):
    """Eleven November still conflicts, twelve November does not, and UNIT_B never does.

    PRD: "Concretely, a new episode is rejected when its start falls at or before the existing episode's end plus the buffer *and* the existing episode's start falls at or before the new episode's end plus the buffer; that rejection carries `ERR_PRODUCTION_UNIT_CONFLICT`."

    PRD: "With the default buffer of two days, two eight-day shoots on the same unit must be separated by more than two clear days on the calendar, while the same two shoots on `UNIT_A` and `UNIT_B` may be scheduled on top of each other without complaint."

    Design: Difficulty/resource_temporal_overlap/production_unit_shoot_windows_need_a_symmetric_two_day_turnaround_buffer
    """
    world = _season_with_first_shoot(api)

    validate_error(
        api.create_episode(
            world["season_id"],
            _episode_payload(2, "UNIT_A", ON_THE_BUFFERED_EDGE),
            STUDIO_EXECUTIVE_HEADERS,
        ),
        ApiErrorId.PRODUCTION_UNIT_CONFLICT,
    )

    cleared = validate_success(
        api.create_episode(
            world["season_id"],
            _episode_payload(2, "UNIT_A", ONE_DAY_CLEAR),
            STUDIO_EXECUTIVE_HEADERS,
        ),
        expected_status=201,
    )
    A.assert_field_values(cleared, episode_number=2, production_unit="UNIT_A")
    A.assert_instant(
        cleared["production_start_date"], ONE_DAY_CLEAR, "production_start_date"
    )

    other_unit = validate_success(
        api.create_episode(
            world["season_id"],
            _episode_payload(3, "UNIT_B", FIRST_SHOOT_START),
            STUDIO_EXECUTIVE_HEADERS,
        ),
        expected_status=201,
    )
    A.assert_field_values(other_unit, production_unit="UNIT_B")
    A.assert_instant(
        other_unit["production_start_date"], FIRST_SHOOT_START, "production_start_date"
    )

    assert len(_episodes_of(api, world["season_id"])) == 3, (
        "Exactly the three accepted episodes may exist"
    )


def test_the_buffer_reaches_backwards_and_a_duplicate_number_is_refused(api):
    """A shoot placed before the existing one collides on its own buffered end.

    PRD: "For any two episodes of the same season sharing the same production unit, those windows are each expanded by the agreement's `turnaround_buffer_days` on both sides, and the two expanded windows must not intersect."

    PRD: "Each carries an `episode_number` — a 1-based integer that may not exceed the season's `episode_order` and is unique within the season, a second use being rejected with `ERR_DUPLICATE_EPISODE_NUMBER`"

    Design: Difficulty/resource_temporal_overlap/production_unit_shoot_windows_need_a_symmetric_two_day_turnaround_buffer
    """
    world = _season_with_first_shoot(api)
    validate_success(
        api.create_episode(
            world["season_id"],
            _episode_payload(2, "UNIT_A", ONE_DAY_CLEAR),
            STUDIO_EXECUTIVE_HEADERS,
        ),
        expected_status=201,
    )

    validate_error(
        api.create_episode(
            world["season_id"],
            _episode_payload(4, "UNIT_A", BEFORE_THE_FIRST_SHOOT),
            STUDIO_EXECUTIVE_HEADERS,
        ),
        ApiErrorId.PRODUCTION_UNIT_CONFLICT,
    )

    # Episode number 2 is already in use. The reuse is placed on UNIT_B so that
    # the turnaround rule — listed ahead of uniqueness inside precedence step 18
    # — has nothing to say and uniqueness is the sole violation.
    validate_error(
        api.create_episode(
            world["season_id"],
            _episode_payload(2, "UNIT_B", ONE_DAY_CLEAR),
            STUDIO_EXECUTIVE_HEADERS,
        ),
        ApiErrorId.DUPLICATE_EPISODE_NUMBER,
    )

    numbers = sorted(e["episode_number"] for e in _episodes_of(api, world["season_id"]))
    assert numbers == [1, 2], f"Neither refused call may create an episode: {numbers}"
