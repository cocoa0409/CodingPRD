"""Two claims on one unit, one worker or one inspection day, and the interval rules."""

from test_helpers import (
    CHAIR_SWINGS,
    KIDDIE_CARS,
    KIDDIE_COASTER,
    LOT_BOSS,
    SAFETY_OFFICER,
    TILT_A_WHIRL,
    ApiErrorId,
    add_route_stop,
    assert_crew_assignment,
    assert_inspection_order,
    assert_instant_equals,
    assert_labor_ledger,
    assert_lot_ledgers,
    assert_ride_allocation,
    book_crew,
    create_crew_assignment_payload,
    create_inspection_order_payload,
    create_ride_allocation_payload,
    current_stop_version,
    list_allocation_inspections,
    open_route,
    read_allocation,
    read_route_stop,
    read_worker,
    register_venue,
    register_worker,
    reserve_allocation,
    schedule_inspection,
    setup_planned_lot,
    setup_planned_lot_with_allocations,
    validate_error,
    validate_paginated,
    validate_success,
)

PLAIN_TILT = dict(TILT_A_WHIRL, requires_state_inspection=False)
SPUR_LOT = {
    "name": "Union County Fairgrounds",
    "city": "Marysville",
    "lot_area_sqft": 200000,
    "power_amps_available": 1000,
    "expected_attendance": 10001,
    "lot_surface": "PAVED",
}
TWO_HOUR_GAP_STOP = {
    "load_in_start": "2026-09-08T14:00:00Z",
    "open_date": "2026-09-11T12:00:00Z",
    "close_date": "2026-09-14T12:00:00Z",
    "teardown_deadline": "2026-09-15T12:00:00Z",
}
FOUR_HOUR_GAP_STOP = dict(TWO_HOUR_GAP_STOP, load_in_start="2026-09-08T16:00:00Z")
OCCUPATION_START = "2026-09-01T06:00:00Z"
OCCUPATION_END = "2026-09-08T12:00:00Z"
SPUR_TEARDOWN_DEADLINE = "2026-09-15T12:00:00Z"

TICKET_SELLER = {
    "full_name": "Tessa Ticket",
    "employment_type": "PERMANENT",
    "hourly_rate_cents": 2000,
    "certified_ride_classes": [],
    "housing_required": False,
}
FIRST_TICKETING_SHIFT = ("2026-09-04T12:00:00Z", "2026-09-04T20:00:00Z")
ADJACENT_TICKETING_SHIFT = ("2026-09-04T20:00:00Z", "2026-09-05T04:00:00Z")
STRADDLING_SHIFT = ("2026-09-04T19:00:00Z", "2026-09-04T21:00:00Z")
SIX_DAY_STATE = {"max_consecutive_work_days": 6}

TWO_SLOT_STATE = {
    "requires_state_ride_inspection": False,
    "inspection_slot_capacity_per_day": 2,
}
PLAIN_COASTER = dict(KIDDIE_COASTER, requires_state_inspection=False)
PLAIN_CARS = dict(KIDDIE_CARS, requires_state_inspection=False)
PLAIN_SWINGS = dict(CHAIR_SWINGS, requires_state_inspection=False)
BUCKET_OPENS = "2026-09-02T00:00:00Z"
BUCKET_LAST_SECOND = "2026-09-02T23:59:59Z"
BUCKET_MIDDAY = "2026-09-02T12:00:00Z"
NEXT_BUCKET_OPENS = "2026-09-03T00:00:00Z"


def _tilt_reserved_on_one_lot_with_two_candidate_spurs():
    """One unit held to a teardown deadline, with a two-hour and a four-hour follower."""
    ctx = setup_planned_lot_with_allocations(ride_specs=[PLAIN_TILT])
    spur_venue = register_venue(ctx["jurisdiction"]["id"], **SPUR_LOT)
    spur_route = open_route(name="2026 Late Fall Spur")
    ctx["spur_venue"] = spur_venue
    ctx["spur_route"] = spur_route
    ctx["near_stop"] = add_route_stop(
        spur_route["id"], spur_venue["id"], **TWO_HOUR_GAP_STOP
    )
    ctx["far_stop"] = add_route_stop(
        spur_route["id"], spur_venue["id"], **FOUR_HOUR_GAP_STOP
    )
    return ctx


