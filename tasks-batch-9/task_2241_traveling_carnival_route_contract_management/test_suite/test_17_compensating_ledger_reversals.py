"""Undoing a booking or a whole lot has to hand back exactly what it took."""

from test_helpers import (
    CLERK,
    CLOCK_START,
    EVENT_PERMIT_VALID_FROM,
    EVENT_PERMIT_VALID_UNTIL,
    GENERAL_MANAGER,
    GIANT_WHEEL,
    KIDDIE_COASTER,
    LOT_BOSS,
    TILT_A_WHIRL,
    assert_crew_assignment,
    assert_guarantee_ledger,
    assert_instant_equals,
    assert_labor_ledger,
    assert_lot_ledgers,
    assert_permit_application,
    assert_ride_allocation,
    book_crew,
    cancel_crew,
    cancel_lot,
    commit_route,
    draft_contract,
    execute_contract,
    file_permit,
    list_stop_allocations,
    read_allocation,
    read_contract,
    read_ride,
    read_route,
    read_route_stop,
    read_worker,
    register_worker,
    send_contract,
    sequence_route,
    setup_planned_lot,
    setup_planned_lot_with_allocations,
    submit_permit,
    validate_paginated,
)

THREE_UNIT_LOT = [GIANT_WHEEL, TILT_A_WHIRL, KIDDIE_COASTER]
CHARGED_SQFT_TOTAL = 8814
CHARGED_AMPS_TOTAL = 573.0
BARE_SQFT_TOTAL = 6918

SIX_DAY_STATE = {"max_consecutive_work_days": 6}
FOUR_PAD_LOT = {"housing_pads_available": 4}
RIGGER = {
    "full_name": "Dale Rigger",
    "employment_type": "PERMANENT",
    "hourly_rate_cents": 1833,
    "certified_ride_classes": ["MAJOR", "FLAT"],
    "housing_required": False,
}
SETTER = {
    "full_name": "Marta Setzer",
    "employment_type": "SEASONAL_DOMESTIC",
    "hourly_rate_cents": 1750,
    "certified_ride_classes": ["FLAT", "KIDDIE"],
    "housing_required": False,
}
SETUP_SHIFT = ("2026-09-01T06:00:00Z", "2026-09-01T17:15:00Z")
TEARDOWN_SHIFT = ("2026-09-07T18:00:00Z", "2026-09-08T04:30:00Z")
SETUP_SHIFT_HOURS = 11.25
SETUP_SHIFT_COST = 23944
TEARDOWN_SHIFT_HOURS = 10.5
TEARDOWN_SHIFT_COST = 20694
BOTH_SHIFTS_COST = 44638
DRIFTED_TOTAL = 44637

EXCLUSIVE_GUARANTEED_DEAL = {
    "counterparty_name": "Franklin County Agricultural Society",
    "revenue_split_pct_operator": 65,
    "guarantee_cents": 900000,
    "ride_minimum_count": 0,
    "exclusivity": "RIDES",
    "settlement_basis": "GREATER_OF",
}
GUARANTEE_CENTS = 900000


def _planned_lot_carrying_three_reserved_units():
    """A PLANNED lot whose ledgers hold the charged figures of three units."""
    return setup_planned_lot_with_allocations(ride_specs=THREE_UNIT_LOT)


def _lot_with_a_setup_and_a_teardown_shift():
    """Two workers booked once each, at rates whose costs round separately."""
    ctx = setup_planned_lot(
        jurisdiction_overrides=SIX_DAY_STATE, venue_overrides=FOUR_PAD_LOT
    )
    ctx["rigger"] = register_worker(**RIGGER)
    ctx["setter"] = register_worker(**SETTER)
    ctx["setup_shift"] = book_crew(
        ctx["stop"]["id"], ctx["rigger"]["id"], "SETUP", *SETUP_SHIFT
    )
    ctx["teardown_shift"] = book_crew(
        ctx["stop"]["id"], ctx["setter"]["id"], "TEARDOWN", *TEARDOWN_SHIFT
    )
    return ctx


def _executed_deal_on_a_lot_holding_a_submitted_permit():
    """A CONFIRMED lot with a guarantee on the route and an undecided EVENT permit."""
    ctx = setup_planned_lot()
    stop_id = ctx["stop"]["id"]
    ctx["permit"] = submit_permit(
        file_permit(
            stop_id, "EVENT", EVENT_PERMIT_VALID_FROM, EVENT_PERMIT_VALID_UNTIL
        )["id"]
    )
    ctx["route"] = sequence_route(ctx["route"]["id"])
    ctx["contract"] = draft_contract(stop_id, **EXCLUSIVE_GUARANTEED_DEAL)
    send_contract(ctx["contract"]["id"])
    ctx["route"] = commit_route(ctx["route"]["id"])
    ctx["contract"] = execute_contract(ctx["contract"]["id"])
    ctx["stop"] = read_route_stop(stop_id)
    ctx["route"] = read_route(ctx["route"]["id"])
    return ctx


