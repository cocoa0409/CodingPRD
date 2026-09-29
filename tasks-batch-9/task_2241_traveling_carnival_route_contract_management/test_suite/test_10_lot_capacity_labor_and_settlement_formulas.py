"""The charge tables, the per-assignment rounding and the pinned settlement order."""

from test_helpers import (
    GIANT_WHEEL,
    KIDDIE_COASTER,
    TILT_A_WHIRL,
    add_route_stop,
    assert_crew_assignment,
    assert_instant_equals,
    assert_labor_ledger,
    assert_lot_ledgers,
    assert_ride_allocation,
    assert_settlement,
    assert_settlement_amounts,
    book_crew,
    build_settlement,
    open_route,
    read_allocation,
    read_route_stop,
    read_worker,
    register_jurisdiction,
    register_venue,
    register_worker,
    setup_open_lot_with_sales,
    setup_planned_lot_with_allocations,
    set_logical_clock,
    CLOCK_START,
)

PLAIN_WHEEL = dict(GIANT_WHEEL, requires_state_inspection=False)
PLAIN_TILT = dict(TILT_A_WHIRL, requires_state_inspection=False)
PLAIN_COASTER = dict(KIDDIE_COASTER, requires_state_inspection=False)
THREE_CLASSES = [PLAIN_WHEEL, PLAIN_TILT, PLAIN_COASTER]

RIGGER_SPEC = {
    "full_name": "Dale Rigger",
    "employment_type": "PERMANENT",
    "hourly_rate_cents": 1833,
    "certified_ride_classes": ["MAJOR", "FLAT"],
    "housing_required": False,
}
TEARDOWN_HAND_SPEC = {
    "full_name": "Marta Setzer",
    "employment_type": "SEASONAL_DOMESTIC",
    "hourly_rate_cents": 1750,
    "certified_ride_classes": ["FLAT", "KIDDIE"],
    "housing_required": False,
}
SETUP_SHIFT = ("2026-09-01T06:00:00Z", "2026-09-01T17:15:00Z")
TEARDOWN_SHIFT = ("2026-09-07T18:00:00Z", "2026-09-08T04:30:00Z")

SPLIT_ONLY_DEAL = {
    "counterparty_name": "Franklin County Agricultural Society",
    "revenue_split_pct_operator": 65,
    "guarantee_cents": 0,
    "ride_minimum_count": 0,
    "exclusivity": "NONE",
    "settlement_basis": "SPLIT_ONLY",
}
SOLO_OPERATOR = {
    "full_name": "Op Solo",
    "employment_type": "PERMANENT",
    "hourly_rate_cents": 1600,
    "certified_ride_classes": ["MAJOR"],
    "housing_required": False,
}
THREE_CHANNEL_SALES = [
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
]


def _two_shifts_on_a_planned_lot():
    """A PLANNED lot carrying one SETUP and one TEARDOWN shift on two workers."""
    set_logical_clock(CLOCK_START)
    jurisdiction = register_jurisdiction()
    venue = register_venue(jurisdiction["id"])
    route = open_route()
    stop = add_route_stop(route["id"], venue["id"])
    rigger = register_worker(**RIGGER_SPEC)
    hand = register_worker(**TEARDOWN_HAND_SPEC)
    setup_shift = book_crew(stop["id"], rigger["id"], "SETUP", *SETUP_SHIFT)
    teardown_shift = book_crew(stop["id"], hand["id"], "TEARDOWN", *TEARDOWN_SHIFT)
    return {
        "stop": stop,
        "rigger": rigger,
        "hand": hand,
        "setup_shift": setup_shift,
        "teardown_shift": teardown_shift,
    }


def _open_lot_with_three_channels():
    """An OPEN lot on a split-only deal carrying three booked channels."""
    return setup_open_lot_with_sales(
        sale_specs=THREE_CHANNEL_SALES,
        contract_overrides=SPLIT_ONLY_DEAL,
        ride_specs=[PLAIN_WHEEL],
        worker_specs=[SOLO_OPERATOR],
        jurisdiction_overrides={"requires_state_ride_inspection": False},
    )


