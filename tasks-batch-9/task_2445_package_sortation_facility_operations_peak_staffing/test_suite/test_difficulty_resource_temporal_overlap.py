"""Two contended resources with deliberately different interval semantics.

A dock door inflates every window by its turnaround buffer on both sides, so
exact adjacency conflicts and only one trailer may hold the door at a time. A
sortation chute applies no buffer at all and carries an aggregate capacity, so
two overlapping destinations are legal and touching at a shared endpoint is not
an overlap.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_CHUTE_CONCURRENCY_EXCEEDED,
    ERR_DOOR_WINDOW_CONFLICT,
)
from test_helpers.constants import DEFAULT_TURNAROUND_BUFFER_MIN
from test_helpers.fixtures import shift_instant
from test_helpers.test_users import INBOUND_COORDINATOR_HEADERS, SORT_SUPERVISOR_HEADERS


# ─── DockDoor: buffered intervals ─────────────────────

BOOKED_START = "2026-08-01T06:00:00Z"
BOOKED_END = "2026-08-01T07:00:00Z"


def _door_holding_one_scheduled_appointment(world, facility):
    """One inbound door on its default fifteen-minute turnaround buffer, holding a
    single `SCHEDULED` appointment for 06:00 to 07:00."""
    door = facility["inbound_door"]
    assert door["turnaround_buffer_min"] == DEFAULT_TURNAROUND_BUFFER_MIN
    booked = world.schedule_appointment(
        facility["center"]["id"],
        door["id"],
        window_start=BOOKED_START,
        window_end=BOOKED_END,
        manifest_package_count=1200,
    )
    assert booked["status"] == "SCHEDULED"
    return booked


def _book(api, center_id, door_id, window_start, window_end, trailer_code=None):
    payload = f.trailer_appointment_payload(
        center_id,
        door_id,
        window_start=window_start,
        window_end=window_end,
        manifest_package_count=800,
    )
    if trailer_code is not None:
        payload["trailer_code"] = trailer_code
    return api.create_trailer_appointment(payload, INBOUND_COORDINATOR_HEADERS)


def test_appointment_starting_exactly_when_the_booked_one_ends_is_rejected(
    world, api, facility
):
    """PRD §3.3: "The practical consequences are worth stating plainly: two appointments that touch exactly (the new window starting at the instant the existing one ends) *do* conflict, because zero clearance is less than any positive buffer; and a gap of exactly the buffer's length is *accepted*, because the strict comparison just fails to trigger."

    Design: Difficulty/resource_temporal_overlap/dock_door_buffered_intervals_treat_adjacency_as_conflict
    """
    booked = _door_holding_one_scheduled_appointment(world, facility)

    response = _book(
        api,
        facility["center"]["id"],
        facility["inbound_door"]["id"],
        BOOKED_END,
        "2026-08-01T08:00:00Z",
    )
    validate_error(response, ERR_DOOR_WINDOW_CONFLICT)

    assert world.appointment(booked["id"])["status"] == "SCHEDULED"


def test_appointment_ending_exactly_when_the_booked_one_starts_is_rejected(
    world, api, facility
):
    """PRD §3.3: "The door's own `turnaround_buffer_min` is inflated onto **both** sides of the comparison: the booking conflicts with an existing appointment when the new window's start is before the existing window's end advanced by the buffer, and simultaneously the existing window's start is before the new window's end advanced by the buffer."

    Design: Difficulty/resource_temporal_overlap/dock_door_buffered_intervals_treat_adjacency_as_conflict
    """
    booked = _door_holding_one_scheduled_appointment(world, facility)

    response = _book(
        api,
        facility["center"]["id"],
        facility["inbound_door"]["id"],
        "2026-08-01T05:00:00Z",
        BOOKED_START,
    )
    validate_error(response, ERR_DOOR_WINDOW_CONFLICT)

    assert world.appointment(booked["id"])["status"] == "SCHEDULED"


def test_gap_of_exactly_the_turnaround_buffer_is_bookable_on_either_side(
    world, api, facility
):
    """PRD §3.3: "The practical consequences are worth stating plainly: two appointments that touch exactly (the new window starting at the instant the existing one ends) *do* conflict, because zero clearance is less than any positive buffer; and a gap of exactly the buffer's length is *accepted*, because the strict comparison just fails to trigger."

    Design: Difficulty/resource_temporal_overlap/dock_door_buffered_intervals_treat_adjacency_as_conflict
    """
    _door_holding_one_scheduled_appointment(world, facility)
    center_id = facility["center"]["id"]
    door_id = facility["inbound_door"]["id"]

    after_start = shift_instant(BOOKED_END, minutes=DEFAULT_TURNAROUND_BUFFER_MIN)
    after = validate_success(
        _book(api, center_id, door_id, after_start, shift_instant(after_start, hours=1)),
        201,
    )
    assert after["status"] == "SCHEDULED"
    assert after["window_start"] == after_start

    before_end = shift_instant(BOOKED_START, minutes=-DEFAULT_TURNAROUND_BUFFER_MIN)
    before = validate_success(
        _book(
            api, center_id, door_id, shift_instant(before_end, hours=-1), before_end
        ),
        201,
    )
    assert before["status"] == "SCHEDULED"
    assert before["window_end"] == before_end


def test_refused_window_becomes_bookable_once_the_holder_reaches_unloaded(
    world, api, facility
):
    """PRD §3.3: "The population under test is the appointments already on that same door whose `status` is `SCHEDULED`, `ARRIVED`, `UNLOADING` or `JAM_HELD`; an appointment that has reached `UNLOADED` has released the door and is ignored."

    Design: Difficulty/resource_temporal_overlap/dock_door_buffered_intervals_treat_adjacency_as_conflict
    """
    booked = _door_holding_one_scheduled_appointment(world, facility)
    center_id = facility["center"]["id"]
    door_id = facility["inbound_door"]["id"]
    contender_code = f.unique_trailer_code()

    validate_error(
        _book(
            api,
            center_id,
            door_id,
            BOOKED_END,
            "2026-08-01T08:00:00Z",
            trailer_code=contender_code,
        ),
        ERR_DOOR_WINDOW_CONFLICT,
    )

    validate_success(api.arrive_trailer_appointment(booked["id"], INBOUND_COORDINATOR_HEADERS))
    validate_success(api.start_unload(booked["id"], INBOUND_COORDINATOR_HEADERS))
    released = validate_success(
        api.complete_unload(booked["id"], INBOUND_COORDINATOR_HEADERS)
    )
    assert released["status"] == "UNLOADED"

    accepted = validate_success(
        _book(
            api,
            center_id,
            door_id,
            BOOKED_END,
            "2026-08-01T08:00:00Z",
            trailer_code=contender_code,
        ),
        201,
    )
    assert accepted["status"] == "SCHEDULED"
    assert accepted["door_id"] == door_id
    assert world.center(center_id)["wip_package_count"] == 1200


# ─── SortChute: unbuffered aggregate intervals ────────

FIRST_START = "2026-08-01T06:00:00Z"
FIRST_END = "2026-08-01T10:00:00Z"
SECOND_START = "2026-08-01T08:00:00Z"
SECOND_END = "2026-08-01T12:00:00Z"


def _chute_carrying_two_overlapping_destinations(world):
    """One chute permitting two concurrent destinations, already holding two
    mappings that overlap between 08:00 and 10:00, plus a third unmapped lane."""
    built = world.setup_facility(map_assignment=False)
    center_id = built["center"]["id"]
    chute = built["chute"]
    assert chute["max_concurrent_destinations"] == 2
    lane_two = world.create_lane(center_id, forecast_hourly_volume=900)
    lane_three = world.create_lane(
        center_id, forecast_hourly_volume=900, service_class="EXPRESS"
    )
    first = world.map_lane_to_chute(
        chute["id"],
        built["lane"]["id"],
        window_start=FIRST_START,
        window_end=FIRST_END,
    )
    second = world.map_lane_to_chute(
        chute["id"], lane_two["id"], window_start=SECOND_START, window_end=SECOND_END
    )
    assert first["status"] == "ACTIVE"
    assert second["status"] == "ACTIVE"
    built.update({"lane_two": lane_two, "lane_three": lane_three,
                  "first": first, "second": second})
    return built


def test_third_simultaneous_destination_on_the_chute_is_rejected(world, api):
    """PRD §3.2: "The requested occupancy is one plus the largest number of existing assignments that overlap at any single instant inside the new window, and when that number exceeds the chute's `max_concurrent_destinations` the create is refused with `ERR_CHUTE_CONCURRENCY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/chute_half_open_intervals_allow_two_concurrent_destinations
    """
    built = _chute_carrying_two_overlapping_destinations(world)
    chute_id = built["chute"]["id"]
    pinned_version = world.chute_version(chute_id)

    response = api.create_chute_assignment(
        f.chute_assignment_payload(
            chute_id,
            built["lane_three"]["id"],
            pinned_version,
            window_start="2026-08-01T09:00:00Z",
            window_end="2026-08-01T09:30:00Z",
        ),
        SORT_SUPERVISOR_HEADERS,
    )
    validate_error(response, ERR_CHUTE_CONCURRENCY_EXCEEDED)

    assert world.chute_version(chute_id) == pinned_version
    assert world.assignment(built["first"]["id"])["status"] == "ACTIVE"
    assert world.assignment(built["second"]["id"])["status"] == "ACTIVE"
    assert world.lane(built["lane_three"]["id"])["assigned_capacity_pph"] == 0


def test_destination_starting_at_the_instant_another_window_ends_is_accepted(
    world, api
):
    """PRD §3.2: "Two intervals overlap when the new window's start is before the existing window's end and the existing window's start is before the new window's end — half-open comparison, no buffer, so two assignments that merely touch at a shared endpoint do not overlap."

    Design: Difficulty/resource_temporal_overlap/chute_half_open_intervals_allow_two_concurrent_destinations
    """
    built = _chute_carrying_two_overlapping_destinations(world)
    chute_id = built["chute"]["id"]
    version_before = world.chute_version(chute_id)

    accepted = validate_success(
        api.create_chute_assignment(
            f.chute_assignment_payload(
                chute_id,
                built["lane_three"]["id"],
                version_before,
                window_start=FIRST_END,
                window_end="2026-08-01T11:00:00Z",
            ),
            SORT_SUPERVISOR_HEADERS,
        ),
        201,
    )
    assert accepted["status"] == "ACTIVE"
    assert accepted["window_start"] == FIRST_END

    assert world.chute_version(chute_id) == version_before + 1
    assert world.assignment(built["first"]["id"])["status"] == "ACTIVE"
    assert world.assignment(built["second"]["id"])["status"] == "ACTIVE"
    assert (
        world.lane(built["lane_three"]["id"])["assigned_capacity_pph"]
        == built["chute"]["throughput_pph"]
    )