def _permit_row(api, stop_id, permit_id):
    """The single permit of a lot, read back through the lot's permit listing."""
    rows, _meta = validate_paginated(
        api.list_route_stop_permit_applications(stop_id, CLERK)
    )
    return next(row for row in rows if row["id"] == permit_id)


def test_darkening_a_lot_hands_back_every_charged_square_foot_and_amp(api):
    """PRD §3.7: "Beyond the deal, every allocation of the lot in `RESERVED`,
    `COMMITTED`, `INSPECTION_HELD` or `OPERATING` is moved to `RELEASED`, each release
    returning its ride to `AVAILABLE` unless that ride is `OUT_OF_SERVICE` or still holds
    another non-terminal allocation; every `SCHEDULED` crew assignment is moved to
    `RELEASED`, decreasing the worker's `scheduled_hours_total` and the lot's
    `labor_cost_provisional_cents`; every permit in `SUBMITTED` or `APPROVED` is moved to
    `EXPIRED`; a route sitting in `SEQUENCED` reverts to `DRAFT`; and the route's
    `stop_count` and `closed_stop_count` are re-derived."

    PRD §2.8: "When an allocation is released, the lot's footprint and amperage totals
    are reduced by exactly that allocation's charged amounts."

    PRD §3.3: "Release stamps `released_at` from the logical clock and reduces the lot's
    `allocated_sqft_used` by this allocation's `footprint_charged_sqft` and its
    `power_amps_used` by this allocation's `power_charged_amps`."

    Design: Difficulty/compensating_invariant/stop_cancel_reverses_the_lot_footprint_and_power_ledger_to_zero
    """
    ctx = _planned_lot_carrying_three_reserved_units()
    stop_id = ctx["stop"]["id"]
    for allocation in ctx["allocations"]:
        assert_ride_allocation(allocation)
        assert allocation["status"] == "RESERVED"
    assert_lot_ledgers(
        read_route_stop(stop_id), CHARGED_SQFT_TOTAL, CHARGED_AMPS_TOTAL
    )

    darkened = cancel_lot(stop_id)
    assert darkened["status"] == "DARK"

    for allocation in ctx["allocations"]:
        released = read_allocation(allocation["id"])
        assert released["status"] == "RELEASED"
        assert_instant_equals(released["released_at"], CLOCK_START, "released_at")

    reversed_stop = read_route_stop(stop_id)
    assert_lot_ledgers(reversed_stop, 0, 0.0)
    assert reversed_stop["allocated_sqft_used"] != CHARGED_SQFT_TOTAL - BARE_SQFT_TOTAL, (
        "the reversal subtracts the charged footprint, not the bare footprint"
    )


def test_the_released_units_rejoin_the_pool_and_the_route_recounts_its_lots(api):
    """PRD §3.1: "The route's `stop_count` (its non-`DARK` stops) and
    `total_haul_miles` are re-derived."

    PRD §3.7: "The two terminal lot states, `CLOSED` and `DARK`, are both counted by
    the route's `closed_stop_count`. When that count reaches the route's `stop_count` and
    the route holds at least one stop, a route in `IN_PROGRESS` advances `IN_PROGRESS →
    CLOSED`. Reaching `CLOSED` is the end of the route's lifecycle."

    PRD §2.10: "The **footprint ledger** of a lot, `allocated_sqft_used`, is the sum of
    `footprint_charged_sqft` over the lot's allocations whose status is `RESERVED`,
    `COMMITTED`, `INSPECTION_HELD` or `OPERATING`. The **power ledger**,
    `power_amps_used`, is the sum of `power_charged_amps` over that same status set,
    rounded to one decimal place."

    Design: Difficulty/compensating_invariant/stop_cancel_reverses_the_lot_footprint_and_power_ledger_to_zero
    """
    ctx = _planned_lot_carrying_three_reserved_units()
    stop_id = ctx["stop"]["id"]
    for ride in ctx["rides"]:
        assert read_ride(ride["id"])["status"] == "AVAILABLE"

    cancel_lot(stop_id)

    for ride in ctx["rides"]:
        assert read_ride(ride["id"])["status"] == "AVAILABLE"
    rows = list_stop_allocations(stop_id)
    assert len(rows) == 3
    assert all(row["status"] == "RELEASED" for row in rows)

    recounted = read_route(ctx["route"]["id"])
    assert recounted["stop_count"] == 0
    assert recounted["closed_stop_count"] == 1
    assert recounted["status"] == "DRAFT"


