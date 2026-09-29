"""Shift windows, bunkhouse pads, visa authorization and lot exclusivity."""

from test_helpers import (
    CLOCK_START,
    GENERAL_MANAGER,
    LOT_BOSS,
    ApiErrorId,
    add_route_stop,
    assert_crew_assignment,
    assert_instant_equals,
    assert_labor_ledger,
    book_crew,
    commit_route,
    create_crew_assignment_payload,
    draft_contract,
    execute_contract,
    open_route,
    read_contract,
    read_route,
    read_route_stop,
    read_worker,
    register_jurisdiction,
    register_venue,
    register_worker,
    send_contract,
    sequence_route,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

FIRST_WINDOW = {
    "load_in_start": "2026-09-01T06:00:00Z",
    "open_date": "2026-09-04T12:00:00Z",
    "close_date": "2026-09-07T12:00:00Z",
    "teardown_deadline": "2026-09-08T12:00:00Z",
}
OVERLAPPING_WINDOW = {
    "load_in_start": "2026-09-05T06:00:00Z",
    "open_date": "2026-09-06T12:00:00Z",
    "close_date": "2026-09-09T12:00:00Z",
    "teardown_deadline": "2026-09-10T12:00:00Z",
}
DISJOINT_WINDOW = {
    "load_in_start": "2026-09-20T06:00:00Z",
    "open_date": "2026-09-23T12:00:00Z",
    "close_date": "2026-09-26T12:00:00Z",
    "teardown_deadline": "2026-09-27T12:00:00Z",
}


def _planned_lot(venue_overrides=None):
    """One jurisdiction, one lot and one PLANNED lot on a DRAFT route."""
    set_logical_clock(CLOCK_START)
    jurisdiction = register_jurisdiction()
    venue = register_venue(jurisdiction["id"], **(venue_overrides or {}))
    route = open_route()
    stop = add_route_stop(route["id"], venue["id"])
    return route, stop


def _exclusive_pair(second_window):
    """Two committed routes booking the same lot, the first deal executed."""
    set_logical_clock(CLOCK_START)
    jurisdiction = register_jurisdiction()
    venue = register_venue(jurisdiction["id"])

    first_route = open_route()
    first_stop = add_route_stop(first_route["id"], venue["id"], **FIRST_WINDOW)
    first_deal = draft_contract(
        first_stop["id"],
        counterparty_name="Franklin County Ag Society",
        revenue_split_pct_operator=65,
        guarantee_cents=400000,
        exclusivity="FULL",
    )
    sequence_route(first_route["id"])
    send_contract(first_deal["id"])
    commit_route(first_route["id"])
    execute_contract(first_deal["id"])

    second_route = open_route(name="2026 Fall Fairs")
    second_stop = add_route_stop(
        second_route["id"], venue["id"], **second_window
    )
    second_deal = draft_contract(
        second_stop["id"],
        counterparty_name="Delaware Community Days",
        revenue_split_pct_operator=65,
        guarantee_cents=400000,
        exclusivity="FULL",
    )
    sequence_route(second_route["id"])
    send_contract(second_deal["id"])
    commit_route(second_route["id"])

    return {
        "first_route": first_route,
        "first_deal": first_deal,
        "second_route": second_route,
        "second_stop": second_stop,
        "second_deal": second_deal,
    }


def test_a_setup_shift_starting_before_the_load_in_is_refused(api):
    """PRD §3.6: "Then the shift-window rule, which differs by role. `SETUP` and
    `TEARDOWN` shifts may fall anywhere inside the lot's load-in-to-teardown
    span, from `load_in_start` to `teardown_deadline`. `RIDE_OPERATOR` and
    `TICKETING` shifts must lie inside the public operating window, from
    `open_date` to `close_date`. A shift outside the window its role permits is
    refused with `ERR_SHIFT_OUTSIDE_STOP_WINDOW`."

    PRD §2.10: "The **labor ledger** of a lot, `labor_cost_provisional_cents`, is
    the sum of `cost_cents` over the lot's crew assignments whose status is
    `SCHEDULED` or `COMPLETED`; its per-worker twin, `scheduled_hours_total`, is
    the sum of `shift_hours` over that worker's assignments in the same two
    statuses, rounded to two decimal places."

    Design: Corner/validations/a_setup_shift_starting_before_load_in_start_is_rejected
    """
    _route, stop = _planned_lot()
    rigger = register_worker(
        full_name="Rigger One", employment_type="PERMANENT", hourly_rate_cents=2000
    )

    validate_error(
        api.create_crew_assignment(
            create_crew_assignment_payload(
                stop["id"],
                rigger["id"],
                "SETUP",
                "2026-09-01T04:00:00Z",
                "2026-09-01T08:00:00Z",
            ),
            LOT_BOSS,
        ),
        ApiErrorId.ERR_SHIFT_OUTSIDE_STOP_WINDOW.value,
    )

    _rows, meta = validate_paginated(
        api.list_route_stop_crew_assignments(stop["id"], LOT_BOSS)
    )
    assert meta["total_count"] == 0, "the refused booking must not have been written"

    assert read_worker(rigger["id"])["scheduled_hours_total"] == 0
    assert_labor_ledger(read_route_stop(stop["id"]), 0)


def test_a_setup_shift_starting_exactly_at_the_load_in_is_admitted(api):
    """PRD §3.6: "`SETUP` and `TEARDOWN` shifts may fall anywhere inside the
    lot's load-in-to-teardown span, from `load_in_start` to
    `teardown_deadline`."

    PRD §3.6: "The base amount is the straight-time hours multiplied by the
    worker's `hourly_rate_cents` plus the overtime hours multiplied by that same
    rate at time-and-a-half, the whole sum rounded half-up to whole cents. A
    rigging premium of 10 percent of that base amount, rounded half-up to whole
    cents, is added for `SETUP` and `TEARDOWN` shifts only, and is zero for
    `RIDE_OPERATOR` and `TICKETING`. A housing stipend of 3,500 cents
    (thirty-five dollars) per shift is added when the worker's
    `housing_required` is true, and is zero otherwise."

    Design: Corner/validations/a_setup_shift_starting_exactly_at_load_in_start_is_admitted
    """
    _route, stop = _planned_lot()
    rigger = register_worker(
        full_name="Rigger One", employment_type="PERMANENT", hourly_rate_cents=2000
    )

    assignment = validate_success(
        api.create_crew_assignment(
            create_crew_assignment_payload(
                stop["id"],
                rigger["id"],
                "SETUP",
                "2026-09-01T06:00:00Z",
                "2026-09-01T14:00:00Z",
            ),
            LOT_BOSS,
        ),
        expected_status=201,
    )

    assert_crew_assignment(assignment)
    assert assignment["status"] == "SCHEDULED"
    assert assignment["shift_hours"] == 8.0
    assert assignment["cost_cents"] == 17600
    assert assignment["housing_pad_assigned"] is False

    worker = read_worker(rigger["id"])
    assert worker["scheduled_hours_total"] == 8.0
    assert worker["worked_days_count"] == 0

    assert_labor_ledger(read_route_stop(stop["id"]), 17600)


def test_a_second_pad_seeking_worker_exhausts_the_lot_bunkhouse(api):
    """PRD §3.6: "Last comes housing. `housing_pad_assigned` on the assignment is
    set to true exactly when the worker's `housing_required` is true, and such an
    assignment occupies a lot pad for the whole load-in-to-teardown window. If
    the count of the lot's `SCHEDULED` assignments carrying
    `housing_pad_assigned`, including the candidate, would exceed the lot's
    `housing_pads_available`, the booking is refused with
    `ERR_HOUSING_PADS_EXHAUSTED`."

    PRD §3.6: "Back-to-back shifts sharing an endpoint do not intersect and are
    admitted."

    Design: Corner/validations/housing_pads_exhausted_is_an_aggregate_violation
    """
    _route, stop = _planned_lot(venue_overrides={"housing_pads_available": 1})
    first = register_worker(
        full_name="Bunk One",
        employment_type="SEASONAL_DOMESTIC",
        hourly_rate_cents=1800,
        housing_required=True,
    )
    second = register_worker(
        full_name="Bunk Two",
        employment_type="SEASONAL_DOMESTIC",
        hourly_rate_cents=1800,
        housing_required=True,
    )
    housed = book_crew(
        stop["id"],
        first["id"],
        "SETUP",
        "2026-09-01T06:00:00Z",
        "2026-09-01T14:00:00Z",
    )
    assert housed["housing_pad_assigned"] is True
    assert housed["status"] == "SCHEDULED"

    validate_error(
        api.create_crew_assignment(
            create_crew_assignment_payload(
                stop["id"],
                second["id"],
                "SETUP",
                "2026-09-01T14:00:00Z",
                "2026-09-01T22:00:00Z",
            ),
            LOT_BOSS,
        ),
        ApiErrorId.ERR_HOUSING_PADS_EXHAUSTED.value,
    )

    rows, meta = validate_paginated(
        api.list_route_stop_crew_assignments(stop["id"], LOT_BOSS)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == housed["id"]
    assert read_worker(second["id"])["scheduled_hours_total"] == 0


def test_the_visa_gate_only_binds_an_h2b_worker(api):
    """PRD §3.6: "The visa gate comes next: for an `H2B_VISA` worker, the shift's
    `shift_end` may not fall later than `visa_expires_on`, and a shift running
    past the authorization is refused with `ERR_WORKER_VISA_LAPSED`."

    PRD §3.6: "`visa_expires_on` records the instant an H-2B authorization
    lapses; it is required exactly when `employment_type` is `H2B_VISA` and must
    be null otherwise, a mismatch either way being refused with
    `ERR_INVALID_REQUEST`."

    Design: Corner/validations/the_visa_gate_applies_only_to_h2b_visa_workers
    """
    _route, stop = _planned_lot()
    domestic = register_worker(
        full_name="Dom One", employment_type="PERMANENT", hourly_rate_cents=2000
    )
    visa_holder = register_worker(
        full_name="Visa One",
        employment_type="H2B_VISA",
        hourly_rate_cents=2000,
        visa_expires_on="2026-09-01T12:00:00Z",
    )

    admitted = book_crew(
        stop["id"],
        domestic["id"],
        "SETUP",
        "2026-09-01T06:00:00Z",
        "2026-09-01T14:00:00Z",
    )
    assert admitted["status"] == "SCHEDULED"
    assert admitted["cost_cents"] == 17600

    validate_error(
        api.create_crew_assignment(
            create_crew_assignment_payload(
                stop["id"],
                visa_holder["id"],
                "SETUP",
                "2026-09-01T06:00:00Z",
                "2026-09-01T14:00:00Z",
            ),
            LOT_BOSS,
        ),
        ApiErrorId.ERR_WORKER_VISA_LAPSED.value,
    )

    assert read_worker(visa_holder["id"])["scheduled_hours_total"] == 0
    assert read_worker(domestic["id"])["scheduled_hours_total"] == 8.0

    _rows, meta = validate_paginated(
        api.list_route_stop_crew_assignments(stop["id"], LOT_BOSS)
    )
    assert meta["total_count"] == 1


def test_a_second_exclusive_deal_on_an_overlapping_run_is_refused(api):
    """PRD §3.2: "Fourth, exclusivity: if either this deal or another
    already-`EXECUTED` deal on the *same lot* grants `RIDES` or `FULL`
    exclusivity, and the two stops' operating windows from `open_date` to
    `close_date` overlap, the execution is refused with
    `ERR_EXCLUSIVITY_CONFLICT`. A `FOOD` or `NONE` provision on both sides does
    not conflict."

    PRD §2.10: "The **guarantee ledger** of a route, `total_guaranteed_cents`, is
    the sum of `guarantee_cents` over the contracts covering that route's stops
    whose status is `EXECUTED`."

    Design: Corner/validations/a_second_full_exclusive_deal_on_an_overlapping_venue_window_is_rejected
    """
    ctx = _exclusive_pair(OVERLAPPING_WINDOW)

    validate_error(
        api.execute_contract(ctx["second_deal"]["id"], GENERAL_MANAGER),
        ApiErrorId.ERR_EXCLUSIVITY_CONFLICT.value,
    )

    blocked = read_contract(ctx["second_deal"]["id"])
    assert blocked["status"] == "SENT"
    assert blocked["executed_at"] is None

    assert read_route_stop(ctx["second_stop"]["id"])["status"] == "PLANNED"
    assert read_route(ctx["second_route"]["id"])["total_guaranteed_cents"] == 0

    assert read_contract(ctx["first_deal"]["id"])["status"] == "EXECUTED"
    assert read_route(ctx["first_route"]["id"])["total_guaranteed_cents"] == 400000


def test_a_second_exclusive_deal_on_a_disjoint_run_is_admitted(api):
    """PRD §3.2: "Fourth, exclusivity: if either this deal or another
    already-`EXECUTED` deal on the *same lot* grants `RIDES` or `FULL`
    exclusivity, and the two stops' operating windows from `open_date` to
    `close_date` overlap, the execution is refused with
    `ERR_EXCLUSIVITY_CONFLICT`."

    PRD §3.2: "Execution stamps `executed_at` from the logical clock, adds the
    deal's `guarantee_cents` to the route's `total_guaranteed_cents`, and then
    cascades. The first hop advances the lot `PLANNED → CONFIRMED`."

    Design: Corner/validations/a_second_full_exclusive_deal_on_a_disjoint_window_is_admitted
    """
    ctx = _exclusive_pair(DISJOINT_WINDOW)

    executed = validate_success(
        api.execute_contract(ctx["second_deal"]["id"], GENERAL_MANAGER)
    )
    assert executed["status"] == "EXECUTED"
    assert_instant_equals(executed["executed_at"], CLOCK_START, "executed_at")

    assert read_route_stop(ctx["second_stop"]["id"])["status"] == "CONFIRMED"
    assert read_route(ctx["second_route"]["id"])["total_guaranteed_cents"] == 400000

    assert read_contract(ctx["first_deal"]["id"])["status"] == "EXECUTED"
    assert read_route(ctx["first_route"]["id"])["total_guaranteed_cents"] == 400000
