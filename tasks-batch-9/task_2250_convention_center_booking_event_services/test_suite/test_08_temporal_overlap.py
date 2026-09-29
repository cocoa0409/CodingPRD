"""Three different interval readings: tree occupancy, per-day aggregates and separation."""

from test_helpers import (
    BALLROOM_B,
    EVENT_SERVICES,
    HALL_A,
    HALL_A1,
    MEETING_ROOM_301,
    RIVERBEND_ROTARY,
    SALES_MANAGER,
    SUNBELT_PROMOTER,
    TEAMSTERS_LOCAL_7,
    ApiClient,
    ApiErrorId,
    approve_blackout,
    assert_crew_hours,
    assert_fields,
    assert_money_cents,
    booking_payload,
    confirm_first_option,
    create_booking,
    labor_call_payload,
    place_hold,
    propose_blackout,
    publish_window,
    read_booking,
    read_hold,
    read_maintenance_blackout,
    read_space,
    read_union_jurisdiction,
    register_child_space,
    register_client,
    register_space,
    register_union_local,
    schedule_labor_call,
    setup_event_lifecycle,
    validate_error,
    validate_paginated,
    validate_success,
)

HARVEST_MARKET = {
    "event_name": "Riverbend Harvest Market",
    "move_in_start_date": "2027-10-05",
    "show_start_date": "2027-10-06",
    "show_end_date": "2027-10-08",
    "move_out_end_date": "2027-10-09",
}

ANTIQUE_SHOW = {
    "event_name": "Riverbend Antique Show",
    "move_in_start_date": "2027-10-06",
    "show_start_date": "2027-10-07",
    "show_end_date": "2027-10-09",
    "move_out_end_date": "2027-10-10",
}


def _confirmed_child_hold_and_two_ancestor_bookings(api: ApiClient):
    """A confirmed hold on Hall A1 plus two unheld bookings on its parent Hall A."""
    publish_window(api, "CONSUMER_SHOW")
    hall = register_space(api, **dict(HALL_A))
    child = register_child_space(api, hall["id"], **dict(HALL_A1))

    sunbelt = register_client(api, **dict(SUNBELT_PROMOTER))
    rotary = register_client(api, **dict(RIVERBEND_ROTARY))

    child_booking = create_booking(
        api,
        sunbelt["id"],
        child["id"],
        event_name="Sunbelt Craft Fair",
        event_class="CONSUMER_SHOW",
        move_in_start_date="2027-10-01",
        show_start_date="2027-10-02",
        show_end_date="2027-10-04",
        move_out_end_date="2027-10-05",
    )
    child_hold = place_hold(api, child_booking["id"])
    confirm_first_option(api, child_hold["id"])

    touching = create_booking(
        api, rotary["id"], hall["id"], event_class="CONSUMER_SHOW", **HARVEST_MARKET
    )
    clear = create_booking(
        api, rotary["id"], hall["id"], event_class="CONSUMER_SHOW", **ANTIQUE_SHOW
    )

    return {
        "space": hall,
        "child_space": child,
        "child_hold": child_hold,
        "touching_booking": touching,
        "clear_booking": clear,
    }


def _hold_attempt(api: ApiClient, booking_id: str):
    booking = read_booking(api, booking_id)
    return api.create_hold(
        booking_id, expected_booking_version=booking["version"], headers=SALES_MANAGER
    )


def test_ancestor_hold_sharing_one_endpoint_with_a_confirmed_child_hold_is_refused(
    api: ApiClient,
):
    """A parent-hall hold starting on the day the child's confirmed hold ends collides.

    PRD: "Two closed intervals **intersect** when the first begins on or before the
    second ends and the second begins on or before the first ends. A single shared
    endpoint therefore counts as an intersection: a range ending on the 10th
    intersects a range starting on the 10th."
    PRD: "No hold whose `status` is `CONFIRMED` may exist on the same space or on
    any related space with a closed interval that intersects the new hold's — a
    confirmed hold is a committed hold, and a collision is refused with
    `ERR_SPACE_DATE_CONFLICT`."
    PRD: "Throughout this specification a **related space** of some space S means S
    itself, any ancestor of S reached by following `parent_space_id` upward any
    number of times, or any descendant of S reached by following the same links
    downward any number of times."

    Design: Difficulty/resource_temporal_overlap/hold_on_ancestor_space_rejected_when_closed_intervals_share_one_endpoint
    """
    world = _confirmed_child_hold_and_two_ancestor_bookings(api)

    response = _hold_attempt(api, world["touching_booking"]["id"])
    validate_error(response, ApiErrorId.SPACE_DATE_CONFLICT, expected_status=409)

    assert_fields(read_booking(api, world["touching_booking"]["id"]), hold_count=0)
    assert_fields(read_hold(api, world["child_hold"]["id"]), status="CONFIRMED")


