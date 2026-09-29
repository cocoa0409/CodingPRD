"""Which violation is reported when one call breaks two rules at once."""

from test_helpers import (
    CLERK,
    CLOCK_START,
    GIANT_WHEEL,
    LOT_BOSS,
    ApiErrorId,
    add_route_stop,
    assert_instant_equals,
    assert_lot_ledgers,
    assert_permit_application,
    cancel_lot,
    create_permit_application_payload,
    create_ride_allocation_payload,
    current_stop_version,
    file_permit,
    list_allocation_inspections,
    open_route,
    read_allocation,
    read_ride,
    read_route_stop,
    record_inspection_result,
    register_ride,
    register_venue,
    set_logical_clock,
    setup_confirmed_lot,
    setup_planned_lot,
    submit_permit,
    validate_error,
    validate_paginated,
    validate_success,
)

TINY_LOT = {
    "name": "Village Green",
    "city": "Delaware",
    "lot_area_sqft": 5000,
    "power_amps_available": 1200,
    "expected_attendance": 1001,
    "lot_surface": "GRASS",
}
PLAIN_WHEEL = dict(GIANT_WHEEL, requires_state_inspection=False)
INSPECTABLE_WHEEL = dict(GIANT_WHEEL, requires_state_inspection=True)
SPLIT_ONLY_DEAL = {
    "counterparty_name": "Franklin County Agricultural Society",
    "revenue_split_pct_operator": 65,
    "guarantee_cents": 0,
    "ride_minimum_count": 0,
    "exclusivity": "NONE",
    "settlement_basis": "SPLIT_ONLY",
}
SPUR_LOT = {
    "name": "Union County Fairgrounds",
    "city": "Marysville",
    "lot_area_sqft": 200000,
    "power_amps_available": 1000,
    "expected_attendance": 10001,
    "lot_surface": "PAVED",
    "housing_pads_available": 2,
}
SPUR_STOP = {
    "load_in_start": "2026-09-08T14:00:00Z",
    "open_date": "2026-09-11T12:00:00Z",
    "close_date": "2026-09-14T12:00:00Z",
    "teardown_deadline": "2026-09-15T12:00:00Z",
}
OCCUPATION_END = "2026-09-08T12:00:00Z"
EVENT_VALID_FROM = "2026-09-04T00:00:00Z"
EVENT_VALID_UNTIL = "2026-09-08T00:00:00Z"
CLOCK_PAST_THE_DEADLINE = "2026-09-02T00:00:00Z"


def _darkened_tiny_lot():
    """A DARK lot too small for the wheel that is about to be reserved onto it."""
    ctx = setup_planned_lot(venue_overrides=TINY_LOT)
    ctx["ride"] = register_ride(PLAIN_WHEEL)
    ctx["stop"] = cancel_lot(ctx["stop"]["id"])
    return ctx


def _out_of_service_wheel_with_a_second_lot():
    """A wheel failed out of service while its held allocation still occupies a lot."""
    ctx = setup_confirmed_lot(
        contract_overrides=SPLIT_ONLY_DEAL,
        ride_specs=[INSPECTABLE_WHEEL],
        jurisdiction_overrides={
            "requires_state_ride_inspection": True,
            "inspection_slot_capacity_per_day": 2,
        },
        venue_overrides={"housing_pads_available": 4},
    )
    orders = list_allocation_inspections(ctx["allocations"][0]["id"])
    assert len(orders) == 1, "the execution cascade scheduled the state inspection"
    ctx["inspection"] = record_inspection_result(orders[0]["id"], "FAIL", defect_count=3)

    ctx["spur_venue"] = register_venue(ctx["jurisdiction"]["id"], **SPUR_LOT)
    ctx["spur_route"] = open_route(name="2026 Late Fall Spur")
    ctx["spur_stop"] = add_route_stop(
        ctx["spur_route"]["id"], ctx["spur_venue"]["id"], **SPUR_STOP
    )
    return ctx


def _submitted_permit_past_its_deadline():
    """A SUBMITTED event permit whose lot's lead-time window has since closed."""
    ctx = setup_planned_lot()
    permit = file_permit(
        ctx["stop"]["id"], "EVENT", EVENT_VALID_FROM, EVENT_VALID_UNTIL
    )
    ctx["permit"] = submit_permit(permit["id"])
    set_logical_clock(CLOCK_PAST_THE_DEADLINE)
    return ctx