def _seller_with_two_back_to_back_shifts():
    """A ticket seller booked twice on one lot, the second starting as the first ends."""
    ctx = setup_planned_lot(jurisdiction_overrides=SIX_DAY_STATE)
    ctx["seller"] = register_worker(**TICKET_SELLER)
    ctx["first_shift"] = book_crew(
        ctx["stop"]["id"], ctx["seller"]["id"], "TICKETING", *FIRST_TICKETING_SHIFT
    )
    ctx["second_shift"] = book_crew(
        ctx["stop"]["id"], ctx["seller"]["id"], "TICKETING", *ADJACENT_TICKETING_SHIFT
    )
    return ctx


def _three_reserved_units_in_a_two_slot_state():
    """Three units reserved in a state that inspects only two rides a day."""
    return setup_planned_lot_with_allocations(
        ride_specs=[PLAIN_COASTER, PLAIN_CARS, PLAIN_SWINGS],
        jurisdiction_overrides=TWO_SLOT_STATE,
    )


def test_a_two_hour_turnaround_is_inside_the_transport_buffer(api):
    """PRD §3.3: "A single unit cannot be in two towns at once, and it cannot teleport
    between them. A reservation is refused with `ERR_RIDE_DOUBLE_BOOKED` when the same
    ride already holds another allocation in `RESERVED`, `COMMITTED`, `INSPECTION_HELD`
    or `OPERATING` whose occupation interval either overlaps the candidate's interval, or
    is separated from it by less than the required haul gap. That required gap is the
    `travel_hours_from_previous` of whichever of the two stops sits later in its haul
    chain — the one with the greater `sequence_index` — plus a four-hour transport
    buffer."

    PRD §2.11: "A ride's occupation interval, by contrast, is treated as **closed** on
    both ends — `[occupation_start, occupation_end]` — because a unit is physically on a
    lot for the whole load-in-to-teardown span including both edges, and two lots that
    share an edge instant cannot both hold the same unit."

    PRD §3.1: "The new stop enters `PLANNED` with `sequence_index` and
    `travel_hours_from_previous` at 0, every capacity, labor and closure aggregate at 0,
    and a `compliance_posture` of `PERMIT_HOLD` — no lot is clear before its event permit
    exists."

    Design: Difficulty/resource_temporal_overlap/ride_occupation_is_closed_and_needs_a_four_hour_transport_buffer
    """
    ctx = _tilt_reserved_on_one_lot_with_two_candidate_spurs()
    held = ctx["allocations"][0]
    assert held["status"] == "RESERVED"
    assert_instant_equals(held["occupation_start"], OCCUPATION_START, "occupation_start")
    assert_instant_equals(held["occupation_end"], OCCUPATION_END, "occupation_end")
    near_stop_id = ctx["near_stop"]["id"]

    validate_error(
        api.create_ride_allocation(
            create_ride_allocation_payload(
                ctx["rides"][0]["id"], near_stop_id, current_stop_version(near_stop_id)
            ),
            LOT_BOSS,
        ),
        ApiErrorId.ERR_RIDE_DOUBLE_BOOKED.value,
        expected_status=409,
    )

    assert_lot_ledgers(read_route_stop(near_stop_id), 0, 0.0)
    _rows, meta = validate_paginated(
        api.list_ride_allocations(LOT_BOSS, params={"route_stop_id": near_stop_id})
    )
    assert meta["total_count"] == 0


def test_a_gap_of_exactly_four_hours_lets_the_unit_move_on(api):
    """PRD §3.3: "That required gap is the `travel_hours_from_previous` of whichever of
    the two stops sits later in its haul chain — the one with the greater
    `sequence_index` — plus a four-hour transport buffer."

    PRD §3.3: "The new allocation enters `RESERVED` with `released_at` null, and its
    occupation interval is fixed at creation: `occupation_start` is copied from the lot's
    `load_in_start` and `occupation_end` from its `teardown_deadline`."

    PRD §3.3: "A ride's **charged footprint**, `footprint_charged_sqft`, is its bare
    `footprint_sqft` multiplied by a spacing multiplier that depends on class — 1.35 for
    `MAJOR`, 1.20 for `FLAT` and 1.10 for `KIDDIE` — and rounded **up** to a whole square
    foot."

    Design: Difficulty/resource_temporal_overlap/ride_occupation_is_closed_and_needs_a_four_hour_transport_buffer
    """
    ctx = _tilt_reserved_on_one_lot_with_two_candidate_spurs()
    ride_id = ctx["rides"][0]["id"]
    far_stop_id = ctx["far_stop"]["id"]

    moved_on = reserve_allocation(ride_id, far_stop_id)
    assert_ride_allocation(moved_on)
    assert moved_on["status"] == "RESERVED"
    assert_instant_equals(
        moved_on["occupation_start"],
        FOUR_HOUR_GAP_STOP["load_in_start"],
        "occupation_start",
    )
    assert_instant_equals(
        moved_on["occupation_end"], SPUR_TEARDOWN_DEADLINE, "occupation_end"
    )
    assert moved_on["footprint_charged_sqft"] == 2404
    assert moved_on["power_charged_amps"] == 138.0

    rows, meta = validate_paginated(
        api.list_ride_allocations(LOT_BOSS, params={"ride_id": ride_id})
    )
    assert meta["total_count"] == 2
    assert all(row["status"] == "RESERVED" for row in rows)