def test_ancestor_hold_one_day_clear_of_the_child_hold_ranks_first(api: ApiClient):
    """A parent-hall hold starting the day after the child's interval ends is admitted.

    PRD: "The new hold's `hold_rank` is one greater than the number of holds in that
    set, so a hold with no competitors ranks 1 and the third overlapping hold on a
    hall ranks 3."
    PRD: "A separate derived field, `hold_count`, counts the holds on this booking
    whose `status` is `ACTIVE`, `CHALLENGED` or `CONFIRMED`, and starts at 0."

    Design: Difficulty/resource_temporal_overlap/hold_on_ancestor_space_rejected_when_closed_intervals_share_one_endpoint
    """
    world = _confirmed_child_hold_and_two_ancestor_bookings(api)

    response = _hold_attempt(api, world["clear_booking"]["id"])
    hold = validate_success(response, expected_status=201)
    assert_fields(hold, hold_rank=1, status="ACTIVE")

    assert_fields(read_booking(api, world["clear_booking"]["id"]), hold_count=1)
    assert_fields(read_hold(api, world["child_hold"]["id"]), status="CONFIRMED")


def _local_filled_to_eight_of_twelve_crew_hours(api: ApiClient):
    """An IN_HOUSE booking with one 8.0 crew-hour utilities call against a 12-hour local."""
    world = setup_event_lifecycle(
        api,
        "in_house",
        space=dict(MEETING_ROOM_301),
        deposit_cents=200000,
    )
    local = register_union_local(api, **dict(TEAMSTERS_LOCAL_7))
    first = schedule_labor_call(
        api, world["booking"]["id"], local["id"], "UTILITIES", "2027-03-01", 8.0, 12.0, 2
    )
    world["local"] = local
    world["first_call"] = first
    return world


def _second_call(api: ApiClient, world, start_hour: float, end_hour: float):
    return api.create_labor_call(
        world["booking"]["id"],
        payload=labor_call_payload(
            world["local"]["id"], "UTILITIES", "2027-03-01", start_hour, end_hour, 1
        ),
        headers=EVENT_SERVICES,
    )


def test_a_second_call_filling_the_day_exactly_to_capacity_is_accepted(api: ApiClient):
    """Four more crew-hours bring the day to exactly 12.0 and the call is written.

    PRD: "The capacity gate is evaluated per calendar day, not against the running
    total: for the submitted `work_date`, the sum of `billed_hours` over that local's
    calls on that date whose `status` is `SCHEDULED`, `DISPATCHED` or `ACTUALIZED`,
    including the call now being written, must be no greater than the local's
    `max_crew_hours_per_day`."
    PRD: "The comparison is inclusive, so filling a day exactly to capacity is
    accepted and only exceeding it is refused, with
    `ERR_UNION_CREW_OVERCOMMITTED`."
    PRD: "The estimate, written at creation into `estimated_charge_cents`, is
    generous to the licensee: take the hours per crew member as the greater of the
    local's `min_call_hours` and the scheduled span, multiply by `crew_size` and by
    the local's `straight_time_rate_cents`, and round half up to whole cents."

    Design: Difficulty/resource_temporal_overlap/union_day_capacity_accepts_exact_fill_then_refuses_one_more_call
    """
    world = _local_filled_to_eight_of_twelve_crew_hours(api)

    call = validate_success(_second_call(api, world, 8.0, 12.0), expected_status=201)
    assert_crew_hours(call["billed_hours"], 4.0)
    assert_money_cents(call["estimated_charge_cents"], 32000, "estimated_charge_cents")

    assert_crew_hours(
        read_union_jurisdiction(api, world["local"]["id"])["committed_crew_hours"], 12.0
    )


