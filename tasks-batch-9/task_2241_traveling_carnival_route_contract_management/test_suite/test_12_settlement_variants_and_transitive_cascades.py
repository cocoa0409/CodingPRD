"""The two settlement variants, the two duty-exposure bases and the long cascades."""

from test_helpers import (
    CHAIR_SWINGS,
    CLOCK_AT_CLOSE,
    CLOCK_START,
    DEFAULT_OPERATOR_SHIFT,
    EVENT_PERMIT_VALID_FROM,
    EVENT_PERMIT_VALID_UNTIL,
    GIANT_WHEEL,
    KIDDIE_CARS,
    KIDDIE_COASTER,
    LOT_BOSS,
    TILT_A_WHIRL,
    ApiErrorId,
    add_route_stop,
    adjudicate_closure,
    approved_permit,
    assert_guarantee_ledger,
    assert_inspection_order,
    assert_instant_equals,
    assert_labor_ledger,
    assert_lot_ledgers,
    assert_readiness,
    assert_settlement,
    assert_settlement_amounts,
    book_crew,
    build_settlement,
    cancel_crew,
    create_crew_assignment_payload,
    execute_contract,
    finalize_settlement,
    list_allocation_inspections,
    log_closure,
    open_route,
    propose_make_good,
    read_allocation,
    read_readiness,
    read_ride,
    read_route,
    read_route_stop,
    read_weather_closure,
    read_worker,
    record_sales,
    register_jurisdiction,
    register_venue,
    register_worker,
    release_allocation,
    respond_make_good,
    set_logical_clock,
    setup_committed_route_with_sent_contract,
    setup_open_lot,
    setup_provisional_settlement_on_struck_lot,
    teardown_lot,
    validate_error,
    validate_paginated,
    validate_success,
)

DUAL_VARIANT_DEAL = {
    "counterparty_name": "Franklin County Agricultural Society",
    "sponsor_name": "Buckeye Beverage",
    "revenue_split_pct_operator": 65,
    "guarantee_cents": 900000,
    "ride_minimum_count": 4,
    "exclusivity": "RIDES",
    "settlement_basis": "GREATER_OF",
}
MIDWAY_RIDES = [
    dict(GIANT_WHEEL, requires_state_inspection=False),
    dict(TILT_A_WHIRL, requires_state_inspection=False),
    dict(KIDDIE_COASTER, requires_state_inspection=False),
    dict(CHAIR_SWINGS, requires_state_inspection=False),
]
FLAT_OPERATORS = [
    {
        "full_name": name,
        "employment_type": "PERMANENT",
        "hourly_rate_cents": 1600,
        "certified_ride_classes": ["FLAT"],
    }
    for name in ("Op One", "Op Two", "Op Three", "Op Four")
]
OPERATOR_SHIFTS = [
    {
        "worker_index": index,
        "crew_role": "RIDE_OPERATOR",
        "shift_start": "2026-09-04T12:00:00Z",
        "shift_end": "2026-09-04T20:00:00Z",
    }
    for index in range(4)
]
FOUR_CHANNEL_SALES = [
    {
        "channel": "WRISTBAND",
        "units": 300,
        "unit_price_cents": 4167,
        "business_date": "2026-09-04T18:00:00Z",
    },
    {
        "channel": "SINGLE",
        "units": 700,
        "unit_price_cents": 1043,
        "business_date": "2026-09-04T19:00:00Z",
    },
    {
        "channel": "PRESALE",
        "units": 501,
        "unit_price_cents": 2100,
        "business_date": "2026-09-04T19:30:00Z",
    },
    {
        "channel": "COMP",
        "units": 40,
        "unit_price_cents": 0,
        "business_date": "2026-09-04T19:45:00Z",
    },
]
CLOCK_MID_RUN = "2026-09-05T18:00:00Z"
KENTUCKY = {
    "state_code": "KY",
    "name": "Kentucky",
    "permit_lead_days": 0,
    "requires_state_ride_inspection": False,
    "inspection_slot_capacity_per_day": 2,
    "amusement_tax_pct": 0,
    "max_consecutive_work_days": 2,
    "housing_permit_required": False,
    "permit_fee_cents": 0,
}
BLUEGRASS_LOT = {
    "name": "Bluegrass Fairground",
    "city": "Lexington",
    "lot_area_sqft": 80000,
    "power_amps_available": 900,
    "expected_attendance": 9001,
    "housing_pads_available": 2,
    "lot_surface": "GRASS",
}
RIGGER_SPEC = {
    "full_name": "Rigger One",
    "employment_type": "PERMANENT",
    "hourly_rate_cents": 2000,
    "certified_ride_classes": [],
}
DAY_ONE_SHIFT = ("2026-09-01T08:00:00Z", "2026-09-01T16:00:00Z")
DAY_TWO_SHIFT = ("2026-09-02T08:00:00Z", "2026-09-02T16:00:00Z")
DAY_THREE_SHIFT = ("2026-09-03T08:00:00Z", "2026-09-03T16:00:00Z")
INSPECTABLE_UNITS = [
    dict(KIDDIE_COASTER, requires_state_inspection=True),
    dict(KIDDIE_CARS, requires_state_inspection=True),
    dict(CHAIR_SWINGS, requires_state_inspection=True),
]
CLOCK_AT_EXECUTION = "2026-08-20T00:00:00Z"
FIRST_SLOT_DAY = "2026-09-01T14:00:00Z"
SECOND_SLOT_DAY = "2026-09-02T14:00:00Z"
CLOSE_OUT_DEAL = {
    "counterparty_name": "Franklin County Agricultural Society",
    "revenue_split_pct_operator": 65,
    "guarantee_cents": 0,
    "ride_minimum_count": 0,
    "exclusivity": "NONE",
    "settlement_basis": "SPLIT_ONLY",
}
FLAT_OPERATOR = {
    "full_name": "Ada Operator",
    "employment_type": "PERMANENT",
    "hourly_rate_cents": 1600,
    "certified_ride_classes": ["FLAT"],
    "housing_required": False,
}