def test_each_ride_class_carries_its_own_spacing_and_startup_surge(api):
    """PRD §3.3: "A ride's **charged footprint**, `footprint_charged_sqft`, is its
    bare `footprint_sqft` multiplied by a spacing multiplier that depends on class —
    1.35 for `MAJOR`, 1.20 for `FLAT` and 1.10 for `KIDDIE` — and rounded **up** to a
    whole square foot. Its **charged amperage**, `power_charged_amps`, is its
    `power_amps` inflated by a startup surge of 25 percent for `MAJOR`, 15 percent
    for `FLAT` and none at all for `KIDDIE`, rounded half-up to one decimal
    place."

    PRD §3.3: "The new allocation enters `RESERVED` with `released_at` null, and its
    occupation interval is fixed at creation: `occupation_start` is copied from the
    lot's `load_in_start` and `occupation_end` from its `teardown_deadline`."

    Design: Difficulty/combinatorial_formula/lot_capacity_charge_combines_class_spacing_surge_and_lot_reserve_constants
    """
    ctx = setup_planned_lot_with_allocations(ride_specs=THREE_CLASSES)
    major, flat, kiddie = ctx["allocations"]

    for allocation in ctx["allocations"]:
        assert_ride_allocation(allocation)
        assert allocation["status"] == "RESERVED"

    assert major["footprint_charged_sqft"] == 5414
    assert major["power_charged_amps"] == 375.0
    assert flat["footprint_charged_sqft"] == 2404
    assert flat["power_charged_amps"] == 138.0
    assert kiddie["footprint_charged_sqft"] == 996
    assert kiddie["power_charged_amps"] == 60.0

    stop = ctx["stop"]
    assert_instant_equals(
        major["occupation_start"], stop["load_in_start"], "occupation_start"
    )
    assert_instant_equals(
        major["occupation_end"], stop["teardown_deadline"], "occupation_end"
    )


def test_the_lot_ledgers_accumulate_every_charged_unit(api):
    """PRD §2.10: "The **footprint ledger** of a lot, `allocated_sqft_used`, is the
    sum of `footprint_charged_sqft` over the lot's allocations whose status is
    `RESERVED`, `COMMITTED`, `INSPECTION_HELD` or `OPERATING`. The **power ledger**,
    `power_amps_used`, is the sum of `power_charged_amps` over that same status set,
    rounded to one decimal place."

    PRD §3.3: "Not all of a fairground can hold rides: the usable area is 80 percent
    of `lot_area_sqft`, rounded **down** to a whole square foot, less a circulation
    reserve of half a square foot per projected attendee — that is,
    `expected_attendance` multiplied by 0.5 and rounded **up** to a whole square
    foot."

    Design: Difficulty/combinatorial_formula/lot_capacity_charge_combines_class_spacing_surge_and_lot_reserve_constants
    """
    ctx = setup_planned_lot_with_allocations(ride_specs=THREE_CLASSES)

    loaded = read_route_stop(ctx["stop"]["id"])
    assert_lot_ledgers(loaded, 8814, 573.0)

    charged = [read_allocation(row["id"]) for row in ctx["allocations"]]
    assert all(row["status"] == "RESERVED" for row in charged)
    assert sum(row["footprint_charged_sqft"] for row in charged) == 8814
    assert sum(row["power_charged_amps"] for row in charged) == 573.0


def test_each_shift_is_rounded_to_whole_cents_on_its_own(api):
    """PRD §3.6: "Once admitted, the assignment's cost is computed and rounded per
    assignment before it enters any total. `shift_hours` is the elapsed time from
    `shift_start` to `shift_end` expressed in hours and rounded half-up to two
    decimals. Of those hours, the straight-time portion is whichever is smaller: the
    shift hours themselves, or the ten-hour overtime threshold; the overtime portion
    is the excess of the shift hours over ten hours, or zero when there is none. The
    base amount is the straight-time hours multiplied by the worker's
    `hourly_rate_cents` plus the overtime hours multiplied by that same rate at
    time-and-a-half, the whole sum rounded half-up to whole cents. A rigging premium
    of 10 percent of that base amount, rounded half-up to whole cents, is added for
    `SETUP` and `TEARDOWN` shifts only, and is zero for `RIDE_OPERATOR` and
    `TICKETING`. A housing stipend of 3,500 cents (thirty-five dollars) per shift is
    added when the worker's `housing_required` is true, and is zero otherwise. The
    assignment's `cost_cents` is the sum of those three components."

    PRD §3.6: "`housing_pad_assigned` on the assignment is set to true exactly when
    the worker's `housing_required` is true, and such an assignment occupies a lot
    pad for the whole load-in-to-teardown window."

    Design: Difficulty/combinatorial_formula/stop_labor_cost_rounds_each_assignment_before_summing_the_lot_total
    """
    ctx = _two_shifts_on_a_planned_lot()

    setup_shift = ctx["setup_shift"]
    assert_crew_assignment(setup_shift)
    assert setup_shift["shift_hours"] == 11.25
    assert setup_shift["cost_cents"] == 23944
    assert setup_shift["housing_pad_assigned"] is False

    teardown_shift = ctx["teardown_shift"]
    assert_crew_assignment(teardown_shift)
    assert teardown_shift["shift_hours"] == 10.5
    assert teardown_shift["cost_cents"] == 20694
    assert teardown_shift["housing_pad_assigned"] is False


