"""Two money formulas whose composition order decides the answer.

A change order's price delta rounds every line on its own before summing, and an
award's performance-bond rate is keyed on the subtotal rather than on the total
it is itself part of. Both orderings are worth exactly the spread between a
correct implementation and a plausible one.
"""

from test_helpers import (
    ChangeOrderStatus,
    ErrorCode,
    ProgramStatus,
    WeightStatus,
    assert_axle_loads,
    assert_program_ledger,
    assert_unit_money,
    award_unit,
    build_unit_order_payload,
    create_active_program,
    create_plant_bay,
    create_released_specification,
    make_purchasing_officer_headers,
    raise_change_order,
    read_program,
    read_unit,
    schedule_trip,
    setup_awarded_unit,
    validate_error,
)


THREE_LINES = [
    {"description": "Compartment shelving", "quantity": 3,
     "unit_cost_cents": 133_333, "markup_pct": 12.5, "is_taxable": True},
    {"description": "LED scene lights", "quantity": 7,
     "unit_cost_cents": 45_555, "markup_pct": 7.5, "is_taxable": False},
    {"description": "Foam proportioner", "quantity": 1,
     "unit_cost_cents": 1_250_005, "markup_pct": 22.0, "is_taxable": True},
]

PUMP_CLAUSE = [
    {"clause_code": "C1", "category": "PUMP",
     "requirement_text": "1500 gpm single stage pump",
     "mandatory": True, "is_restrictive": False},
]

AERIAL_CLAUSE = [
    {"clause_code": "C1", "category": "AERIAL",
     "requirement_text": "100 ft rear-mount aerial ladder",
     "mandatory": True, "is_restrictive": False},
]

AERIAL_UNIT = {
    "unit_type": "AERIAL",
    "gvwr_kg": 27_000,
    "front_axle_rating_kg": 11_000,
    "rear_axle_rating_kg": 16_500,
    "base_curb_front_kg": 9_800,
    "base_curb_rear_kg": 14_440,
    "crew_seat_count": 3,
}


def _three_line_change_order(api):
    """One SPEC_LOCKED pumper, a scheduled trip, and the three-line amendment."""
    ctx = setup_awarded_unit(
        api,
        program_overrides={"name": "Metro FD 2024-2029 Apparatus",
                           "agency_name": "Metro Fire District",
                           "max_option_units": 3},
        clauses=PUMP_CLAUSE,
    )
    bay = create_plant_bay(api, name="Bay A", max_concurrent_visitors=10)
    trip = schedule_trip(api, ctx["unit_id"], bay["id"],
                         trip_type="PRE_CONSTRUCTION",
                         scheduled_start="2026-08-10T08:00:00Z",
                         scheduled_end="2026-08-10T16:00:00Z", committee_size=4)
    ctx["trip_id"] = trip["id"]
    ctx["change_order"] = raise_change_order(
        api, ctx["unit_id"], trip["id"], ctx["program_id"],
        line_items=THREE_LINES,
    )
    return ctx


def _bond_boundary_program(api):
    """A program whose 2026 award lands the subtotal exactly on the tier-1 ceiling."""
    program = create_active_program(api, name="Boundary Bond Program",
                                    agency_name="Harbor Fire Authority",
                                    base_year=2026,
                                    base_unit_price_cents=50_000_000,
                                    max_option_units=2)
    spec = create_released_specification(api, program["id"],
                                        clauses=AERIAL_CLAUSE,
                                        title="Aerial spec rev A")
    return {"program": program, "specification_id": spec["specification_id"]}


def test_each_change_order_line_is_rounded_on_its_own_before_the_lines_are_summed(
        api, admin_headers):
    """Three lines price to 2,446,181 cents, one cent below the naive path.

    PRD 3.8: "`price_delta_cents` is computed when the change order is raised and
    recomputed on every revision, and the rounding order is pinned: each line
    item is rounded on its own and the rounded line values are then summed.
    Summing unrounded line values and rounding once at the end produces a
    different figure and is wrong."
    PRD 3.8: "a change order with three lines — three units at 133,333 cents with
    12.5 percent markup and taxable; seven units at 45,555 cents with 7.5 percent
    markup and not taxable; one unit at 1,250,005 cents with 22.0 percent markup
    and taxable — yields line values of 479,249, 342,801 and 1,624,131 cents, for
    a `price_delta_cents` of 2,446,181. Summing before rounding would have
    produced 2,446,182, one cent high."

    Design: Difficulty/combinatorial_formula/change_order_per_line_rounding_beats_sum_then_round
    """
    ctx = _three_line_change_order(api)
    change_order = ctx["change_order"]

    assert change_order["price_delta_cents"] == 2_446_181, change_order
    assert change_order["price_delta_cents"] != 2_446_182, change_order
    assert change_order["status"] == ChangeOrderStatus.DRAFT.value, change_order
    assert change_order["revision_count"] == 0, change_order
    assert change_order["approved_by_user_id"] is None, change_order
    assert change_order["applied_at"] is None, change_order