def _midway_with_four_units_and_one_closure():
    """An OPEN four-unit lot with all four channels booked and a WIND closure logged."""
    ctx = setup_open_lot(
        contract_overrides=DUAL_VARIANT_DEAL,
        ride_specs=MIDWAY_RIDES,
        worker_specs=FLAT_OPERATORS,
        crew_specs=OPERATOR_SHIFTS,
        jurisdiction_overrides={
            "requires_state_ride_inspection": False,
            "max_consecutive_work_days": 6,
        },
        venue_overrides={"housing_pads_available": 4},
    )
    ctx["sales"] = record_sales(ctx["stop"]["id"], FOUR_CHANNEL_SALES)
    set_logical_clock(CLOCK_MID_RUN)
    ctx["closure"] = log_closure(
        ctx["stop"]["id"], "WIND", "2026-09-05T14:00:00Z", "2026-09-05T19:00:00Z"
    )
    return ctx


def _bluegrass_lot_with_two_rigging_shifts():
    """A Kentucky lot whose consecutive-day ceiling is two, with two booked days."""
    set_logical_clock(CLOCK_START)
    jurisdiction = register_jurisdiction(**KENTUCKY)
    venue = register_venue(jurisdiction["id"], **BLUEGRASS_LOT)
    route = open_route(name="2026 Bluegrass Loop", home_base_state="KY")
    stop = add_route_stop(route["id"], venue["id"])
    rigger = register_worker(**RIGGER_SPEC)
    first = book_crew(stop["id"], rigger["id"], "SETUP", *DAY_ONE_SHIFT)
    second = book_crew(stop["id"], rigger["id"], "SETUP", *DAY_TWO_SHIFT)
    return stop, rigger, first, second