def test_a_darkened_lot_answers_the_state_gate_not_the_footprint_budget(api):
    """PRD §2.7: "A single request can violate many rules at once, and callers must
    be able to rely on *which* violation is reported. The system evaluates checks in a
    fixed global order and returns the first failure it encounters; a check later in
    the order is never allowed to mask an earlier one."

    PRD §2.7: "**Route-stop state** — `ERR_STOP_STATE_INVALID`. The stop must be
    `PLANNED`, `CONFIRMED` or `SETUP` to reserve a ride; `CONFIRMED` to begin setup;
    `SETUP` to open gates; `OPEN` to tear down; `PLANNED`, `CONFIRMED`, `SETUP` or
    `OPEN` to be cancelled; `OPEN` or `TEARDOWN` to record a ticket sale, to log a
    closure, to adjudicate a closure or to create a settlement; `TEARDOWN` to finalize
    a settlement; `PLANNED`, `CONFIRMED` or `SETUP` to submit a permit; `PLANNED` to
    execute a contract; and anything other than `CLOSED` to release an allocation or
    cancel a crew shift."

    PRD §2.7: "**Lot footprint budget** — `ERR_LOT_CAPACITY_EXCEEDED` on ride
    reservation."

    Design: Difficulty/priority_pair_validation_conflict/stop_state_41_beats_lot_capacity_90_on_a_darkened_stop
    """
    ctx = _darkened_tiny_lot()
    assert ctx["stop"]["status"] == "DARK"

    validate_error(
        api.create_ride_allocation(
            create_ride_allocation_payload(
                ctx["ride"]["id"],
                ctx["stop"]["id"],
                current_stop_version(ctx["stop"]["id"]),
            ),
            LOT_BOSS,
        ),
        ApiErrorId.ERR_STOP_STATE_INVALID.value,
        expected_status=409,
    )


def test_the_refused_reservation_leaves_no_row_and_no_charge(api):
    """PRD §2.10: "The **footprint ledger** of a lot, `allocated_sqft_used`, is the
    sum of `footprint_charged_sqft` over the lot's allocations whose status is
    `RESERVED`, `COMMITTED`, `INSPECTION_HELD` or `OPERATING`. The **power ledger**,
    `power_amps_used`, is the sum of `power_charged_amps` over that same status set,
    rounded to one decimal place."

    PRD §3.3: "When the reservation is accepted, both lot ledgers are re-derived over
    the contributing status set and the lot's `version` is incremented."

    Design: Difficulty/priority_pair_validation_conflict/stop_state_41_beats_lot_capacity_90_on_a_darkened_stop
    """
    ctx = _darkened_tiny_lot()
    darkened_version = ctx["stop"]["version"]

    validate_error(
        api.create_ride_allocation(
            create_ride_allocation_payload(
                ctx["ride"]["id"], ctx["stop"]["id"], darkened_version
            ),
            LOT_BOSS,
        ),
        ApiErrorId.ERR_STOP_STATE_INVALID.value,
        expected_status=409,
    )

    _rows, meta = validate_paginated(
        api.list_ride_allocations(LOT_BOSS, params={"ride_id": ctx["ride"]["id"]})
    )
    assert meta["total_count"] == 0

    untouched = read_route_stop(ctx["stop"]["id"])
    assert untouched["status"] == "DARK"
    assert untouched["version"] == darkened_version
    assert_lot_ledgers(untouched, 0, 0.0)
    assert read_ride(ctx["ride"]["id"])["status"] == "AVAILABLE"


def test_three_defects_take_the_unit_out_of_service_and_hold_its_allocation(api):
    """PRD §3.5: "On the **fail** branch — `SCHEDULED → FAILED` — the request must
    carry a `defect_count` of at least 1, and a failure recorded without one is
    refused with `ERR_INVALID_REQUEST`. The supplied count is stored and
    `result_recorded_at` is stamped. The allocation is moved `COMMITTED →
    INSPECTION_HELD`. If the failure recorded three or more defects, the ride itself
    is set `OUT_OF_SERVICE`, which both blocks any further reservation of that unit
    and prevents a later passing inspection from releasing the hold."

    PRD §3.3: "The new allocation enters `RESERVED` with `released_at` null, and its
    occupation interval is fixed at creation: `occupation_start` is copied from the
    lot's `load_in_start` and `occupation_end` from its `teardown_deadline`."

    Design: Difficulty/priority_pair_validation_conflict/ride_out_of_service_60_beats_double_booking_70_for_a_failed_ride
    """
    ctx = _out_of_service_wheel_with_a_second_lot()

    failed = ctx["inspection"]
    assert failed["status"] == "FAILED"
    assert failed["defect_count"] == 3

    assert read_ride(ctx["rides"][0]["id"])["status"] == "OUT_OF_SERVICE"
    held = read_allocation(ctx["allocations"][0]["id"])
    assert held["status"] == "INSPECTION_HELD"
    assert_instant_equals(held["occupation_end"], OCCUPATION_END, "occupation_end")