def test_two_shifts_sharing_an_endpoint_do_not_collide(api):
    """PRD §3.6: "Overlap comes next: the worker may hold no other `SCHEDULED`
    assignment whose half-open interval intersects the candidate's, and a collision
    answers `ERR_CREW_SHIFT_OVERLAP`. Back-to-back shifts sharing an endpoint do not
    intersect and are admitted."

    PRD §2.11: "Time intervals in this system are **half-open** unless stated otherwise:
    a crew shift covers `[shift_start, shift_end)`, a weather closure covers
    `[closed_from, closed_to)`, and a daily operating window covers its start instant up
    to but excluding its end instant. Two shifts that share an endpoint — one ending
    exactly when the next begins — therefore do not overlap and are both admitted."

    PRD §3.6: "A rigging premium of 10 percent of that base amount, rounded half-up to
    whole cents, is added for `SETUP` and `TEARDOWN` shifts only, and is zero for
    `RIDE_OPERATOR` and `TICKETING`."

    Design: Difficulty/resource_temporal_overlap/crew_shift_intervals_are_half_open_so_back_to_back_shifts_are_admitted
    """
    ctx = _seller_with_two_back_to_back_shifts()

    for shift in (ctx["first_shift"], ctx["second_shift"]):
        assert_crew_assignment(shift)
        assert shift["status"] == "SCHEDULED"
        assert shift["shift_hours"] == 8.0
        assert shift["cost_cents"] == 16000

    assert_labor_ledger(read_route_stop(ctx["stop"]["id"]), 32000)
    assert read_worker(ctx["seller"]["id"])["scheduled_hours_total"] == 16.0


def test_a_shift_straddling_the_shared_endpoint_is_refused(api):
    """PRD §3.6: "Overlap comes next: the worker may hold no other `SCHEDULED`
    assignment whose half-open interval intersects the candidate's, and a collision
    answers `ERR_CREW_SHIFT_OVERLAP`."

    PRD §3.6: "Then the shift-window rule, which differs by role. `SETUP` and
    `TEARDOWN` shifts may fall anywhere inside the lot's load-in-to-teardown span, from
    `load_in_start` to `teardown_deadline`. `RIDE_OPERATOR` and `TICKETING` shifts must
    lie inside the public operating window, from `open_date` to `close_date`. A shift
    outside the window its role permits is refused with `ERR_SHIFT_OUTSIDE_STOP_WINDOW`."

    PRD §2.10: "The **labor ledger** of a lot, `labor_cost_provisional_cents`, is the
    sum of `cost_cents` over the lot's crew assignments whose status is `SCHEDULED` or
    `COMPLETED`; its per-worker twin, `scheduled_hours_total`, is the sum of
    `shift_hours` over that worker's assignments in the same two statuses, rounded to two
    decimal places."

    Design: Difficulty/resource_temporal_overlap/crew_shift_intervals_are_half_open_so_back_to_back_shifts_are_admitted
    """
    ctx = _seller_with_two_back_to_back_shifts()

    validate_error(
        api.create_crew_assignment(
            create_crew_assignment_payload(
                ctx["stop"]["id"],
                ctx["seller"]["id"],
                "TICKETING",
                *STRADDLING_SHIFT,
            ),
            LOT_BOSS,
        ),
        ApiErrorId.ERR_CREW_SHIFT_OVERLAP.value,
        expected_status=409,
    )

    assert_labor_ledger(read_route_stop(ctx["stop"]["id"]), 32000)
    assert read_worker(ctx["seller"]["id"])["scheduled_hours_total"] == 16.0
    _rows, meta = validate_paginated(
        api.list_worker_crew_assignments(
            ctx["seller"]["id"], LOT_BOSS, params={"status": "SCHEDULED"}
        )
    )
    assert meta["total_count"] == 2


