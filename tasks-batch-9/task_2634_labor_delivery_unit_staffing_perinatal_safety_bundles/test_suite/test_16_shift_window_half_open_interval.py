"""One roster endpoint, two independent interval facts, both pinned on the edge.

A night nurse already holds a shift covering 06:00 to 16:00. Five further
windows are offered: one that shares exactly one minute, one that starts at the
precise instant the first ends, one that spans exactly the maximum permitted
number of minutes, one that spans one minute more, and one that shares a minute
with the first window but belongs to a different nurse. Each refusal must name
the fact it actually broke, and neither fact may be used to explain the other's
outcome.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_instant_equals,
    assert_shift_assignment,
    bootstrap_unit,
    create_shift,
    get_success_data,
    minutes_between,
)

CLOCK_START = "2026-08-20T05:00:00Z"

BASE_START = "2026-08-20T06:00:00Z"
BASE_END = "2026-08-20T16:00:00Z"

OVERLAP_START = "2026-08-20T15:59:00Z"
NIGHT_END = "2026-08-20T22:00:00Z"

TOUCHING_START = "2026-08-20T16:00:00Z"

CAP_EXACT_START = "2026-08-21T00:00:00Z"
CAP_EXACT_END = "2026-08-21T12:00:00Z"

CAP_OVER_START = "2026-08-22T00:00:00Z"
CAP_OVER_END = "2026-08-22T12:01:00Z"

MAX_SHIFT_MINUTES = 720

ROSTER_STAFF = {
    "charge": {
        "full_name": "Petronella Vandermeulen RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-12-31T00:00:00Z",
        "or_circulating_qualified": False,
    },
    "night": {
        "full_name": "Casimir Oyelaran RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-12-31T00:00:00Z",
        "or_circulating_qualified": False,
    },
    "other": {
        "full_name": "Aurelie Nkemdirim RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-12-31T00:00:00Z",
        "or_circulating_qualified": False,
    },
}


def _offer(world, staff_key, shift_start_utc, shift_end_utc):
    """Offer a BEDSIDE window for one nurse without asserting the outcome."""
    return api_client.create_shift(
        {
            "unit_id": world.unit_id,
            "staff_id": world.staff_id(staff_key),
            "role_slot": "BEDSIDE",
            "shift_start_utc": shift_start_utc,
            "shift_end_utc": shift_end_utc,
        },
        world.charge_headers,
    )


@pytest.fixture
def five_windows_against_one_rostered_shift():
    """A single SCHEDULED 06:00-16:00 window, then five probes around its edges."""
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=2,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR")],
        staff_specs=ROSTER_STAFF,
        unit_overrides={"unit_name": "Wrenfield Community Birth Unit"},
    )
    base = create_shift(
        world,
        staff_key="night",
        role_slot="BEDSIDE",
        shift_start_utc=BASE_START,
        shift_end_utc=BASE_END,
    )
    sharing_one_minute = _offer(world, "night", OVERLAP_START, NIGHT_END)
    touching_endpoint = _offer(world, "night", TOUCHING_START, NIGHT_END)
    exactly_at_the_cap = _offer(world, "night", CAP_EXACT_START, CAP_EXACT_END)
    one_minute_over_the_cap = _offer(world, "night", CAP_OVER_START, CAP_OVER_END)
    same_minute_other_nurse = _offer(world, "other", OVERLAP_START, NIGHT_END)
    return {
        "world": world,
        "base": base,
        "sharing_one_minute": sharing_one_minute,
        "touching_endpoint": touching_endpoint,
        "exactly_at_the_cap": exactly_at_the_cap,
        "one_minute_over_the_cap": one_minute_over_the_cap,
        "same_minute_other_nurse": same_minute_other_nurse,
    }


def test_a_single_shared_minute_is_an_overlap(
    five_windows_against_one_rostered_shift,
):
    """"Two shifts for the same staff member collide when their half-open
    intervals share any instant" — one shared minute is enough, and at a span of
    361 minutes the length cap cannot be the reason.

    Design: Difficulty/resource_temporal_overlap/shift_window_admits_the_touching_sixteen_hundred_start_and_the_exact_720_minute_span_but_refuses_15_59_and_721
    """
    setup = five_windows_against_one_rostered_shift
    response = setup["sharing_one_minute"]
    validate_error(response, ApiErrorId.ERR_SHIFT_WINDOW_OVERLAP.value, 409)
    assert (
        response.json()["data"]["error_id"]
        != ApiErrorId.ERR_SHIFT_WINDOW_TOO_LONG.value
    )
    assert minutes_between(OVERLAP_START, NIGHT_END) < MAX_SHIFT_MINUTES


def test_a_window_starting_where_the_last_one_ends_is_admitted(
    five_windows_against_one_rostered_shift,
):
    """"Two shifts for the same staff member collide when their half-open intervals share
    any instant; a shift that ends at precisely the instant the next one starts does
    not collide, and both may exist." The admitted window differs from the refused
    one by a single minute of start time.

    Design: Difficulty/resource_temporal_overlap/shift_window_admits_the_touching_sixteen_hundred_start_and_the_exact_720_minute_span_but_refuses_15_59_and_721
    """
    setup = five_windows_against_one_rostered_shift
    shift = get_success_data(setup["touching_endpoint"])
    assert_shift_assignment(shift)
    assert shift["staff_id"] == setup["world"].staff_id("night")
    assert_instant_equals(shift["shift_start_utc"], TOUCHING_START, "shift_start_utc")
    assert_instant_equals(shift["shift_end_utc"], NIGHT_END, "shift_end_utc")
    assert_instant_equals(setup["base"]["shift_end_utc"], TOUCHING_START, "base end")


def test_the_touching_window_opens_on_its_documented_state(
    five_windows_against_one_rostered_shift,
):
    """"The entry opens in `SCHEDULED` with `assigned_acuity_load_units` at 0 and
    `capacity_units_effective` null, and it may be listed filtered by `unit_id`,
    `staff_id`, `role_slot`, `status` and `relieved_by_shift_id`, ordered by
    `shift_start_utc` ascending with `created_at` ascending as the tie-break."

    Design: Difficulty/resource_temporal_overlap/shift_window_admits_the_touching_sixteen_hundred_start_and_the_exact_720_minute_span_but_refuses_15_59_and_721
    """
    setup = five_windows_against_one_rostered_shift
    shift = get_success_data(setup["touching_endpoint"])
    assert shift["status"] == "SCHEDULED"
    assert shift["assigned_acuity_load_units"] == pytest.approx(0.0, abs=1e-9)
    assert shift["capacity_units_effective"] is None
    assert shift["version"] == 1
    base = get_success_data(
        api_client.get_shift(setup["base"]["id"], setup["world"].charge_headers)
    )
    assert base["status"] == "SCHEDULED"
    assert base["version"] == 1


def test_the_span_cap_admits_exactly_seven_hundred_and_twenty_minutes(
    five_windows_against_one_rostered_shift,
):
    """"A shift's span may not exceed 720 minutes" — a span of exactly 720 does
    not exceed it, so the window stands.

    Design: Difficulty/resource_temporal_overlap/shift_window_admits_the_touching_sixteen_hundred_start_and_the_exact_720_minute_span_but_refuses_15_59_and_721
    """
    setup = five_windows_against_one_rostered_shift
    shift = get_success_data(setup["exactly_at_the_cap"])
    assert_shift_assignment(shift)
    assert minutes_between(CAP_EXACT_START, CAP_EXACT_END) == MAX_SHIFT_MINUTES
    assert_instant_equals(shift["shift_start_utc"], CAP_EXACT_START, "shift_start_utc")
    assert_instant_equals(shift["shift_end_utc"], CAP_EXACT_END, "shift_end_utc")
    assert shift["status"] == "SCHEDULED"


def test_one_minute_over_the_cap_is_refused_on_its_own_terms(
    five_windows_against_one_rostered_shift,
):
    """"A window longer than 720 minutes is refused with `ERR_SHIFT_WINDOW_TOO_LONG`, and a
    window sharing any instant with another window already rostered for the same
    staff member is refused with `ERR_SHIFT_WINDOW_OVERLAP`." The nurse holds nothing else on that day, so
    the overlap rule cannot be the reason.

    Design: Difficulty/resource_temporal_overlap/shift_window_admits_the_touching_sixteen_hundred_start_and_the_exact_720_minute_span_but_refuses_15_59_and_721
    """
    setup = five_windows_against_one_rostered_shift
    response = setup["one_minute_over_the_cap"]
    validate_error(response, ApiErrorId.ERR_SHIFT_WINDOW_TOO_LONG.value, 409)
    assert (
        response.json()["data"]["error_id"] != ApiErrorId.ERR_SHIFT_WINDOW_OVERLAP.value
    )
    assert minutes_between(CAP_OVER_START, CAP_OVER_END) == MAX_SHIFT_MINUTES + 1


def test_the_overlap_search_is_keyed_on_the_staff_member(
    five_windows_against_one_rostered_shift,
):
    """"A window longer than 720 minutes is refused with `ERR_SHIFT_WINDOW_TOO_LONG`, and a
    window sharing any instant with another window already rostered for the same
    staff member is refused with `ERR_SHIFT_WINDOW_OVERLAP`." — the identical
    window for a different nurse in the same unit and the same role slot stands.

    Design: Difficulty/resource_temporal_overlap/shift_window_admits_the_touching_sixteen_hundred_start_and_the_exact_720_minute_span_but_refuses_15_59_and_721
    """
    setup = five_windows_against_one_rostered_shift
    world = setup["world"]
    shift = get_success_data(setup["same_minute_other_nurse"])
    assert_shift_assignment(shift)
    assert shift["staff_id"] == world.staff_id("other")
    assert shift["role_slot"] == "BEDSIDE"
    assert_instant_equals(shift["shift_start_utc"], OVERLAP_START, "shift_start_utc")
    assert shift["status"] == "SCHEDULED"


def test_only_the_admitted_windows_were_ever_written(
    five_windows_against_one_rostered_shift,
):
    """A refused roster entry leaves no row behind, so the calendar holds the
    base window, the touching window and the exact-cap window for the night
    nurse and nothing else, "ordered by `shift_start_utc` ascending".

    Design: Difficulty/resource_temporal_overlap/shift_window_admits_the_touching_sixteen_hundred_start_and_the_exact_720_minute_span_but_refuses_15_59_and_721
    """
    setup = five_windows_against_one_rostered_shift
    world = setup["world"]
    rows = api_client.list_shifts(
        world.charge_headers,
        params={"staff_id": world.staff_id("night"), "limit": 100},
    ).json()["data"]
    assert len(rows) == 3
    starts = [row["shift_start_utc"] for row in rows]
    for expected, actual in zip([BASE_START, TOUCHING_START, CAP_EXACT_START], starts):
        assert_instant_equals(actual, expected, "shift_start_utc")
    all_rows = api_client.list_shifts(
        world.charge_headers, params={"unit_id": world.unit_id, "limit": 100}
    ).json()["data"]
    assert len(all_rows) == 4