def test_an_out_of_service_unit_answers_serviceability_not_double_booking(api):
    """PRD §2.7: "**Ride serviceability** — `ERR_RIDE_OUT_OF_SERVICE` when the ride
    being reserved or committed is `OUT_OF_SERVICE`."

    PRD §2.7: "**Ride double-booking** — `ERR_RIDE_DOUBLE_BOOKED` on ride
    reservation."

    PRD §3.3: "A reservation is refused with `ERR_RIDE_DOUBLE_BOOKED` when the same
    ride already holds another allocation in `RESERVED`, `COMMITTED`,
    `INSPECTION_HELD` or `OPERATING` whose occupation interval either overlaps the
    candidate's interval, or is separated from it by less than the required haul gap.
    That required gap is the `travel_hours_from_previous` of whichever of the two stops
    sits later in its haul chain — the one with the greater `sequence_index` — plus a
    four-hour transport buffer."

    Design: Difficulty/priority_pair_validation_conflict/ride_out_of_service_60_beats_double_booking_70_for_a_failed_ride
    """
    ctx = _out_of_service_wheel_with_a_second_lot()
    spur_stop_id = ctx["spur_stop"]["id"]

    validate_error(
        api.create_ride_allocation(
            create_ride_allocation_payload(
                ctx["rides"][0]["id"],
                spur_stop_id,
                current_stop_version(spur_stop_id),
            ),
            LOT_BOSS,
        ),
        ApiErrorId.ERR_RIDE_OUT_OF_SERVICE.value,
        expected_status=409,
    )

    _rows, meta = validate_paginated(
        api.list_ride_allocations(LOT_BOSS, params={"route_stop_id": spur_stop_id})
    )
    assert meta["total_count"] == 0
    assert_lot_ledgers(read_route_stop(spur_stop_id), 0, 0.0)


def test_a_permit_already_submitted_answers_the_state_gate_not_the_lead_time(api):
    """PRD §2.7: "**Other child-resource state** — a permit must be `DRAFT` to submit
    and `SUBMITTED` to decide (`ERR_PERMIT_STATE_INVALID`); an inspection order must be
    `SCHEDULED` to record a result (`ERR_INSPECTION_STATE_INVALID`); a crew assignment
    must be `SCHEDULED` to cancel (`ERR_ASSIGNMENT_STATE_INVALID`); a weather closure
    must be `LOGGED` to adjudicate (`ERR_CLOSURE_STATE_INVALID`); a make-good
    arrangement must be `PROPOSED` to respond to (`ERR_MAKEGOOD_STATE_INVALID`)."

    PRD §2.7: "**Permit lead time** — `ERR_PERMIT_LEAD_TIME_VIOLATION` on permit
    submission."

    PRD §3.4: "Submission stamps `submitted_at` from the logical clock."

    Design: Difficulty/priority_pair_validation_conflict/permit_state_44_beats_lead_time_72_on_a_resubmitted_permit
    """
    ctx = _submitted_permit_past_its_deadline()
    permit = ctx["permit"]
    assert_permit_application(permit)
    assert permit["status"] == "SUBMITTED"
    assert_instant_equals(permit["submitted_at"], CLOCK_START, "submitted_at")

    validate_error(
        api.submit_permit_application(permit["id"], CLERK),
        ApiErrorId.ERR_PERMIT_STATE_INVALID.value,
        expected_status=409,
    )


def test_the_lead_time_rule_still_bites_a_fresh_draft_at_the_same_clock(api):
    """PRD §3.4: "**Submitting** a permit (`DRAFT → SUBMITTED`) is also a
    `ComplianceClerk` action, admitted while the lot is `PLANNED`, `CONFIRMED` or
    `SETUP`, and it is where the lead-time rule bites. The number of whole days from
    the logical clock to the lot's `open_date` — the elapsed seconds divided by one day
    and rounded **down** to a whole number — must be at least the jurisdiction's
    `permit_lead_days`; filing exactly that many whole days ahead is admitted, and
    filing any later is refused with `ERR_PERMIT_LEAD_TIME_VIOLATION`."

    PRD §3.4: "A new permit sits in `DRAFT` with `submitted_at`, `decided_at` and
    `denial_reason` all null."

    Design: Difficulty/priority_pair_validation_conflict/permit_state_44_beats_lead_time_72_on_a_resubmitted_permit
    """
    ctx = _submitted_permit_past_its_deadline()

    validate_error(
        api.submit_permit_application(ctx["permit"]["id"], CLERK),
        ApiErrorId.ERR_PERMIT_STATE_INVALID.value,
        expected_status=409,
    )
    rows, _meta = validate_paginated(
        api.list_route_stop_permit_applications(ctx["stop"]["id"], CLERK)
    )
    unchanged = next(row for row in rows if row["id"] == ctx["permit"]["id"])
    assert unchanged["status"] == "SUBMITTED"
    assert_instant_equals(unchanged["submitted_at"], CLOCK_START, "submitted_at")

    fresh = validate_success(
        api.create_permit_application(
            create_permit_application_payload(
                ctx["stop"]["id"],
                "TRANSPORT",
                EVENT_VALID_FROM,
                EVENT_VALID_UNTIL,
                axles_declared=4,
            ),
            CLERK,
        ),
        expected_status=201,
    )
    assert fresh["status"] == "DRAFT"
    validate_error(
        api.submit_permit_application(fresh["id"], CLERK),
        ApiErrorId.ERR_PERMIT_LEAD_TIME_VIOLATION.value,
        expected_status=422,
    )
