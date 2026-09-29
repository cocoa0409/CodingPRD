"""Two resources booked over time, each with its own interval convention.

Weekday windows on a grid carry a two-minute station-identification buffer on
each side, so a start that looks clear by one minute is not. Phone-bank rosters
run two conventions at once over the same pair of shifts: closed intervals for the
volunteer's own calendar and half-open intervals for the station's phone lines.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import (
    DEVELOPMENT_HEADERS,
    DIRECTOR_HEADERS,
    api_client,
    assertions,
    factories,
    fixtures,
)

CLOCK = "2026-08-01T00:00:00Z"

SHIFT_DAY_10 = "2026-08-03T10:00:00Z"
SHIFT_DAY_11 = "2026-08-03T11:00:00Z"
SHIFT_DAY_12 = "2026-08-03T12:00:00Z"
SHIFT_DAY_13 = "2026-08-03T13:00:00Z"
SHIFT_DAY_14 = "2026-08-03T14:00:00Z"


def _grid_holding_one_midday_hour():
    """A mutable grid with a single tentative Monday 09:00 hour, so the buffer
    around minute 600 is the only thing standing in the way."""
    base = fixtures.station()
    approved = fixtures.create_approved_program(
        base["host_id"],
        base["members"],
        title="Delta Sessions",
        format_code="MUSIC",
        requested_daypart="MIDDAY",
        requested_duration_minutes=60,
    )
    grid = fixtures.create_grid()
    incumbent = fixtures.add_slot(
        grid["id"],
        approved["program_id"],
        day_of_week=1,
        start_minute=540,
        duration_minutes=60,
    )
    return {
        "grid_id": grid["id"],
        "program_id": approved["program_id"],
        "incumbent_slot_id": incumbent["id"],
    }


def _place(setup, day_of_week, start_minute):
    return api_client.create_slot_assignment(
        setup["grid_id"],
        factories.create_slot_assignment_payload(
            setup["program_id"],
            fixtures.grid_version(setup["grid_id"]),
            day_of_week=day_of_week,
            start_minute=start_minute,
            duration_minutes=60,
        ),
        DIRECTOR_HEADERS,
    )


def _drive_on_a_single_phone_line():
    """One active drive with exactly one phone line and a first shift already on
    the books from 10:00 to 12:00."""
    base = fixtures.development_station(clock=CLOCK)
    gus, hana, iris = base["volunteers"]
    drive = fixtures.create_active_drive(
        name="Fall Drive",
        goal_cents=5_000_000,
        start_at="2026-08-01T00:00:00Z",
        end_at="2026-08-14T23:59:00Z",
        phone_line_count=1,
    )
    first = fixtures.create_shift(drive["id"], gus["id"], SHIFT_DAY_10, SHIFT_DAY_12)
    assert first["status"] == "SCHEDULED"
    return {
        "drive_id": drive["id"],
        "gus_id": gus["id"],
        "hana_id": hana["id"],
        "iris_id": iris["id"],
        "first_shift_id": first["id"],
    }


def _roster(setup, volunteer_id, start_at, end_at):
    return api_client.create_phone_bank_shift(
        {
            "drive_id": setup["drive_id"],
            "volunteer_id": volunteer_id,
            "start_at": start_at,
            "end_at": end_at,
        },
        DEVELOPMENT_HEADERS,
    )


class TestSlotWindowBuffer:
    def test_a_start_one_minute_short_of_the_buffer_collides(self):
        """Minute 601 is inside the two-minute buffer and is refused.

        "Two occupations on the same grid and the same `day_of_week`, both with
        `status` `TENTATIVE` or `CONFIRMED`, collide when the new window's start is
        earlier than the existing window's end plus two minutes *and* the existing
        window's start is earlier than the new window's end plus two minutes. A
        collision is normally refused with `ERR_SLOT_CONFLICT`." The incumbent hour
        ends at minute 600, so 601 is earlier than 602 and the windows collide.

        Design: Difficulty/resource_temporal_overlap/slot_windows_are_half_open_with_a_two_minute_station_id_buffer
        """
        setup = _grid_holding_one_midday_hour()
        version_before = fixtures.grid_version(setup["grid_id"])

        validate_error(_place(setup, 1, 601), "ERR_SLOT_CONFLICT", 409)

        grid = fixtures.read_grid(setup["grid_id"])
        assert grid["version"] == version_before
        assert grid["total_assigned_minutes"] == 60
        assert fixtures.read_slot(setup["incumbent_slot_id"])["status"] == "TENTATIVE"

    def test_a_start_exactly_at_the_buffer_edge_lands_and_other_weekdays_are_free(self):
        """Minute 602 clears the buffer, and minute 601 is free on another day.

        The collision test compares "the new window's start" against "the existing
        window's end plus two minutes", so minute 602 is not earlier than 602 and
        the windows do not collide. The rule only compares occupations on "the same
        grid and the same `day_of_week`", so the very minute refused on Monday is
        available on Tuesday, and each placement recomputes the grid, whose figures
        are "recomputed on every occupation created, confirmed, released, preempted
        or reinstated on it".

        Design: Difficulty/resource_temporal_overlap/slot_windows_are_half_open_with_a_two_minute_station_id_buffer
        """
        setup = _grid_holding_one_midday_hour()
        validate_error(_place(setup, 1, 601), "ERR_SLOT_CONFLICT", 409)

        neighbour = validate_success(_place(setup, 1, 602), 201)
        assert neighbour["status"] == "TENTATIVE"
        assert neighbour["start_minute"] == 602
        assert neighbour["duration_minutes"] == 60
        assertions.assert_slot_assignment(neighbour)
        assert fixtures.read_grid(setup["grid_id"])["total_assigned_minutes"] == 120

        tuesday = validate_success(_place(setup, 2, 601), 201)
        assert tuesday["day_of_week"] == 2
        assert tuesday["start_minute"] == 601

        _, monday_meta = validate_paginated(
            api_client.list_slot_assignments(
                DIRECTOR_HEADERS, params={"grid_id": setup["grid_id"], "day_of_week": 1}
            )
        )
        assert monday_meta["total_count"] == 2

        _, tuesday_meta = validate_paginated(
            api_client.list_slot_assignments(
                DIRECTOR_HEADERS, params={"grid_id": setup["grid_id"], "day_of_week": 2}
            )
        )
        assert tuesday_meta["total_count"] == 1

        grid = fixtures.read_grid(setup["grid_id"])
        assert grid["total_assigned_minutes"] == 180
        assertions.assert_two_decimals_equal(
            grid["public_affairs_minutes_pct"], 0.00, "public_affairs_minutes_pct"
        )


class TestPhoneBankIntervalConventions:
    def test_back_to_back_shifts_conflict_for_the_same_volunteer(self):
        """A volunteer's own calendar is closed at both ends.

        "a volunteer's own shifts are compared as **closed** intervals: a new shift
        conflicts with any existing shift of the same volunteer whose `status` is
        `SCHEDULED` or `COMPLETED` when the two closed intervals from `start_at`
        through `end_at` inclusive intersect at all. Back-to-back shifts that merely
        touch at an endpoint — one ending at 14:00 and the next starting at 14:00 —
        **do** conflict, and the roster is refused with `ERR_SHIFT_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/phone_bank_shifts_close_per_volunteer_but_stay_half_open_per_line
        """
        setup = _drive_on_a_single_phone_line()

        validate_error(
            _roster(setup, setup["gus_id"], SHIFT_DAY_12, SHIFT_DAY_14),
            "ERR_SHIFT_CONFLICT",
            409,
        )

        _, gus_meta = validate_paginated(
            api_client.list_phone_bank_shifts(
                DEVELOPMENT_HEADERS,
                params={"drive_id": setup["drive_id"], "volunteer_id": setup["gus_id"]},
            )
        )
        assert gus_meta["total_count"] == 1

    def test_the_same_touching_window_is_free_for_another_volunteer_but_the_line_is_not(self):
        """The line is handed over at 12:00; it cannot be shared at 11:00.

        "line capacity is measured on **half-open** windows: a shift consumes a
        line for the interval from its `start_at` up to but not including its
        `end_at` ... Two shifts that touch at an endpoint therefore do **not**
        consume the same line at the same time. When the number of shifts
        simultaneously holding a line would exceed the drive's `phone_line_count`,
        the roster is refused with `ERR_PHONE_LINE_CAPACITY`." A third volunteer
        working 11:00 to 13:00 overlaps both booked windows on a single line, and
        because she holds no shift of her own the closed-interval check has nothing
        to say.

        Design: Difficulty/resource_temporal_overlap/phone_bank_shifts_close_per_volunteer_but_stay_half_open_per_line
        """
        setup = _drive_on_a_single_phone_line()
        validate_error(
            _roster(setup, setup["gus_id"], SHIFT_DAY_12, SHIFT_DAY_14),
            "ERR_SHIFT_CONFLICT",
            409,
        )

        handover = validate_success(
            _roster(setup, setup["hana_id"], SHIFT_DAY_12, SHIFT_DAY_14), 201
        )
        assert handover["status"] == "SCHEDULED"
        assertions.assert_phone_bank_shift(handover)

        validate_error(
            _roster(setup, setup["iris_id"], SHIFT_DAY_11, SHIFT_DAY_13),
            "ERR_PHONE_LINE_CAPACITY",
            409,
        )

        _, drive_meta = validate_paginated(
            api_client.list_phone_bank_shifts(
                DEVELOPMENT_HEADERS, params={"drive_id": setup["drive_id"]}
            )
        )
        assert drive_meta["total_count"] == 2

        _, iris_meta = validate_paginated(
            api_client.list_phone_bank_shifts(
                DEVELOPMENT_HEADERS, params={"volunteer_id": setup["iris_id"]}
            )
        )
        assert iris_meta["total_count"] == 0

        drive = fixtures.read_drive(setup["drive_id"])
        assert drive["phone_line_count"] == 1
        assert drive["status"] == "ACTIVE"