def test_a_draft_change_order_is_open_but_commits_nothing(api, admin_headers):
    """The amendment counts as open work while contributing no money anywhere.

    PRD 3.8: "Raising it increases the unit's `open_change_order_count` by one and
    increments the unit's `version`".
    PRD 3.8: "The unit's `change_order_total_cents` is rebuilt as the sum of the
    `price_delta_cents` of every change order of that unit whose `status` is
    `APPROVED` — an empty set giving 0".
    PRD 2.10: "Contributing to the sum are the award price and the accumulated
    approved change-order value of every unit order of the program".

    Design: Difficulty/combinatorial_formula/change_order_per_line_rounding_beats_sum_then_round
    """
    ctx = _three_line_change_order(api)

    unit = read_unit(api, ctx["unit_id"])
    assert_unit_money(unit, price_cents=68_276_000, change_order_total_cents=0,
                      open_change_order_count=1)
    assert unit["version"] == ctx["unit"]["version"] + 1, unit

    assert_program_ledger(read_program(api, ctx["program_id"]), 68_276_000,
                          ProgramStatus.ACTIVE.value, None)


def test_the_bond_tier_is_keyed_on_the_subtotal_and_not_on_the_finished_total(api,
                                                                            admin_headers):
    """A subtotal exactly on the tier-1 ceiling stays in tier 1.

    PRD 3.5: "a subtotal of at most 50,000,000 cents (500,000 dollars) takes the
    first-tier rate of 1.25 percent; a subtotal above that but at most 90,000,000
    cents (900,000 dollars) takes the second-tier rate of 1.00 percent... Both
    tier boundaries are inclusive of the ceiling value."
    PRD 3.5: "a unit whose subtotal is exactly 50,000,000 cents takes the
    first-tier rate of 1.25 percent for a fee of 625,000 cents and a price of
    50,625,000 cents, whereas keying the tier on the finished total would have
    selected the second tier and produced 50,500,000 — a divergence of 125,000
    cents."

    Design: Difficulty/combinatorial_formula/performance_bond_tier_keyed_on_subtotal_not_total
    """
    ctx = _bond_boundary_program(api)

    on_the_line = award_unit(api, ctx["program"]["id"], ctx["specification_id"],
                             award_year=2026, **AERIAL_UNIT)
    assert_unit_money(on_the_line, price_cents=50_625_000)
    assert on_the_line["price_cents"] != 50_500_000, on_the_line

    over_the_line = award_unit(api, ctx["program"]["id"], ctx["specification_id"],
                               award_year=2027, **AERIAL_UNIT)
    assert_unit_money(over_the_line, price_cents=52_520_000)


def test_the_award_weight_model_and_the_escalation_window_bound_the_same_program(
        api, admin_headers):
    """The tier-1 unit's axle loads, the ledger sum and the year-window refusal.

    PRD 3.5: "The front share is one quarter of the payload, quantised to a whole
    kilogram with round-half-up, but capped at 450 kilograms — whichever of the
    two is smaller. The rear share is the whole payload minus the front share, so
    nothing is lost in the split."
    PRD 3.5: "The `award_year` must also fall within the escalation window: not
    earlier than the program's `base_year` and not later than that base year plus
    five, or the award is refused with `ERR_ESCALATION_YEAR_OUT_OF_RANGE`."

    Design: Difficulty/combinatorial_formula/performance_bond_tier_keyed_on_subtotal_not_total
    """
    ctx = _bond_boundary_program(api)
    first = award_unit(api, ctx["program"]["id"], ctx["specification_id"],
                       award_year=2026, **AERIAL_UNIT)
    award_unit(api, ctx["program"]["id"], ctx["specification_id"],
               award_year=2027, **AERIAL_UNIT)

    assert_axle_loads(first, front_kg=10_410, rear_kg=15_870, gross_kg=26_280,
                      weight_status=WeightStatus.WITHIN_LIMITS.value)
    assert_program_ledger(read_program(api, ctx["program"]["id"]), 103_145_000,
                          ProgramStatus.ACTIVE.value, None)

    validate_error(
        api.create_unit_order(
            build_unit_order_payload(ctx["program"]["id"], ctx["specification_id"],
                                     award_year=2032, **AERIAL_UNIT),
            make_purchasing_officer_headers("po-releaser"),
        ),
        ErrorCode.ERR_ESCALATION_YEAR_OUT_OF_RANGE,
        422,
    )
    assert_program_ledger(read_program(api, ctx["program"]["id"]), 103_145_000,
                          ProgramStatus.ACTIVE.value, None)