def test_the_provisional_variant_prorates_the_guarantee_by_elapsed_days(api):
    """PRD §3.8: "The `PROVISIONAL` variant is used when a settlement is created and
    again when a disputed one is reconciled, while the run is still open or being
    struck. It counts rides forward-looking: allocations in `COMMITTED`,
    `INSPECTION_HELD` and `OPERATING` all count toward the ride minimum in step 6.
    In step 7 it pro-rates the guarantee by elapsed operating days: the elapsed day
    count is the whole days from the lot's `open_date` to the earlier of the logical
    clock and the lot's `close_date`, rounded down, plus one, taken as at least one
    day, and then capped at the lot's `operating_days`; `guarantee_effective_cents`
    is the deal's `guarantee_cents` multiplied by that elapsed count divided by
    `operating_days`, rounded half-up to whole cents. And
    `makegood_deduction_cents` is always 0 under this variant — the provisional
    numbers ignore every make-good."

    PRD §3.8: "**Tax, rounded per channel then summed.** For each of the same three
    channels, multiply that channel's gross by the jurisdiction's
    `amusement_tax_pct` divided by 100 and round half-up to whole cents. The
    settlement's `tax_cents` is the sum of the three rounded channel taxes. Summing
    the channels first and rounding once is not used and gives a different answer."

    PRD §3.8: "`effective_operator_pct` is the deal's `revenue_split_pct_operator`
    plus that bonus, capped at 72.5 — whichever is smaller."

    Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_diverge_on_guarantee_basis_and_ride_count
    """
    ctx = _midway_with_four_units_and_one_closure()

    settlement = build_settlement(ctx["contract"]["id"])
    assert_settlement(settlement)
    assert settlement["status"] == "PROVISIONAL"
    assert settlement["variant"] == "PROVISIONAL"
    assert settlement["effective_operator_pct"] == 67.5
    assert_settlement_amounts(
        settlement,
        gross_cents=3032300,
        tax_cents=197101,
        taxable_net_cents=2835199,
        split_share_cents=1913759,
        shortfall_penalty_cents=0,
        guarantee_effective_cents=600000,
        makegood_deduction_cents=0,
        settlement_due_cents=1913759,
    )

    assert read_route_stop(ctx["stop"]["id"])["operating_ride_count"] == 4
    for allocation in ctx["allocations"]:
        assert read_allocation(allocation["id"])["status"] == "OPERATING"


def test_the_final_variant_abates_the_guarantee_and_drops_the_pulled_unit(api):
    """PRD §3.8: "The `FINAL` variant is used only at finalization, once the lot is
    being struck and every closure has been adjudicated. It counts only rides that
    actually operated: allocations in `OPERATING` and `STRUCK` count in step 6,
    which is why a mid-run pull-off can lower the final ride count below what the
    provisional already counted. In step 7 it abates the guarantee by adjudicated
    closure hours instead of pro-rating by elapsed days: the abatement ratio is the
    lot's `closure_hours_adjudicated` divided by its `scheduled_operating_hours`,
    capped at 1; `guarantee_effective_cents` is the deal's `guarantee_cents`
    multiplied by one minus that ratio, rounded half-up to whole cents. And
    `makegood_deduction_cents` is the sum of `amount_cents` over the deal's
    make-good arrangements whose `kind` is `CASH_REFUND` and whose `status` is
    `ACCEPTED`."

    PRD §3.8: "The ride shortfall is the deal's `ride_minimum_count` less that
    count, or zero if the count meets or exceeds the minimum. The raw penalty is the
    shortfall multiplied by 25,000 cents (two hundred and fifty dollars) per missing
    ride. The cap is 10 percent of `split_share_cents`, rounded half-up to whole
    cents. `shortfall_penalty_cents` is whichever of the raw penalty and the cap is
    smaller."

    PRD §3.8: "The base due is `split_share_cents` less `shortfall_penalty_cents`.
    Where the deal's `settlement_basis` is `GREATER_OF`, the due figure is whichever
    is larger of that base due and `guarantee_effective_cents`; where it is
    `SPLIT_ONLY`, the due figure is the base due with no guarantee floor at all.
    `settlement_due_cents` is then that due figure less `makegood_deduction_cents`,
    or zero if the subtraction would go negative — whichever is larger."

    Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_diverge_on_guarantee_basis_and_ride_count
    """
    ctx = _midway_with_four_units_and_one_closure()
    settlement = build_settlement(ctx["contract"]["id"])
    assert settlement["variant"] == "PROVISIONAL"

    adjudicated = adjudicate_closure(ctx["closure"]["id"])
    assert adjudicated["abated_hours"] == 5.0
    assert read_route_stop(ctx["stop"]["id"])["closure_hours_adjudicated"] == 5.0

    refund = propose_make_good(
        ctx["closure"]["id"], ctx["contract"]["id"], "CASH_REFUND"
    )
    assert refund["amount_cents"] == 270000
    assert respond_make_good(refund["id"], "ACCEPT")["status"] == "ACCEPTED"

    pulled = release_allocation(ctx["allocations"][3]["id"])
    assert pulled["status"] == "RELEASED"

    set_logical_clock(CLOCK_AT_CLOSE)
    teardown_lot(ctx["stop"]["id"])

    final = finalize_settlement(settlement["id"])
    assert final["status"] == "FINAL"
    assert final["variant"] == "FINAL"
    assert final["id"] == settlement["id"], "finalization overwrites the same row"
    assert final["effective_operator_pct"] == 67.5
    assert_settlement_amounts(
        final,
        gross_cents=3032300,
        tax_cents=197101,
        taxable_net_cents=2835199,
        split_share_cents=1913759,
        shortfall_penalty_cents=25000,
        guarantee_effective_cents=712500,
        makegood_deduction_cents=270000,
        settlement_due_cents=1618759,
    )
    assert read_weather_closure(ctx["closure"]["id"])["abated_hours"] == 5.0