def test_cancelling_one_shift_reverses_only_that_workers_hours(api):
    """PRD §3.6: "Cancelling a booked shift (`SCHEDULED → RELEASED`) is a `LotBoss`
    action available while the lot is not `CLOSED`. It reverses exactly what the booking
    added: the worker's `scheduled_hours_total` falls by that assignment's `shift_hours`
    and the lot's `labor_cost_provisional_cents` falls by its `cost_cents`, restoring
    both ledgers to their pre-assignment values."

    PRD §2.10: "The **labor ledger** of a lot, `labor_cost_provisional_cents`, is the
    sum of `cost_cents` over the lot's crew assignments whose status is `SCHEDULED` or
    `COMPLETED`; its per-worker twin, `scheduled_hours_total`, is the sum of
    `shift_hours` over that worker's assignments in the same two statuses, rounded to two
    decimal places."

    PRD §3.6: "Once admitted, the assignment's cost is computed and rounded per
    assignment before it enters any total."

    Design: Difficulty/compensating_invariant/crew_cancel_and_rebook_restores_the_labor_ledger_without_drift
    """
    ctx = _lot_with_a_setup_and_a_teardown_shift()
    stop_id = ctx["stop"]["id"]
    assert_crew_assignment(ctx["setup_shift"])
    assert ctx["setup_shift"]["shift_hours"] == SETUP_SHIFT_HOURS
    assert ctx["setup_shift"]["cost_cents"] == SETUP_SHIFT_COST
    assert ctx["teardown_shift"]["shift_hours"] == TEARDOWN_SHIFT_HOURS
    assert ctx["teardown_shift"]["cost_cents"] == TEARDOWN_SHIFT_COST
    assert_labor_ledger(read_route_stop(stop_id), BOTH_SHIFTS_COST)
    assert read_worker(ctx["rigger"]["id"])["scheduled_hours_total"] == SETUP_SHIFT_HOURS

    released = cancel_crew(ctx["setup_shift"]["id"])
    assert released["status"] == "RELEASED"

    assert_labor_ledger(read_route_stop(stop_id), TEARDOWN_SHIFT_COST)
    assert read_worker(ctx["rigger"]["id"])["scheduled_hours_total"] == 0.0
    assert (
        read_worker(ctx["setter"]["id"])["scheduled_hours_total"]
        == TEARDOWN_SHIFT_HOURS
    ), "the cancel touched only the released worker's hours"


def test_rebooking_the_identical_shift_restores_the_ledger_without_drift(api):
    """PRD §3.6: "The base amount is the straight-time hours multiplied by the worker's
    `hourly_rate_cents` plus the overtime hours multiplied by that same rate at
    time-and-a-half, the whole sum rounded half-up to whole cents. A rigging premium of
    10 percent of that base amount, rounded half-up to whole cents, is added for `SETUP`
    and `TEARDOWN` shifts only, and is zero for `RIDE_OPERATOR` and `TICKETING`."

    PRD §3.6: "The lot's `labor_cost_provisional_cents` and the worker's
    `scheduled_hours_total` are then re-derived over the contributing statuses as
    described in §2.10, and the lot's posture is re-derived."

    PRD §2.8: "When a booked shift is cancelled, the worker's scheduled hours and the
    lot's provisional labor cost are each reduced by exactly the amount that shift
    contributed, restoring both running totals to their pre-assignment values."

    Design: Difficulty/compensating_invariant/crew_cancel_and_rebook_restores_the_labor_ledger_without_drift
    """
    ctx = _lot_with_a_setup_and_a_teardown_shift()
    stop_id = ctx["stop"]["id"]
    cancel_crew(ctx["setup_shift"]["id"])

    rebooked = book_crew(stop_id, ctx["rigger"]["id"], "SETUP", *SETUP_SHIFT)
    assert_crew_assignment(rebooked)
    assert rebooked["id"] != ctx["setup_shift"]["id"], "the released row is not revived"
    assert rebooked["status"] == "SCHEDULED"
    assert rebooked["shift_hours"] == SETUP_SHIFT_HOURS
    assert rebooked["cost_cents"] == SETUP_SHIFT_COST

    restored = read_route_stop(stop_id)
    assert_labor_ledger(restored, BOTH_SHIFTS_COST)
    assert restored["labor_cost_provisional_cents"] != DRIFTED_TOTAL, (
        "each assignment's cost is rounded before it enters the total"
    )
    assert read_worker(ctx["rigger"]["id"])["scheduled_hours_total"] == SETUP_SHIFT_HOURS

    rows, meta = validate_paginated(
        api.list_route_stop_crew_assignments(stop_id, LOT_BOSS)
    )
    assert meta["total_count"] == 3
    assert len([row for row in rows if row["status"] == "RELEASED"]) == 1