def test_the_lot_labor_total_sums_the_already_rounded_shifts(api):
    """PRD §2.10: "The **labor ledger** of a lot, `labor_cost_provisional_cents`, is
    the sum of `cost_cents` over the lot's crew assignments whose status is
    `SCHEDULED` or `COMPLETED`; its per-worker twin, `scheduled_hours_total`, is the
    sum of `shift_hours` over that worker's assignments in the same two statuses,
    rounded to two decimal places."

    PRD §3.6: "Once admitted, the assignment's cost is computed and rounded per
    assignment before it enters any total."

    Design: Difficulty/combinatorial_formula/stop_labor_cost_rounds_each_assignment_before_summing_the_lot_total
    """
    ctx = _two_shifts_on_a_planned_lot()

    stop = read_route_stop(ctx["stop"]["id"])
    assert_labor_ledger(stop, 44638)
    assert stop["labor_cost_provisional_cents"] != 44637, (
        "summing the unrounded products and rounding once is not the rule"
    )

    assert read_worker(ctx["rigger"]["id"])["scheduled_hours_total"] == 11.25
    assert read_worker(ctx["hand"]["id"])["scheduled_hours_total"] == 10.5


def test_the_tax_is_rounded_channel_by_channel_before_it_is_summed(api):
    """PRD §3.8: "**Channel gross.** For each of `WRISTBAND`, `SINGLE` and `PRESALE`
    separately, sum `units` multiplied by `unit_price_cents` over the lot's sales
    batches in that channel. These are exact integers with no rounding. The
    settlement's `gross_cents` is the sum of those three channel figures. `COMP`
    batches enter none of them."

    PRD §3.8: "**Tax, rounded per channel then summed.** For each of the same three
    channels, multiply that channel's gross by the jurisdiction's `amusement_tax_pct`
    divided by 100 and round half-up to whole cents. The settlement's `tax_cents` is
    the sum of the three rounded channel taxes. Summing the channels first and
    rounding once is not used and gives a different answer."

    PRD §3.8: "**Taxable net.** `taxable_net_cents` is `gross_cents` less
    `tax_cents`."

    Design: Difficulty/combinatorial_formula/stop_settlement_pinned_step_order_resolves_tier_penalty_guarantee_cycle
    """
    ctx = _open_lot_with_three_channels()

    settlement = build_settlement(ctx["contract"]["id"])
    assert_settlement(settlement)
    assert settlement["gross_cents"] == 3032300
    assert settlement["tax_cents"] == 197101
    assert settlement["tax_cents"] != 197100, (
        "the summed gross is not the base of a single rounding"
    )
    assert settlement["taxable_net_cents"] == 2835199


def test_the_tier_bonus_then_the_penalty_then_the_guarantee_floor_resolve_in_order(api):
    """PRD §3.8: "**Volume tier on the post-tax net.** The tier bonus is measured
    against the taxable net, with inclusive lower bounds: a net of at least 5,000,000
    cents earns a bonus of 5.0 percentage points; otherwise a net of at least
    2,000,000 cents earns 2.5 percentage points; otherwise the bonus is 0.
    `effective_operator_pct` is the deal's `revenue_split_pct_operator` plus that
    bonus, capped at 72.5 — whichever is smaller."

    PRD §3.8: "**Split share.** `split_share_cents` is `taxable_net_cents`
    multiplied by `effective_operator_pct` divided by 100, rounded half-up to whole
    cents."

    PRD §3.8: "The base due is `split_share_cents` less `shortfall_penalty_cents`.
    Where the deal's `settlement_basis` is `GREATER_OF`, the due figure is whichever
    is larger of that base due and `guarantee_effective_cents`; where it is
    `SPLIT_ONLY`, the due figure is the base due with no guarantee floor at all."

    Design: Difficulty/combinatorial_formula/stop_settlement_pinned_step_order_resolves_tier_penalty_guarantee_cycle
    """
    ctx = _open_lot_with_three_channels()

    settlement = build_settlement(ctx["contract"]["id"])
    assert settlement["status"] == "PROVISIONAL"
    assert settlement["variant"] == "PROVISIONAL"
    assert settlement["effective_operator_pct"] == 67.5
    assert_settlement_amounts(
        settlement,
        taxable_net_cents=2835199,
        split_share_cents=1913759,
        shortfall_penalty_cents=0,
        guarantee_effective_cents=0,
        settlement_due_cents=1913759,
    )
