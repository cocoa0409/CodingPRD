"""Two opposite interval conventions on two different shared resources.

A venue zone is occupied over a closed window inflated by ninety minutes on both
ends, while a host's shift is half-open with no buffer and is tested as an
aggregate concurrency count rather than pairwise.
"""

from typing import Any, Dict

from test_helpers import (
    ERR_BUILD_ZONE_CONFLICT,
    ERR_HOST_CAPACITY_EXCEEDED,
    OPERATIONS_MANAGER,
    ApiClient,
    allocate_booking,
    assert_block_position,
    assert_list_page,
    assert_total_count,
    confirm_tranche,
    get_success_data,
    host_assignment_payload,
    hospitality_build_payload,
    ids_of,
    make_assignment,
    make_block,
    make_booking,
    make_client,
    make_committed_deal,
    make_event,
    make_host,
    make_published_gold_package,
    make_ready_build,
    make_tranche,
    read_block,
    read_host,
    reset_clock,
    validate_error,
)

MATCH_DAY = "2027-02-01T"


def _zone_a_occupied_from_nine_to_two(api: ApiClient) -> Dict[str, Any]:
    """A PLANNED build holding ZONE_A from 09:00 to 14:00 on match day."""
    reset_clock(api)
    event = make_event(api)
    incumbent = _plan_build(api, event["id"], "ZONE_A", "09:00", "14:00")
    return {"event": event, "incumbent": get_success_data(incumbent, 201)}


def _plan_build(api: ApiClient, event_id: str, zone: str, start: str, end: str):
    """Fire POST /hospitality-builds for one match-day window, without asserting."""
    payload = hospitality_build_payload(
        event_id,
        zone_code=zone,
        service_window_start=f"{MATCH_DAY}{start}:00.000Z",
        service_window_end=f"{MATCH_DAY}{end}:00.000Z",
        space_units=30,
        catering_covers=20,
        staff_count=5,
    )
    return api.create_hospitality_build(payload, OPERATIONS_MANAGER)


def _host_carrying_two_overlapping_shifts(api: ApiClient) -> Dict[str, Any]:
    """A capacity-2 host already working 10:00-14:00 and 12:00-16:00.

    Four five-unit bookings are allocated first — together consuming exactly the
    block's forty ticket units — so that each shift names a booking that
    genuinely holds inventory.
    """
    reset_clock(api)
    event = make_event(api)
    deal = make_committed_deal(api, event["id"])
    block = make_block(api, deal["id"], channel="CORPORATE", target_units=40,
                       priority_rank=1)
    tranche = make_tranche(api, deal["id"], promised_units=60)
    confirm_tranche(api, tranche["id"], deal["id"], 60)
    package = make_published_gold_package(api, event["id"])
    client = make_client(api)

    bookings = []
    for _ in range(4):
        booking = make_booking(api, client["id"], package["id"],
                               channel="CORPORATE", units=5)
        bookings.append(allocate_booking(api, booking["id"], block["id"]))

    build = make_ready_build(api, event["id"])
    host = make_host(api, max_concurrent_bookings=2)
    early = make_assignment(api, host["id"], bookings[0]["id"], build["id"],
                            shift_start=f"{MATCH_DAY}10:00:00.000Z",
                            shift_end=f"{MATCH_DAY}14:00:00.000Z")
    middle = make_assignment(api, host["id"], bookings[1]["id"], build["id"],
                             shift_start=f"{MATCH_DAY}12:00:00.000Z",
                             shift_end=f"{MATCH_DAY}16:00:00.000Z")
    return {
        "event": event,
        "block": block,
        "package": package,
        "client": client,
        "bookings": bookings,
        "build": build,
        "host": read_host(api, host["id"]),
        "early": early,
        "middle": middle,
    }


def _roster(api: ApiClient, scenario: Dict[str, Any], booking_index: int,
            start: str, end: str):
    """Fire POST /host-assignments for one match-day shift, without asserting."""
    payload = host_assignment_payload(
        scenario["host"]["id"],
        scenario["bookings"][booking_index]["id"],
        scenario["build"]["id"],
        shift_start=f"{MATCH_DAY}{start}:00.000Z",
        shift_end=f"{MATCH_DAY}{end}:00.000Z",
    )
    return api.create_host_assignment(payload, OPERATIONS_MANAGER)


# --------------------------------------------------------------------------
# Venue zones: closed windows plus a symmetric ninety-minute buffer
# --------------------------------------------------------------------------


def test_a_gap_of_exactly_ninety_minutes_conflicts_and_ninety_one_does_not(
    api: ApiClient,
) -> None:
    """One minute separates a rejected window from an accepted one.

    Against an incumbent ending at 14:00, a window starting at 15:30 leaves
    exactly ninety minutes of clearance and is refused; a window starting at
    15:31 leaves ninety-one and is accepted. No implementation with a zero,
    sixty or one-hundred-and-twenty-minute buffer, and none using a strict
    comparison at the boundary, gives both answers.

    PRD §2.10: "Windows that merely touch conflict; a gap of exactly ninety
    minutes conflicts; a gap of ninety-one minutes does not."

    Design: Difficulty/resource_temporal_overlap/build_zone_closed_interval_with_ninety_minute_buffer_conflicts
    """
    scenario = _zone_a_occupied_from_nine_to_two(api)
    event_id = scenario["event"]["id"]
    assert scenario["incumbent"]["build_state"] == "PLANNED"

    validate_error(_plan_build(api, event_id, "ZONE_A", "15:30", "20:00"),
                   ERR_BUILD_ZONE_CONFLICT, 409)

    accepted = get_success_data(
        _plan_build(api, event_id, "ZONE_A", "15:31", "20:00"), 201
    )
    assert accepted["build_state"] == "PLANNED"

    page = api.list_hospitality_builds(OPERATIONS_MANAGER,
                                       {"event_id": event_id, "zone_code": "ZONE_A"})
    assert_list_page(page, expected_total=2, expected_rows=2)
    assert set(ids_of(get_success_data(page))) == {
        scenario["incumbent"]["id"], accepted["id"]
    }