def test_darkening_a_confirmed_lot_terminates_the_deal_and_returns_the_guarantee(api):
    """PRD §3.7: "The first hop branches on the deal: a contract in `EXECUTED` is moved
    to `TERMINATED`, while one in `DRAFT`, `SENT` or `COUNTERED` is moved to `VOID`. The
    second hop follows from the first: the `TERMINATED` branch decreases the route's
    `total_guaranteed_cents` by that deal's `guarantee_cents`, whereas the `VOID` branch
    leaves the route total untouched because an unexecuted guarantee was never added to
    it, and leaves `negotiation_round` and every negotiated term exactly as they stood."

    PRD §2.10: "The **guarantee ledger** of a route, `total_guaranteed_cents`, is the
    sum of `guarantee_cents` over the contracts covering that route's stops whose status
    is `EXECUTED`. Executing a deal adds its guarantee; terminating an executed deal
    subtracts it; voiding an unexecuted one changes nothing."

    PRD §2.8: "When an executed deal is terminated because its lot went dark, the
    route's guarantee total is reduced by exactly that deal's guarantee — but a deal that
    was voided before execution never contributed to the total in the first place and
    therefore leaves it untouched."

    Design: Difficulty/compensating_invariant/stop_cancel_reverses_the_route_guarantee_ledger_and_expires_permits
    """
    ctx = _executed_deal_on_a_lot_holding_a_submitted_permit()
    assert ctx["contract"]["status"] == "EXECUTED"
    assert ctx["stop"]["status"] == "CONFIRMED"
    assert_guarantee_ledger(ctx["route"], GUARANTEE_CENTS)
    assert ctx["route"]["stop_count"] == 1
    assert ctx["route"]["closed_stop_count"] == 0

    darkened = cancel_lot(ctx["stop"]["id"], GENERAL_MANAGER)
    assert darkened["status"] == "DARK"

    terminated = read_contract(ctx["contract"]["id"])
    assert terminated["status"] == "TERMINATED"
    assert terminated["guarantee_cents"] == GUARANTEE_CENTS, (
        "the ledger was compensated, the negotiated term was not rewritten"
    )
    assert_guarantee_ledger(read_route(ctx["route"]["id"]), 0)


def test_the_same_cancel_expires_the_submitted_permit_and_leaves_the_route_committed(api):
    """PRD §3.4: "Both an `APPROVED` and a `SUBMITTED` permit are moved to `EXPIRED`
    when the lot goes `DARK`. Each of these transitions re-derives the lot's posture and
    increments the permit's `version`."

    PRD §3.7: "Beyond the deal, every allocation of the lot in `RESERVED`, `COMMITTED`,
    `INSPECTION_HELD` or `OPERATING` is moved to `RELEASED`, each release returning its
    ride to `AVAILABLE` unless that ride is `OUT_OF_SERVICE` or still holds another
    non-terminal allocation; every `SCHEDULED` crew assignment is moved to `RELEASED`,
    decreasing the worker's `scheduled_hours_total` and the lot's
    `labor_cost_provisional_cents`; every permit in `SUBMITTED` or `APPROVED` is moved to
    `EXPIRED`; a route sitting in `SEQUENCED` reverts to `DRAFT`; and the route's
    `stop_count` and `closed_stop_count` are re-derived."

    PRD §3.1: "The route's `stop_count` (its non-`DARK` stops) and `total_haul_miles`
    are re-derived."

    Design: Difficulty/compensating_invariant/stop_cancel_reverses_the_route_guarantee_ledger_and_expires_permits
    """
    ctx = _executed_deal_on_a_lot_holding_a_submitted_permit()
    stop_id = ctx["stop"]["id"]
    standing = _permit_row(api, stop_id, ctx["permit"]["id"])
    assert_permit_application(standing)
    assert standing["status"] == "SUBMITTED"

    cancel_lot(stop_id, GENERAL_MANAGER)

    lapsed = _permit_row(api, stop_id, ctx["permit"]["id"])
    assert lapsed["status"] == "EXPIRED"

    recounted = read_route(ctx["route"]["id"])
    assert recounted["stop_count"] == 0
    assert recounted["closed_stop_count"] == 1
    assert recounted["status"] == "COMMITTED"