def test_a_booked_but_unworked_day_still_consumes_the_consecutive_ceiling(api):
    """PRD §3.6: "For the purpose of this gate, the system takes the union of the
    dates covered by all of that worker's assignments whose lot lies in the *same
    jurisdiction* and whose status is `SCHEDULED` or `COMPLETED`, with the candidate
    assignment included in the union, and finds the longest run of consecutive UTC
    dates in that union. If the longest run exceeds the jurisdiction's
    `max_consecutive_work_days`, the booking is refused with
    `ERR_CONSECUTIVE_DAYS_EXCEEDED`. Note that this scheduled basis counts
    booked-but-unworked shifts: a shift on the books consumes a consecutive day
    whether or not it is ever worked."

    PRD §3.6: "An assignment is deemed to cover every UTC calendar date from the
    date of its `shift_start` through the date one second before its `shift_end`,
    inclusive."

    Design: Difficulty/dual_variant_calc/worker_duty_exposure_scheduled_basis_gate_versus_worked_basis_counter
    """
    stop, rigger, first, _second = _bluegrass_lot_with_two_rigging_shifts()

    validate_error(
        api.create_crew_assignment(
            create_crew_assignment_payload(
                stop["id"], rigger["id"], "SETUP", *DAY_THREE_SHIFT
            ),
            LOT_BOSS,
        ),
        ApiErrorId.ERR_CONSECUTIVE_DAYS_EXCEEDED.value,
        expected_status=422,
    )
    assert read_worker(rigger["id"])["scheduled_hours_total"] == 16.0

    released = cancel_crew(first["id"])
    assert released["status"] == "RELEASED"

    reopened = validate_success(
        api.create_crew_assignment(
            create_crew_assignment_payload(
                stop["id"], rigger["id"], "SETUP", *DAY_THREE_SHIFT
            ),
            LOT_BOSS,
        ),
        expected_status=201,
    )
    assert reopened["status"] == "SCHEDULED"
    assert reopened["cost_cents"] == 17600

    _rows, meta = validate_paginated(
        api.list_worker_crew_assignments(
            rigger["id"], LOT_BOSS, params={"status": "SCHEDULED"}
        )
    )
    assert meta["total_count"] == 2, "the released day left the run two days long"


def test_the_worked_basis_counter_ignores_shifts_that_are_only_booked(api):
    """PRD §3.6: "`worked_days_count` uses the **worked** basis rather than the
    scheduled one: it is the number of distinct UTC calendar dates covered by that
    worker's `COMPLETED` assignments across every jurisdiction. Because the worked
    basis counts only completed rows, the same worker with the same history yields a
    shorter run than the scheduled basis whenever a booked shift was released or its
    lot went `DARK`."

    PRD §2.10: "The **labor ledger** of a lot, `labor_cost_provisional_cents`, is
    the sum of `cost_cents` over the lot's crew assignments whose status is
    `SCHEDULED` or `COMPLETED`; its per-worker twin, `scheduled_hours_total`, is the
    sum of `shift_hours` over that worker's assignments in the same two statuses,
    rounded to two decimal places."

    PRD §3.6: "It reverses exactly what the booking added: the worker's
    `scheduled_hours_total` falls by that assignment's `shift_hours` and the lot's
    `labor_cost_provisional_cents` falls by its `cost_cents`, restoring both ledgers
    to their pre-assignment values."

    Design: Difficulty/dual_variant_calc/worker_duty_exposure_scheduled_basis_gate_versus_worked_basis_counter
    """
    stop, rigger, first, second = _bluegrass_lot_with_two_rigging_shifts()
    assert first["cost_cents"] == 17600
    assert second["cost_cents"] == 17600
    assert first["shift_hours"] == 8.0

    booked = read_worker(rigger["id"])
    assert booked["scheduled_hours_total"] == 16.0
    assert booked["worked_days_count"] == 0, (
        "the worked basis admits COMPLETED rows only"
    )
    assert_labor_ledger(read_route_stop(stop["id"]), 35200)

    cancel_crew(first["id"])
    after_cancel = read_worker(rigger["id"])
    assert after_cancel["scheduled_hours_total"] == 8.0
    assert after_cancel["worked_days_count"] == 0
    assert_labor_ledger(read_route_stop(stop["id"]), 17600)

    third = book_crew(stop["id"], rigger["id"], "SETUP", *DAY_THREE_SHIFT)
    assert third["cost_cents"] == 17600
    restored = read_worker(rigger["id"])
    assert restored["scheduled_hours_total"] == 16.0
    assert restored["worked_days_count"] == 0
    assert_labor_ledger(read_route_stop(stop["id"]), 35200)