def test_one_more_call_beyond_the_filled_day_is_refused(api: ApiClient):
    """The next four crew-hours on the same date exceed capacity and are refused.

    PRD: "And the local's daily capacity must hold."
    PRD: "The local's `committed_crew_hours` is the sum of `billed_hours` over its
    calls whose `status` is `SCHEDULED`, `DISPATCHED` or `ACTUALIZED`, and cancelled
    calls contribute nothing."

    Design: Difficulty/resource_temporal_overlap/union_day_capacity_accepts_exact_fill_then_refuses_one_more_call
    """
    world = _local_filled_to_eight_of_twelve_crew_hours(api)
    validate_success(_second_call(api, world, 8.0, 12.0), expected_status=201)

    response = _second_call(api, world, 9.0, 13.0)
    validate_error(response, ApiErrorId.UNION_CREW_OVERCOMMITTED, expected_status=409)

    assert_crew_hours(
        read_union_jurisdiction(api, world["local"]["id"])["committed_crew_hours"], 12.0
    )

    items, _meta = validate_paginated(
        api.list_labor_calls(headers=EVENT_SERVICES, booking_id=world["booking"]["id"])
    )
    assert len(items) == 2, f"expected exactly two labor calls, got {len(items)}"


def _approved_capital_project_on_the_ballroom(api: ApiClient):
    """An APPROVED capital-project window on Ballroom B demanding two days on each side."""
    publish_window(api, "CONSUMER_SHOW")
    space = register_space(api, **dict(BALLROOM_B))
    client = register_client(api, **dict(SUNBELT_PROMOTER))
    blackout = propose_blackout(
        api, space["id"], "2027-12-01", "2027-12-10", "CAPITAL_PROJECT", 2
    )
    approve_blackout(api, blackout["id"])
    return {"space": space, "client": client, "blackout": blackout}


def _bazaar_payload(client_id: str, space_id: str, *, extended: bool):
    if extended:
        return booking_payload(
            client_id,
            space_id,
            event_name="Sunbelt Holiday Bazaar Extended",
            event_class="CONSUMER_SHOW",
            move_in_start_date="2027-11-25",
            show_start_date="2027-11-26",
            show_end_date="2027-11-28",
            move_out_end_date="2027-11-29",
        )
    return booking_payload(
        client_id,
        space_id,
        event_name="Sunbelt Holiday Bazaar",
        event_class="CONSUMER_SHOW",
        move_in_start_date="2027-11-24",
        show_start_date="2027-11-25",
        show_end_date="2027-11-27",
        move_out_end_date="2027-11-28",
    )


def test_a_three_day_separation_from_the_maintenance_window_is_admitted(api: ApiClient):
    """A booking ending three days before the window starts clears a two-day buffer.

    PRD: "A candidate interval **clears** the maintenance window only when it does
    not intersect the buffered window — equivalently, only when the candidate ends
    more than `buffer_days` days before `window_start_date`, or begins more than
    `buffer_days` days after `window_end_date`."
    PRD: "`space_days_committed` is the inclusive number of days from
    `move_in_start_date` through `move_out_end_date` — the difference in calendar
    days plus one — and the named space's `committed_space_days` rises by exactly
    that figure."

    Design: Difficulty/resource_temporal_overlap/blackout_buffer_clearance_admits_three_day_gap_and_refuses_two_day_gap
    """
    world = _approved_capital_project_on_the_ballroom(api)

    response = api.create_booking(
        payload=_bazaar_payload(world["client"]["id"], world["space"]["id"], extended=False),
        headers=SALES_MANAGER,
    )
    booking = validate_success(response, expected_status=201)
    assert_fields(booking, status="TENTATIVE", space_days_committed=5)


def test_a_two_day_separation_from_the_maintenance_window_is_refused(api: ApiClient):
    """A booking ending exactly two days before the window is not separated enough.

    PRD: "Separation of exactly `buffer_days` days is not enough; the requirement is
    strictly more than that many days, on both sides."
    PRD: "The **maintenance clearance** gate requires the booking's closed interval
    from `move_in_start_date` through `move_out_end_date` to clear every `APPROVED`
    maintenance window on the named space and on every related space, by the
    buffered-window rule of §2.7; a collision is
    `ERR_MAINTENANCE_BLACKOUT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/blackout_buffer_clearance_admits_three_day_gap_and_refuses_two_day_gap
    """
    world = _approved_capital_project_on_the_ballroom(api)
    validate_success(
        api.create_booking(
            payload=_bazaar_payload(world["client"]["id"], world["space"]["id"], extended=False),
            headers=SALES_MANAGER,
        ),
        expected_status=201,
    )

    response = api.create_booking(
        payload=_bazaar_payload(world["client"]["id"], world["space"]["id"], extended=True),
        headers=SALES_MANAGER,
    )
    validate_error(response, ApiErrorId.MAINTENANCE_BLACKOUT_CONFLICT, expected_status=409)

    assert read_space(api, world["space"]["id"])["committed_space_days"] == 5
    assert_fields(read_maintenance_blackout(api, world["blackout"]["id"]), status="APPROVED")
