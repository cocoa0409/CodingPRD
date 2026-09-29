"""Boundary precision on three different metrics at three different endpoints:
whole minutes of dock turnaround buffer, cubic feet of trailer cube at two
decimal places, and the logical-clock instant against a dispatch cut time.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_DISPATCH_CUT_PASSED,
    ERR_DOOR_WINDOW_CONFLICT,
    ERR_TRAILER_CUBE_EXCEEDED,
)
from test_helpers.assertions import expected_cube_after_scan, expected_cube_utilization_pct
from test_helpers.constants import DEFAULT_TURNAROUND_BUFFER_MIN
from test_helpers.fixtures import shift_instant
from test_helpers.test_users import (
    INBOUND_COORDINATOR_HEADERS,
    OPS_MANAGER_HEADERS,
    SORT_SUPERVISOR_HEADERS,
)

FIRST_WINDOW_START = "2026-08-01T06:00:00Z"
FIRST_WINDOW_END = "2026-08-01T07:00:00Z"

TRAILER_CUBE_EXACT_FIT_CUFT = 402.34
SMALL_PACKAGES_FOR_EXACT_FIT = 1201
INDUCTED_MANIFEST = 3000

DISPATCH_CUT_TIME = "2026-08-01T13:00:00Z"


def _door_with_one_booked_window(world):
    """A center with one inbound door left on its default turnaround buffer, and
    one `SCHEDULED` appointment occupying 06:00 to 07:00 on that door."""
    center = world.create_center(automation_utilization_pct=70.00, flex_pool_total=20)
    door = world.create_door(center["id"], door_number=1, kind="INBOUND")
    appointment = world.schedule_appointment(
        center["id"],
        door["id"],
        window_start=FIRST_WINDOW_START,
        window_end=FIRST_WINDOW_END,
        manifest_package_count=1000,
    )
    return center, door, appointment


def _book(api, center_id, door_id, window_start, window_end):
    return api.create_trailer_appointment(
        f.trailer_appointment_payload(
            center_id,
            door_id,
            window_start=window_start,
            window_end=window_end,
            priority_class="STANDARD",
            manifest_package_count=1000,
        ),
        INBOUND_COORDINATOR_HEADERS,
    )


def _appointments_on_door(api, door_id):
    rows, meta = validate_paginated(
        api.list_trailer_appointments(
            INBOUND_COORDINATOR_HEADERS, door_id=door_id, limit=100
        )
    )
    return rows, meta


def _load_filled_to_the_brim(world, facility):
    """A load whose trailer cube is exactly the cube of 1,201 small packages,
    staged behind a manifest large enough to fund the scan."""
    center_id = facility["center"]["id"]
    world.induct_packages(center_id, facility["inbound_door"]["id"], INDUCTED_MANIFEST)
    return world.stage_load(
        center_id,
        facility["outbound_door"]["id"],
        facility["lane"]["id"],
        trailer_cube_cuft=TRAILER_CUBE_EXACT_FIT_CUFT,
    )


def _sealed_load_awaiting_its_cut_time(world, facility):
    """A `LOADED` and `SEALED` trailer whose cut time is 13:00 on the clock's
    startup day: everything dispatch needs except a clock position."""
    return world.create_sealed_load(
        facility["center"]["id"],
        facility["inbound_door"]["id"],
        facility["outbound_door"]["id"],
        facility["lane"]["id"],
        small_count=100,
        dispatch_cut_time=DISPATCH_CUT_TIME,
    )


def test_door_booking_with_a_gap_of_exactly_the_turnaround_buffer_is_accepted(api, world):
    """PRD §3.3: "The practical consequences are worth stating plainly: two appointments that touch exactly (the new window starting at the instant the existing one ends) *do* conflict, because zero clearance is less than any positive buffer; and a gap of exactly the buffer's length is *accepted*, because the strict comparison just fails to trigger."

    Design: Difficulty/boundary_precision_check/door_turnaround_buffer_gap_exactly_15_minutes
    """
    center, door, first = _door_with_one_booked_window(world)
    assert world.door(door["id"])["turnaround_buffer_min"] == DEFAULT_TURNAROUND_BUFFER_MIN
    assert first["status"] == "SCHEDULED"

    exactly_clear = shift_instant(FIRST_WINDOW_END, minutes=DEFAULT_TURNAROUND_BUFFER_MIN)
    created = validate_success(
        _book(
            api,
            center["id"],
            door["id"],
            exactly_clear,
            shift_instant(exactly_clear, hours=1),
        ),
        201,
    )
    assert created["status"] == "SCHEDULED"
    assert created["door_id"] == door["id"]
    assert created["window_start"].startswith("2026-08-01T07:15:00")

    rows, meta = _appointments_on_door(api, door["id"])
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {first["id"], created["id"]}


def test_door_booking_inside_the_turnaround_buffer_is_rejected(api, world):
    """PRD §3.3: "The door's own `turnaround_buffer_min` is inflated onto **both** sides of the comparison: the booking conflicts with an existing appointment when the new window's start is before the existing window's end advanced by the buffer, and simultaneously the existing window's start is before the new window's end advanced by the buffer."

    Design: Difficulty/boundary_precision_check/door_turnaround_buffer_gap_exactly_15_minutes
    """
    center, door, first = _door_with_one_booked_window(world)
    assert world.door(door["id"])["turnaround_buffer_min"] == DEFAULT_TURNAROUND_BUFFER_MIN

    one_minute_short = shift_instant(
        FIRST_WINDOW_END, minutes=DEFAULT_TURNAROUND_BUFFER_MIN - 1
    )
    validate_error(
        _book(
            api,
            center["id"],
            door["id"],
            one_minute_short,
            shift_instant(one_minute_short, hours=1),
        ),
        ERR_DOOR_WINDOW_CONFLICT,
    )

    validate_error(
        _book(
            api,
            center["id"],
            door["id"],
            FIRST_WINDOW_END,
            shift_instant(FIRST_WINDOW_END, hours=1),
        ),
        ERR_DOOR_WINDOW_CONFLICT,
    )

    rows, meta = _appointments_on_door(api, door["id"])
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]


def test_scan_filling_the_trailer_exactly_to_its_cube_is_accepted(api, world, facility):
    """PRD §2.9: "The trailer cube comparison is not strict: filling a trailer exactly to its `trailer_cube_cuft` is accepted and only a strictly greater result is refused."

    Design: Difficulty/boundary_precision_check/cube_exact_fit_accepted_then_one_more_package_rejected
    """
    center_id = facility["center"]["id"]
    load = _load_filled_to_the_brim(world, facility)
    assert float(load["trailer_cube_cuft"]) == TRAILER_CUBE_EXACT_FIT_CUFT
    assert float(load["cube_used_cuft"]) == 0

    scanned = validate_success(
        api.scan_packages(
            load["id"],
            f.scan_packages_payload(small_count=SMALL_PACKAGES_FOR_EXACT_FIT),
            SORT_SUPERVISOR_HEADERS,
        )
    )
    expected_cube = expected_cube_after_scan(0, small=SMALL_PACKAGES_FOR_EXACT_FIT)
    assert expected_cube == TRAILER_CUBE_EXACT_FIT_CUFT
    assert float(scanned["cube_used_cuft"]) == expected_cube
    assert float(scanned["cube_utilization_pct"]) == expected_cube_utilization_pct(
        TRAILER_CUBE_EXACT_FIT_CUFT, TRAILER_CUBE_EXACT_FIT_CUFT
    )
    assert float(scanned["cube_utilization_pct"]) == 100.00
    assert scanned["package_count"] == SMALL_PACKAGES_FOR_EXACT_FIT
    assert scanned["load_status"] == "LOADING"

    center_after = world.center(center_id)
    assert center_after["wip_package_count"] == (
        INDUCTED_MANIFEST - SMALL_PACKAGES_FOR_EXACT_FIT
    )
    assert (
        world.lane(facility["lane"]["id"])["sorted_package_count"]
        == SMALL_PACKAGES_FOR_EXACT_FIT
    )
    world.assert_ledgers(center_id)


def test_one_package_past_an_exactly_full_trailer_is_rejected(api, world, facility):
    """PRD §3.8: "The capacity gate is checked against the post-scan figure and is deliberately non-strict: a batch that fills the trailer to *exactly* its `trailer_cube_cuft` is accepted, and only a result strictly greater than the trailer's cube is refused, with `ERR_TRAILER_CUBE_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/cube_exact_fit_accepted_then_one_more_package_rejected
    """
    center_id = facility["center"]["id"]
    load = _load_filled_to_the_brim(world, facility)
    filled = world.scan(load["id"], small_count=SMALL_PACKAGES_FOR_EXACT_FIT)
    assert float(filled["cube_used_cuft"]) == TRAILER_CUBE_EXACT_FIT_CUFT

    # One more small package rounds the stored total strictly past the trailer.
    assert (
        expected_cube_after_scan(TRAILER_CUBE_EXACT_FIT_CUFT, small=1)
        > TRAILER_CUBE_EXACT_FIT_CUFT
    )
    validate_error(
        api.scan_packages(
            load["id"], f.scan_packages_payload(small_count=1), SORT_SUPERVISOR_HEADERS
        ),
        ERR_TRAILER_CUBE_EXCEEDED,
    )

    load_after = world.load(load["id"])
    assert float(load_after["cube_used_cuft"]) == TRAILER_CUBE_EXACT_FIT_CUFT
    assert load_after["package_count"] == SMALL_PACKAGES_FOR_EXACT_FIT
    assert float(load_after["cube_utilization_pct"]) == 100.00
    assert load_after["load_status"] == "LOADING"

    center_after = world.center(center_id)
    assert center_after["wip_package_count"] == (
        INDUCTED_MANIFEST - SMALL_PACKAGES_FOR_EXACT_FIT
    )
    assert (
        world.lane(facility["lane"]["id"])["sorted_package_count"]
        == SMALL_PACKAGES_FOR_EXACT_FIT
    )
    world.assert_ledgers(center_id)


def test_dispatch_at_the_cut_time_instant_is_rejected(api, world, facility):
    """PRD §2.9: "The dispatch cut time comparison is strict: a logical clock exactly equal to `dispatch_cut_time` is already too late."

    Design: Difficulty/boundary_precision_check/dispatch_cut_time_instant_is_strictly_before
    """
    load = _sealed_load_awaiting_its_cut_time(world, facility)
    assert load["load_status"] == "LOADED"
    assert load["seal_status"] == "SEALED"
    assert load["dispatched_at"] is None

    world.set_clock(DISPATCH_CUT_TIME)
    validate_error(
        api.dispatch_load(load["id"], OPS_MANAGER_HEADERS), ERR_DISPATCH_CUT_PASSED
    )

    load_after = world.load(load["id"])
    assert load_after["load_status"] == "LOADED"
    assert load_after["dispatched_at"] is None
    assert load_after["seal_status"] == "SEALED"


def test_dispatch_one_second_before_the_cut_time_succeeds(api, world, facility):
    """PRD §3.8: "The load must be `LOADED`, so a trailer still accepting scans cannot leave; `seal_status` must be `SEALED`, and a trailer that is `UNSEALED` or `BROKEN` is refused with `ERR_LOAD_NOT_SEALED`; the logical clock must be strictly before `dispatch_cut_time`, so a clock exactly equal to the cut time is already too late and the attempt is refused with `ERR_DISPATCH_CUT_PASSED`; and the center must not be `FROZEN`, otherwise `ERR_CENTER_FROZEN`."

    Design: Difficulty/boundary_precision_check/dispatch_cut_time_instant_is_strictly_before
    """
    load = _sealed_load_awaiting_its_cut_time(world, facility)
    seal_code = load["seal_code"]

    in_time = shift_instant(DISPATCH_CUT_TIME, seconds=-1)
    world.set_clock(in_time)
    dispatched = validate_success(api.dispatch_load(load["id"], OPS_MANAGER_HEADERS))

    assert dispatched["load_status"] == "DISPATCHED"
    assert dispatched["dispatched_at"].startswith("2026-08-01T12:59:59")
    assert dispatched["seal_status"] == "SEALED"
    assert dispatched["seal_code"] == seal_code