def _committed_route_with_three_inspectable_units():
    """A COMMITTED route whose PLANNED lot holds three RESERVED inspectable units."""
    ctx = setup_committed_route_with_sent_contract(
        contract_overrides=dict(DUAL_VARIANT_DEAL, ride_minimum_count=3),
        ride_specs=INSPECTABLE_UNITS,
        jurisdiction_overrides={
            "requires_state_ride_inspection": True,
            "inspection_slot_capacity_per_day": 2,
        },
        venue_overrides={"housing_pads_available": 4},
    )
    ctx["event_permit"] = approved_permit(
        ctx["stop"]["id"],
        "EVENT",
        EVENT_PERMIT_VALID_FROM,
        EVENT_PERMIT_VALID_UNTIL,
    )
    return ctx


def test_executing_the_deal_confirms_the_lot_commits_every_unit_and_assigns_the_rides(
    api,
):
    """PRD §3.2: "Execution stamps `executed_at` from the logical clock, adds the deal's
    `guarantee_cents` to the route's `total_guaranteed_cents`, and then cascades. The
    first hop advances the lot `PLANNED → CONFIRMED`. The second hop commits every one
    of that lot's allocations sitting in `RESERVED`, processed oldest-first by
    `created_at`, because each commit may consume a scarce inspection slot. The third
    hop, caused by the second, sets each newly committed allocation's ride to
    `ASSIGNED` and — where the ride requires a state inspection and the lot's
    jurisdiction demands one — creates a single inspection order with `authority` of
    `STATE`, `status` of `SCHEDULED` and `attempt_number` of 1, on a date chosen by
    the slot ladder described in §3.5; where that ladder finds no day with free
    capacity, the allocation is instead moved `COMMITTED → INSPECTION_HELD` and no
    inspection row is written."

    PRD §2.10: "The **footprint ledger** of a lot, `allocated_sqft_used`, is the sum
    of `footprint_charged_sqft` over the lot's allocations whose status is
    `RESERVED`, `COMMITTED`, `INSPECTION_HELD` or `OPERATING`. The **power ledger**,
    `power_amps_used`, is the sum of `power_charged_amps` over that same status set,
    rounded to one decimal place."

    Design: Difficulty/transitive_cascade/contract_execute_cascades_four_hops_to_inspection_slots_and_posture
    """
    ctx = _committed_route_with_three_inspectable_units()
    route_id = ctx["route"]["id"]
    stop_id = ctx["stop"]["id"]

    assert_guarantee_ledger(read_route(route_id), 0)
    assert read_route_stop(stop_id)["status"] == "PLANNED"
    for allocation in ctx["allocations"]:
        assert read_allocation(allocation["id"])["status"] == "RESERVED"
        assert list_allocation_inspections(allocation["id"]) == []

    set_logical_clock(CLOCK_AT_EXECUTION)
    executed = execute_contract(ctx["contract"]["id"])
    assert executed["status"] == "EXECUTED"
    assert_instant_equals(executed["executed_at"], CLOCK_AT_EXECUTION, "executed_at")

    assert_guarantee_ledger(read_route(route_id), 900000)
    struck = read_route_stop(stop_id)
    assert struck["status"] == "CONFIRMED"
    assert_lot_ledgers(struck, 3032, 164.5)

    for allocation, ride in zip(ctx["allocations"], ctx["rides"]):
        assert read_allocation(allocation["id"])["status"] == "COMMITTED"
        assert read_ride(ride["id"])["status"] == "ASSIGNED"