def test_the_zone_is_the_resource_and_its_window_is_closed_at_both_ends(
    api: ApiClient,
) -> None:
    """The same window on another zone is fine; touching an end instant is not.

    The occupancy that blocks ZONE_A from 09:00 to 14:00 says nothing about
    ZONE_B, so the identical window is accepted there — the resource is the zone
    on the fixture, not the fixture. Once ZONE_B is occupied, a window starting
    at exactly 14:00 collides with it, because both end instants are occupied and
    a merely touching window conflicts.

    PRD §2.10: "A hospitality build's occupancy of a venue zone is a **closed**
    interval: both `service_window_start` and `service_window_end` are instants
    at which the zone is considered occupied."

    Design: Difficulty/resource_temporal_overlap/build_zone_closed_interval_with_ninety_minute_buffer_conflicts
    """
    scenario = _zone_a_occupied_from_nine_to_two(api)
    event_id = scenario["event"]["id"]

    other_zone = get_success_data(
        _plan_build(api, event_id, "ZONE_B", "09:00", "14:00"), 201
    )
    assert other_zone["zone_code"] == "ZONE_B"

    validate_error(_plan_build(api, event_id, "ZONE_B", "14:00", "16:00"),
                   ERR_BUILD_ZONE_CONFLICT, 409)

    assert_total_count(
        api.list_hospitality_builds(OPERATIONS_MANAGER,
                                    {"event_id": event_id, "zone_code": "ZONE_B"}), 1
    )
    assert_total_count(
        api.list_hospitality_builds(OPERATIONS_MANAGER,
                                    {"event_id": event_id, "zone_code": "ZONE_A"}), 1
    )


# --------------------------------------------------------------------------
# Host shifts: half-open, unbuffered, and counted in aggregate
# --------------------------------------------------------------------------


def test_a_shift_beginning_when_another_ends_is_accepted(api: ApiClient) -> None:
    """Adjacency at 14:00 is permitted, and the host may hold three rosters.

    The new 14:00-18:00 shift does not overlap the 10:00-14:00 one at all,
    because the earlier shift does not cover its own end instant, so peak
    concurrency over the new shift is two — exactly the capacity. The host's
    assignment counter then reads 3, above its capacity of two, which is what
    shows the rule bounds instantaneous concurrency rather than the number of
    rosters held.

    PRD §2.10: "A shift that ends at precisely the instant another begins does
    not overlap it, and adjacency is therefore permitted."

    Design: Difficulty/resource_temporal_overlap/host_shift_half_open_adjacency_allowed_with_aggregate_capacity
    """
    scenario = _host_carrying_two_overlapping_shifts(api)
    assert scenario["host"]["max_concurrent_bookings"] == 2
    assert scenario["host"]["active_assignment_count"] == 2
    assert_block_position(read_block(api, scenario["block"]["id"]), allocated=40,
                          committed=40, released_back=0, state="EXHAUSTED")

    adjacent = get_success_data(_roster(api, scenario, 2, "14:00", "18:00"), 201)

    assert adjacent["assignment_state"] == "ASSIGNED"
    assert read_host(api, scenario["host"]["id"])["active_assignment_count"] == 3


def test_a_shorter_shift_inside_the_double_cover_exceeds_the_capacity(
    api: ApiClient,
) -> None:
    """A strictly shorter shift is refused where a longer one was accepted.

    Over 13:00-14:00 the two existing shifts are both live, so the proposed
    13:00-15:00 shift would make three concurrent at that instant against a
    capacity of two. Every pairwise comparison passes — no two shifts alone
    exceed the capacity — so only the aggregate per-instant test refuses this.
    Nothing is written: the host still holds its three earlier rosters and the
    fourth booking has none.

    PRD §2.10: "The host capacity rule is an **aggregate** test rather than a
    pairwise one: for every instant covered by the proposed shift, the number of
    that host's existing `ASSIGNED` assignments whose half-open shift contains
    that instant, plus one for the proposed shift itself, must be at most the
    host's `max_concurrent_bookings`."

    Design: Difficulty/resource_temporal_overlap/host_shift_half_open_adjacency_allowed_with_aggregate_capacity
    """
    scenario = _host_carrying_two_overlapping_shifts(api)
    host_id = scenario["host"]["id"]
    adjacent = get_success_data(_roster(api, scenario, 2, "14:00", "18:00"), 201)

    validate_error(_roster(api, scenario, 3, "13:00", "15:00"),
                   ERR_HOST_CAPACITY_EXCEEDED, 409)

    assert read_host(api, host_id)["active_assignment_count"] == 3
    page = api.list_host_assignments(OPERATIONS_MANAGER,
                                     {"on_site_host_id": host_id})
    assert_list_page(page, expected_total=3, expected_rows=3)
    rows = get_success_data(page)
    assert set(ids_of(rows)) == {scenario["early"]["id"], scenario["middle"]["id"],
                                 adjacent["id"]}
    assert all(row["assignment_state"] == "ASSIGNED" for row in rows)
    assert_total_count(
        api.list_host_assignments(OPERATIONS_MANAGER,
                                  {"booking_id": scenario["bookings"][3]["id"]}), 0
    )