def test_both_ends_of_one_utc_day_land_in_the_same_slot_bucket(api):
    """PRD §3.5: "The same capacity rule applies to manual scheduling: if the scheduled
    date's UTC day bucket already holds as many inspection orders in `SCHEDULED`, `PASSED`
    or `FAILED` in that jurisdiction as its `inspection_slot_capacity_per_day` allows, the
    request is refused with `ERR_INSPECTION_SLOTS_FULL`."

    PRD §2.11: "Calendar-day buckets are likewise half-open: the UTC day `D` spans
    `[D 00:00:00Z, D+1 00:00:00Z)`. Inspection slot capacity is counted per such bucket,
    and a worker's consecutive-day run is counted over such buckets."

    PRD §3.5: "The new order enters `SCHEDULED` with `defect_count` 0 and
    `result_recorded_at` null, and its `attempt_number` is computed as one more than the
    number of inspection orders already `FAILED` on the same allocation — so a
    re-inspection is a *new* row rather than a reopened one."

    Design: Difficulty/resource_temporal_overlap/inspection_slot_buckets_are_half_open_utc_days_per_jurisdiction
    """
    ctx = _three_reserved_units_in_a_two_slot_state()
    first, second, third = ctx["allocations"]

    opening_order = schedule_inspection(first["id"], "THIRD_PARTY", BUCKET_OPENS)
    assert_inspection_order(opening_order)
    assert opening_order["status"] == "SCHEDULED"
    assert opening_order["attempt_number"] == 1
    assert opening_order["defect_count"] == 0
    assert opening_order["result_recorded_at"] is None
    assert_instant_equals(
        opening_order["scheduled_date"], BUCKET_OPENS, "scheduled_date"
    )

    closing_order = schedule_inspection(second["id"], "THIRD_PARTY", BUCKET_LAST_SECOND)
    assert closing_order["status"] == "SCHEDULED"
    assert closing_order["attempt_number"] == 1
    assert_instant_equals(
        closing_order["scheduled_date"], BUCKET_LAST_SECOND, "scheduled_date"
    )

    for allocation in (first, second, third):
        assert read_allocation(allocation["id"])["status"] == "RESERVED"


def test_the_third_order_waits_for_the_next_days_bucket(api):
    """PRD §3.5: "The same capacity rule applies to manual scheduling: if the scheduled
    date's UTC day bucket already holds as many inspection orders in `SCHEDULED`, `PASSED`
    or `FAILED` in that jurisdiction as its `inspection_slot_capacity_per_day` allows, the
    request is refused with `ERR_INSPECTION_SLOTS_FULL`."

    PRD §2.11: "Calendar-day buckets are likewise half-open: the UTC day `D` spans
    `[D 00:00:00Z, D+1 00:00:00Z)`. Inspection slot capacity is counted per such bucket,
    and a worker's consecutive-day run is counted over such buckets."

    PRD §3.5: "A `SafetyOfficer` may also schedule an inspection by hand, naming a
    `ride_allocation_id`, an `authority` of either `STATE` or `THIRD_PARTY`, and a
    `scheduled_date`."

    Design: Difficulty/resource_temporal_overlap/inspection_slot_buckets_are_half_open_utc_days_per_jurisdiction
    """
    ctx = _three_reserved_units_in_a_two_slot_state()
    first, second, third = ctx["allocations"]
    schedule_inspection(first["id"], "THIRD_PARTY", BUCKET_OPENS)
    schedule_inspection(second["id"], "THIRD_PARTY", BUCKET_LAST_SECOND)

    validate_error(
        api.create_inspection_order(
            create_inspection_order_payload(third["id"], "THIRD_PARTY", BUCKET_MIDDAY),
            SAFETY_OFFICER,
        ),
        ApiErrorId.ERR_INSPECTION_SLOTS_FULL.value,
        expected_status=409,
    )
    assert list_allocation_inspections(third["id"]) == []

    next_bucket = validate_success(
        api.create_inspection_order(
            create_inspection_order_payload(
                third["id"], "THIRD_PARTY", NEXT_BUCKET_OPENS
            ),
            SAFETY_OFFICER,
        ),
        expected_status=201,
    )
    assert next_bucket["status"] == "SCHEDULED"
    assert_instant_equals(
        next_bucket["scheduled_date"], NEXT_BUCKET_OPENS, "scheduled_date"
    )
    assert len(list_allocation_inspections(third["id"])) == 1