def test_the_commit_waterfall_fills_the_first_day_then_spills_to_the_next(api):
    """PRD §3.5: "The ladder considers the UTC calendar days from the day of the
    lot's `load_in_start` through the day of its `open_date`, inclusive. For each
    such day it counts how many inspection orders in the *same jurisdiction* already
    fall in that day's half-open UTC bucket, counting rows in `SCHEDULED`, `PASSED`
    and `FAILED` alike — a consumed slot is consumed whatever the outcome. A day is a
    candidate when that count is strictly below the jurisdiction's
    `inspection_slot_capacity_per_day`. The ladder picks the **earliest** candidate
    day, and because calendar days are distinct the ranking never ties; the chosen
    day at 14:00:00Z becomes the inspection's `scheduled_date`."

    PRD §3.2: "The third hop, caused by the second, sets each newly committed
    allocation's ride to `ASSIGNED` and — where the ride requires a state inspection
    and the lot's jurisdiction demands one — creates a single inspection order with
    `authority` of `STATE`, `status` of `SCHEDULED` and `attempt_number` of 1, on a
    date chosen by the slot ladder described in §3.5; where that ladder finds no day
    with free capacity, the allocation is instead moved `COMMITTED → INSPECTION_HELD`
    and no inspection row is written."

    PRD §3.7: "If any of the lot's allocations in `RESERVED`, `COMMITTED`,
    `INSPECTION_HELD` or `OPERATING` either is itself `INSPECTION_HELD`, or belongs
    to a ride whose `requires_state_inspection` is true at a lot whose jurisdiction
    sets `requires_state_ride_inspection` and has no inspection order of its own with
    `authority` `STATE`, `status` `PASSED` and a `scheduled_date` at or before the
    lot's `open_date`, then the posture is `INSPECTION_HOLD` and its blocking error
    is `ERR_INSPECTION_NOT_PASSED`."

    Design: Difficulty/transitive_cascade/contract_execute_cascades_four_hops_to_inspection_slots_and_posture
    """
    ctx = _committed_route_with_three_inspectable_units()
    set_logical_clock(CLOCK_AT_EXECUTION)
    execute_contract(ctx["contract"]["id"])

    expected_days = [FIRST_SLOT_DAY, FIRST_SLOT_DAY, SECOND_SLOT_DAY]
    for allocation, expected_day in zip(ctx["allocations"], expected_days):
        orders = list_allocation_inspections(allocation["id"])
        assert len(orders) == 1, "each commit writes exactly one state order"
        order = orders[0]
        assert_inspection_order(order)
        assert order["authority"] == "STATE"
        assert order["status"] == "SCHEDULED"
        assert order["attempt_number"] == 1
        assert_instant_equals(order["scheduled_date"], expected_day, "scheduled_date")

    readiness = read_readiness(ctx["stop"]["id"], LOT_BOSS)
    assert_readiness(readiness)
    assert readiness["compliance_posture"] == "INSPECTION_HOLD"
    assert readiness["blocking_error_id"] == ApiErrorId.ERR_INSPECTION_NOT_PASSED.value
    assert readiness["committed_ride_count"] == 3
    assert readiness["ride_minimum_required"] == 3


def _struck_lot_with_a_provisional_settlement():
    """A TEARDOWN lot on a split-only deal, one booked shift and one sales batch."""
    return setup_provisional_settlement_on_struck_lot(
        contract_overrides=CLOSE_OUT_DEAL,
        ride_specs=[dict(TILT_A_WHIRL, requires_state_inspection=False)],
        worker_specs=[FLAT_OPERATOR],
        crew_specs=[dict(DEFAULT_OPERATOR_SHIFT)],
        jurisdiction_overrides={"requires_state_ride_inspection": False},
    )


def test_finalizing_overwrites_the_money_and_closes_the_lot(api):
    """PRD §3.8: "Finalization re-runs the calculation under the `FINAL` variant,
    overwrites every computed amount on the row, sets `variant` to `FINAL` and stamps
    `finalized_at` from the logical clock."

    PRD §3.8: "It then cascades. The lot advances `TEARDOWN → CLOSED`."

    PRD §3.8: "The base due is `split_share_cents` less `shortfall_penalty_cents`.
    Where the deal's `settlement_basis` is `GREATER_OF`, the due figure is whichever
    is larger of that base due and `guarantee_effective_cents`; where it is
    `SPLIT_ONLY`, the due figure is the base due with no guarantee floor at all."

    Design: Difficulty/transitive_cascade/settlement_finalize_cascades_three_hops_to_crew_worker_and_route_closure
    """
    ctx = _struck_lot_with_a_provisional_settlement()
    stop_id = ctx["stop"]["id"]
    assert read_route_stop(stop_id)["status"] == "TEARDOWN"
    assert ctx["settlement"]["status"] == "PROVISIONAL"

    final = finalize_settlement(ctx["settlement"]["id"])
    assert_settlement(final)
    assert final["status"] == "FINAL"
    assert final["variant"] == "FINAL"
    assert final["effective_operator_pct"] == 65
    assert_instant_equals(final["finalized_at"], CLOCK_AT_CLOSE, "finalized_at")
    assert_settlement_amounts(
        final,
        gross_cents=100000,
        tax_cents=6500,
        taxable_net_cents=93500,
        split_share_cents=60775,
        shortfall_penalty_cents=0,
        guarantee_effective_cents=0,
        makegood_deduction_cents=0,
        settlement_due_cents=60775,
    )

    assert read_route_stop(stop_id)["status"] == "CLOSED"


def test_the_closing_lot_completes_the_crew_and_closes_the_route(api):
    """PRD §3.8: "That closure moves every `SCHEDULED` crew assignment of the lot to
    `COMPLETED`, and each completion recomputes its worker's `worked_days_count` on
    the worked basis. The route's `closed_stop_count` is re-derived, and a route in
    `IN_PROGRESS` whose closed count has caught up with its `stop_count` advances to
    `CLOSED`."

    PRD §3.6: "`worked_days_count` uses the **worked** basis rather than the
    scheduled one: it is the number of distinct UTC calendar dates covered by that
    worker's `COMPLETED` assignments across every jurisdiction."

    PRD §2.10: "The **labor ledger** of a lot, `labor_cost_provisional_cents`, is
    the sum of `cost_cents` over the lot's crew assignments whose status is
    `SCHEDULED` or `COMPLETED`; its per-worker twin, `scheduled_hours_total`, is the
    sum of `shift_hours` over that worker's assignments in the same two statuses,
    rounded to two decimal places."

    Design: Difficulty/transitive_cascade/settlement_finalize_cascades_three_hops_to_crew_worker_and_route_closure
    """
    ctx = _struck_lot_with_a_provisional_settlement()
    stop_id = ctx["stop"]["id"]
    route_id = ctx["route"]["id"]
    worker_id = ctx["workers"][0]["id"]
    assignment_id = ctx["assignments"][0]["id"]

    def roster_row():
        rows, _meta = validate_paginated(
            api.list_route_stop_crew_assignments(stop_id, LOT_BOSS)
        )
        return next(row for row in rows if row["id"] == assignment_id)

    assert roster_row()["status"] == "SCHEDULED"
    before_worker = read_worker(worker_id)
    assert before_worker["worked_days_count"] == 0
    assert before_worker["scheduled_hours_total"] == 8.0
    before_route = read_route(route_id)
    assert before_route["status"] == "IN_PROGRESS"
    assert before_route["closed_stop_count"] == 0
    assert_labor_ledger(read_route_stop(stop_id), 12800)

    finalize_settlement(ctx["settlement"]["id"])

    completed = roster_row()
    assert completed["status"] == "COMPLETED"
    after_worker = read_worker(worker_id)
    assert after_worker["worked_days_count"] == 1
    assert after_worker["scheduled_hours_total"] == 8.0, (
        "a completed shift stays inside the scheduled-hours status set"
    )
    assert_labor_ledger(read_route_stop(stop_id), 12800)

    closed_route = read_route(route_id)
    assert closed_route["closed_stop_count"] == 1
    assert closed_route["stop_count"] == 1
    assert closed_route["status"] == "CLOSED"
