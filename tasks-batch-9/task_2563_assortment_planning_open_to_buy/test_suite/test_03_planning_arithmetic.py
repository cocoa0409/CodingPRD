"""Planning arithmetic: markdown-reserve tiers, the size-curve remainder
waterfall, the seasonal receipt budget, the variance verdict's month set and
proration, and the overlay multiplier chain.

Every expected integer in this module is the figure the PRD's pinned formulas
and pinned rounding produce for the authored inputs; nothing is approximated.
"""
from test_helpers import (
    BUYER_HEADERS,
    PLANNER_HEADERS,
    activate_overlay,
    adopt_item,
    create_overlay,
    get_item,
    get_month,
    get_option_plan,
    get_plan,
    get_size_curve_cells,
    post_actuals,
    propose_item,
    replace_size_curve,
    setup_plan_scenario,
    validate_success,
)

# ─── Shared authored inputs ───────────────────────────

# Four months that share bom 20,000,000, markdown 2,000,000 and eom 22,000,000
# and differ only in planned_sales_cents, so the reserve rate can move for no
# other reason than the tier it lands in.
TIER_PROBE_MONTHS = [
    {
        "month_index": 1,
        "fiscal_month_label": "2027-03",
        "first_receipt_date": "2027-03-05T00:00:00Z",
        "bom_inventory_cents": 20_000_000,
        "planned_sales_cents": 15_996_000,
        "planned_markdown_cents": 2_000_000,
        "planned_eom_cents": 22_000_000,
    },
    {
        "month_index": 2,
        "fiscal_month_label": "2027-04",
        "first_receipt_date": "2027-04-02T00:00:00Z",
        "bom_inventory_cents": 20_000_000,
        "planned_sales_cents": 16_000_000,
        "planned_markdown_cents": 2_000_000,
        "planned_eom_cents": 22_000_000,
    },
    {
        "month_index": 3,
        "fiscal_month_label": "2027-05",
        "first_receipt_date": "2027-05-07T00:00:00Z",
        "bom_inventory_cents": 20_000_000,
        "planned_sales_cents": 33_996_000,
        "planned_markdown_cents": 2_000_000,
        "planned_eom_cents": 22_000_000,
    },
    {
        "month_index": 4,
        "fiscal_month_label": "2027-06",
        "first_receipt_date": "2027-06-04T00:00:00Z",
        "bom_inventory_cents": 20_000_000,
        "planned_sales_cents": 34_000_000,
        "planned_markdown_cents": 2_000_000,
        "planned_eom_cents": 22_000_000,
    },
]

# A balanced two-size curve, enough to make a cell slottable.
TWO_SIZE_CURVE = [
    {"size_label": "S", "size_sort_order": 1, "pct_bps": 4000},
    {"size_label": "L", "size_sort_order": 2, "pct_bps": 6000},
]


def _tier_probe_scenario():
    """An APPROVED plan (planned_margin_bps 5000) whose four months are locked in
    one approval cascade."""
    return setup_plan_scenario(
        plan_overrides={"planned_margin_bps": 5000},
        month_specs=[dict(spec) for spec in TIER_PROBE_MONTHS],
        size_curve=TWO_SIZE_CURVE,
        approve=True,
    )


# ─── Markdown reserve tier boundaries ─────────────────

def test_reserve_rate_deep_tier_just_below_4000_edge(api):
    """PRD §3.4: "Step two selects a reserve rate from the provisional sell-through,
    with every band's lower edge inclusive: below 4000 basis points the rate is 900,
    from 4000 up to but not including 6500 it is 600, from 6500 up to but not
    including 8500 it is 350, and at 8500 or above it is 150."

    PRD §3.4: "Step three writes `markdown_reserve_cents` as the denominator
    multiplied by `reserve_rate_bps` and divided by ten thousand, rounded half up."

    Design: Corner/calculations/reserve_rate_tier_boundaries_across_four_months
    """
    scenario = _tier_probe_scenario()
    month = get_month(scenario["months"][1]["id"])

    assert month["status"] == "LOCKED_PLAN", "the approval cascade must lock month 1"
    assert month["provisional_sell_through_bps"] == 3999, (
        "planned sales 15,996,000 at margin 5000 is 7,998,000 at cost over a "
        "denominator of 20,000,000, so provisional_sell_through_bps is 3999"
    )
    assert month["reserve_rate_bps"] == 900, (
        "3999 bps sits strictly below the 4000 edge, so the deep 900 bps rate applies"
    )
    assert month["markdown_reserve_cents"] == 1_800_000, (
        "markdown_reserve_cents is 20,000,000 * 900 / 10000"
    )
    assert month["otb_planned_cents"] == 13_798_000, (
        "otb_planned_cents is 7,998,000 + 22,000,000 + 2,000,000 + 1,800,000 "
        "- 20,000,000"
    )


def test_reserve_rate_mid_tier_exactly_at_4000_edge(api):
    """PRD §3.4: "Step two selects a reserve rate from the provisional sell-through,
    with every band's lower edge inclusive: below 4000 basis points the rate is 900,
    from 4000 up to but not including 6500 it is 600, from 6500 up to but not
    including 8500 it is 350, and at 8500 or above it is 150."

    PRD §3.4: "`provisional_sell_through_bps` is then ten thousand multiplied by the
    cost of sales, divided by that denominator, rounded half up."

    Design: Corner/calculations/reserve_rate_tier_boundaries_across_four_months
    """
    scenario = _tier_probe_scenario()
    month = get_month(scenario["months"][2]["id"])

    assert month["provisional_sell_through_bps"] == 4000, (
        "planned sales 16,000,000 at margin 5000 is 8,000,000 at cost over "
        "20,000,000, so provisional_sell_through_bps is exactly 4000"
    )
    assert month["reserve_rate_bps"] == 600, (
        "the 4000 edge is inclusive on the lower side of the 600 bps band, so "
        "exactly 4000 reserves 600 and not 900"
    )
    assert month["markdown_reserve_cents"] == 1_200_000, (
        "markdown_reserve_cents is 20,000,000 * 600 / 10000"
    )
    assert month["otb_planned_cents"] == 13_200_000, (
        "otb_planned_cents is 8,000,000 + 22,000,000 + 2,000,000 + 1,200,000 "
        "- 20,000,000"
    )


def test_reserve_rate_light_tier_just_below_8500_edge(api):
    """PRD §3.4: "Step two selects a reserve rate from the provisional sell-through,
    with every band's lower edge inclusive: below 4000 basis points the rate is 900,
    from 4000 up to but not including 6500 it is 600, from 6500 up to but not
    including 8500 it is 350, and at 8500 or above it is 150."

    PRD §3.4: "Under the planned basis, the month's planned cost of sales is its
    `planned_sales_cents` converted to cost by the plan's margin, rounded half up,
    and `otb_planned_cents` is that planned cost of sales plus `planned_eom_cents`
    plus `planned_markdown_cents` plus `markdown_reserve_cents`, less
    `bom_inventory_cents`."

    Design: Corner/calculations/reserve_rate_tier_boundaries_across_four_months
    """
    scenario = _tier_probe_scenario()
    month = get_month(scenario["months"][3]["id"])

    assert month["provisional_sell_through_bps"] == 8499, (
        "planned sales 33,996,000 at margin 5000 is 16,998,000 at cost over "
        "20,000,000, so provisional_sell_through_bps is 8499"
    )
    assert month["reserve_rate_bps"] == 350, (
        "8499 bps sits strictly below the 8500 edge, so the light 350 bps rate applies"
    )
    assert month["markdown_reserve_cents"] == 700_000, (
        "markdown_reserve_cents is 20,000,000 * 350 / 10000"
    )
    assert month["otb_planned_cents"] == 21_698_000, (
        "otb_planned_cents is 16,998,000 + 22,000,000 + 2,000,000 + 700,000 "
        "- 20,000,000"
    )


def test_reserve_rate_min_tier_exactly_at_8500_edge(api):
    """PRD §3.4: "Step two selects a reserve rate from the provisional sell-through,
    with every band's lower edge inclusive: below 4000 basis points the rate is 900,
    from 4000 up to but not including 6500 it is 600, from 6500 up to but not
    including 8500 it is 350, and at 8500 or above it is 150."

    PRD §3.4: "A slow month therefore reserves six times as much for markdowns as a
    fast one."

    Design: Corner/calculations/reserve_rate_tier_boundaries_across_four_months
    """
    scenario = _tier_probe_scenario()
    month = get_month(scenario["months"][4]["id"])

    assert month["provisional_sell_through_bps"] == 8500, (
        "planned sales 34,000,000 at margin 5000 is 17,000,000 at cost over "
        "20,000,000, so provisional_sell_through_bps is exactly 8500"
    )
    assert month["reserve_rate_bps"] == 150, (
        "at 8500 or above the minimum 150 bps rate applies, not the light 350"
    )
    assert month["markdown_reserve_cents"] == 300_000, (
        "markdown_reserve_cents is 20,000,000 * 150 / 10000"
    )
    assert month["otb_planned_cents"] == 21_300_000, (
        "otb_planned_cents is 17,000,000 + 22,000,000 + 2,000,000 + 300,000 "
        "- 20,000,000"
    )


def test_reserve_tiers_leave_posture_fully_open(api):
    """PRD §3.4: "Otherwise the system sums `otb_open_cents` across those months and
    sums `otb_planned_cents` across the same months, and `open_ratio_bps` is ten
    thousand multiplied by the open sum, divided by the planned sum or by 1 if that
    planned sum is smaller than 1, rounded half up."

    PRD §3.4: "At 1500 basis points or above the posture is `OPEN`; at 500 or above
    but below 1500 it is `RESTRICTED`; below 500 it is `FROZEN`."

    Design: Corner/calculations/reserve_rate_tier_boundaries_across_four_months
    """
    scenario = _tier_probe_scenario()
    plan = get_plan(scenario["plan_id"])

    assert plan["open_ratio_bps"] == 10000, (
        "with no commitments each month's otb_open_cents equals its "
        "otb_planned_cents, so the open ratio is exactly 10000"
    )
    assert plan["otb_posture"] == "OPEN", (
        "an open ratio of 10000 is at or above 1500, so the posture is OPEN"
    )
    reserves = [
        get_month(scenario["months"][idx]["id"])["markdown_reserve_cents"]
        for idx in (1, 2, 3, 4)
    ]
    assert reserves == [1_800_000, 1_200_000, 700_000, 300_000], (
        "the four months share every input but planned_sales_cents, so the reserve "
        f"moves only because the tier moved; got {reserves}"
    )


# ─── Size-curve remainder reconciliation, upward ──────

# S 500 / M 525 / L 625 / XL 8350 sums to 10000 bps; against a cell total unit
# target of 276 the per-row rounding lands one unit short, so the reconciliation
# has to run upward.
UPWARD_REMAINDER_CURVE = [
    {"size_label": "S", "size_sort_order": 1, "pct_bps": 500},
    {"size_label": "M", "size_sort_order": 2, "pct_bps": 525},
    {"size_label": "L", "size_sort_order": 3, "pct_bps": 625},
    {"size_label": "XL", "size_sort_order": 4, "pct_bps": 8350},
]


def _cell_with_upward_remainder_curve():
    """An OPEN BETTER cell on a 40-store cluster at sales_index 11500 (depth 6),
    carrying the four-size curve whose per-row rounding under-allocates by one."""
    scenario = setup_plan_scenario(size_curve=[])
    option_plan_id = scenario["option_plan"]["id"]
    replace_size_curve(option_plan_id, UPWARD_REMAINDER_CURVE)
    return option_plan_id


def test_size_curve_raw_units_are_rounded_per_row(api):
    """PRD §3.3: "Then, for each size row, it computes an unrounded demand in
    ten-thousandths of a unit: the exact demand for that size is
    `depth_units_per_option` times `store_count` times the cluster's
    `sales_index_bps` divided by ten thousand times the row's `pct_bps` divided by
    ten thousand; multiplying that exact demand by ten thousand and rounding half up
    to an integer gives the row's `raw_units_x10000`, which is retained on the row
    precisely so the remainder tie-break is auditable."

    PRD §2.3: "Three lists override that default because their domain ordering is
    the one planners read them in: the plan-month list is ordered by `month_index`
    ascending, the size-curve-cell list of an option plan is ordered by
    `size_sort_order` ascending, and the weekly actuals list of a plan month is
    ordered by `week_index` ascending."

    Design: Corner/calculations/size_curve_upward_remainder_waterfall
    """
    option_plan_id = _cell_with_upward_remainder_curve()

    cells = get_size_curve_cells(option_plan_id)
    assert len(cells) == 4, f"the submitted set replaces the curve wholesale; got {cells}"
    assert [c["size_label"] for c in cells] == ["S", "M", "L", "XL"], (
        "the size-curve-cell list is ordered by size_sort_order ascending regardless "
        "of allocated_units magnitude"
    )
    assert [c["raw_units_x10000"] for c in cells] == [138_000, 144_900, 172_500, 2_304_600], (
        "raw_units_x10000 is 6 * 40 * 11500 / 10000 * pct_bps / 10000 * 10000 rounded "
        "half up per row: S 138000, M 144900, L 172500, XL 2304600"
    )


def test_size_curve_upward_remainder_adds_the_unit_to_the_largest_fraction(api):
    """PRD §3.3: "The row's `allocated_units` is then `raw_units_x10000` divided by
    ten thousand and rounded half up to a whole unit."

    PRD §3.3: "Each row's fractional part is the remainder of `raw_units_x10000`
    divided by ten thousand."

    PRD §3.3: "When the difference is positive, rows are visited in descending order
    of fractional part, ties again broken by ascending `size_sort_order`, and one
    unit is added to each row visited."

    Design: Corner/calculations/size_curve_upward_remainder_waterfall
    """
    option_plan_id = _cell_with_upward_remainder_curve()

    cells = get_size_curve_cells(option_plan_id)
    allocated = {c["size_label"]: c["allocated_units"] for c in cells}

    assert allocated["S"] == 15, (
        "per-row rounding gives S 14 (13.8) and the +1 deficit goes to S, whose "
        "fractional part 8000 beats XL 4600, M 4900 and L 2500"
    )
    assert allocated["M"] == 14, "M keeps its rounded 14 (14.49)"
    assert allocated["L"] == 17, "L keeps its rounded 17 (17.25)"
    assert allocated["XL"] == 230, (
        "XL keeps its rounded 230 (230.46) even though it is the largest cell"
    )
    assert sum(allocated.values()) == 276, (
        "the reconciled rows sum to the cell's total unit target 276, which is "
        f"round_half_up(6 * 40 * 11500 / 10000); got {allocated}"
    )
    assert all(c["allocated_units"] > 0 for c in cells), (
        "no row ends the reconciliation at zero allocated_units, so "
        "ERR_SIZE_CURVE_ZERO_CELL does not fire"
    )


# ─── Seasonal receipt budget: turn floor + SEASONAL role ───

SEASONAL_MONTH = {
    "month_index": 1,
    "fiscal_month_label": "2027-05",
    "first_receipt_date": "2027-05-07T00:00:00Z",
    "bom_inventory_cents": 30_000_000,
    "planned_sales_cents": 40_000_000,
    "planned_markdown_cents": 2_500_000,
    "planned_eom_cents": 32_000_000,
}

SEASONAL_GOOD_CELL = {
    "tier": "GOOD",
    "breadth_target": 10,
    "depth_units_per_option": 8,
    "assumed_unit_cost_cents": 1800,
}

EQUAL_QUARTERS_CURVE = [
    {"size_label": "S", "size_sort_order": 1, "pct_bps": 2500},
    {"size_label": "M", "size_sort_order": 2, "pct_bps": 2500},
    {"size_label": "L", "size_sort_order": 3, "pct_bps": 2500},
    {"size_label": "XL", "size_sort_order": 4, "pct_bps": 2500},
]


def _seasonal_turn_floor_scenario():
    """A SEASONAL category under a 900,000,000 department, approved from a plan whose
    planned_turn_x100 150 sits below the turn floor."""
    return setup_plan_scenario(
        department_overrides={
            "name": "Seasonal Home",
            "code": "SHOM",
            "sales_target_cents": 900_000_000,
        },
        category_overrides={
            "name": "Patio",
            "code": "PATI",
            "role": "SEASONAL",
            "sales_share_bps": 2500,
        },
        plan_overrides={"season_code": "SUMMER", "planned_turn_x100": 150},
        month_specs=[dict(SEASONAL_MONTH)],
        option_plan_specs=[dict(SEASONAL_GOOD_CELL)],
        size_curve=EQUAL_QUARTERS_CURVE,
        approve=True,
    )


def test_receipt_budget_clamps_turn_basis_at_the_floor(api):
    """PRD §3.4: "Third, a **turn capacity** is computed against a three-turn
    reference: the turn basis is the greater of the plan's `planned_turn_x100` and a
    floor of 200 (two turns), and the turn capacity is the cost of goods multiplied
    by 300 and divided by that turn basis, rounded half up — so a plan targeting
    fewer than two turns is treated as if it targeted exactly two."

    PRD §3.4: "Finally, `receipt_budget_cents` is the smaller of the department
    ceiling and the larger of the role capacity and the turn capacity."

    Design: Corner/calculations/receipt_budget_turn_floor_and_seasonal_multiplier
    """
    scenario = _seasonal_turn_floor_scenario()
    plan = get_plan(scenario["plan_id"])

    assert plan["status"] == "APPROVED", "the approval must succeed on a positive budget"
    assert plan["receipt_budget_cents"] == 101_250_000, (
        "cost of goods 67,500,000 over a turn basis clamped to 200 gives a turn "
        "capacity of 101,250,000, which beats the SEASONAL role capacity 84,375,000 "
        "and survives the department ceiling 108,000,000; an unclamped turn of 150 "
        "would instead have produced 135,000,000"
    )


def test_receipt_budget_seasonal_role_capacity_loses_the_inner_max(api):
    """PRD §3.4: "Second, a **role capacity** is that cost of goods multiplied by the
    receipt multiplier of the category's `role` and divided by ten thousand, rounded
    half up: a `TRAFFIC_DRIVER` category is allowed 11000 basis points of its cost of
    goods, a `DESTINATION` category 10000, a `CONVENIENCE` category 9000, a
    `SEASONAL` category 12500 and an `OCCASIONAL` category 8500."

    PRD §3.4: "Fourth, a **department ceiling** is the department's
    `sales_target_cents` multiplied by 1200 basis points and divided by ten thousand,
    rounded half up: no single category may claim more than 12% of its department's
    annual sales target as receipts."

    Design: Corner/calculations/receipt_budget_turn_floor_and_seasonal_multiplier
    """
    scenario = _seasonal_turn_floor_scenario()
    plan = get_plan(scenario["plan_id"])

    assert plan["receipt_budget_cents"] != 84_375_000, (
        "the SEASONAL role capacity 67,500,000 * 12500 / 10000 is the largest "
        "multiplier in the table yet still loses the inner max to the turn capacity"
    )
    assert plan["receipt_budget_cents"] != 108_000_000, (
        "the department ceiling 900,000,000 * 1200 / 10000 sits above the inner max, "
        "so the outer min does not bind here"
    )
    assert plan["receipt_budget_cents"] == 101_250_000, (
        "the budget is turn-driven: both other candidates lose"
    )


def test_option_slots_and_unit_target_from_the_turn_driven_budget(api):
    """PRD §3.4: "That tier share is then multiplied by the store cluster's
    `sales_index_bps`, divided by ten thousand and rounded half up again; collapsing
    the two multiplications into a single rounding step is a different and incorrect
    answer."

    PRD §3.4: "`option_slots_total` is then the larger of 2 and the smaller of the
    cell's `breadth_target` and that affordable count — every slotted tier is
    guaranteed a minimum of two options even when the arithmetic funds fewer."

    PRD §3.3: "The rule computes, first, the cell's total unit target for one option
    across the whole cluster: the option plan's `depth_units_per_option` multiplied
    by the cluster's `store_count`, multiplied by the cluster's `sales_index_bps` and
    divided by ten thousand, with the result rounded half up to a whole unit."

    Design: Corner/calculations/receipt_budget_turn_floor_and_seasonal_multiplier
    """
    scenario = _seasonal_turn_floor_scenario()
    cell = get_option_plan(scenario["option_plan"]["id"])

    assert cell["status"] == "SLOTTED", "link 4 slots the OPEN cell that carries a curve"
    assert cell["option_slots_total"] == 10, (
        "tier share 45,562,500 times sales_index 11500 gives 52,396,875 against a "
        "per-option cost of 8 * 40 * 1800 = 576,000, so 90 options are affordable and "
        "breadth_target 10 is the binding limb"
    )
    assert cell["option_slots_open"] == 10, (
        "option_slots_open is option_slots_total less the 0 slots already assigned"
    )
    assert cell["target_units_per_option"] == 368, (
        "target_units_per_option is round_half_up(8 * 40 * 11500 / 10000)"
    )
    cells = get_size_curve_cells(cell["id"])
    assert [c["allocated_units"] for c in cells] == [92, 92, 92, 92], (
        "each of the four equal 2500 bps rows takes exactly a quarter of 368, so "
        "there is no remainder to reconcile"
    )


def test_month_reserve_ignores_the_larger_receipt_budget(api):
    """PRD §3.4: "Under `PLANNED_BASIS` the month's cost of sales is its
    `planned_sales_cents` converted to cost by the plan's margin and rounded half up,
    and the inventory base is the authored `bom_inventory_cents`; under
    `PROJECTED_BASIS` the cost of sales is the projected cost of sales and the
    inventory base is the projected beginning-of-month inventory, both defined in
    §3.7."

    PRD §3.4: "Under the planned basis, the month's planned cost of sales is its
    `planned_sales_cents` converted to cost by the plan's margin, rounded half up,
    and `otb_planned_cents` is that planned cost of sales plus `planned_eom_cents`
    plus `planned_markdown_cents` plus `markdown_reserve_cents`, less
    `bom_inventory_cents`."

    Design: Corner/calculations/receipt_budget_turn_floor_and_seasonal_multiplier
    """
    scenario = _seasonal_turn_floor_scenario()
    month = get_month(scenario["months"][1]["id"])

    assert month["provisional_sell_through_bps"] == 6000, (
        "cost of sales 18,000,000 over the authored bom 30,000,000 is 6000 bps; the "
        "receipt budget plays no part in the month's reserve arithmetic"
    )
    assert month["reserve_rate_bps"] == 600, "6000 bps falls in the 4000-to-6500 band"
    assert month["otb_planned_cents"] == 24_300_000, (
        "otb_planned_cents is 18,000,000 + 32,000,000 + 2,500,000 + 1,800,000 "
        "- 30,000,000"
    )


# ─── Variance verdict: input set and per-month proration ───

def _one_month_selling_scenario():
    """An APPROVED plan whose M1 (planned_sales 30,000,000) sells while M2
    (planned_sales 36,000,000) is left LOCKED_PLAN."""
    return setup_plan_scenario(
        size_curve=TWO_SIZE_CURVE,
        approve=True,
        open_season_month_indexes=(1,),
    )


def test_variance_ignores_the_month_that_never_opened(api):
    """PRD §3.7: "The month set is every plan month of the plan whose `status` is
    `IN_SEASON` or `CLOSED`; months still `DRAFT` or `LOCKED_PLAN` contribute neither
    actuals nor plan, and an `IN_SEASON` month with no posts contributes zero to both
    sides."

    PRD §3.7: "`sales_variance_bps` is then ten thousand multiplied by the difference
    between the actual sales to date and the prorated plan to date, divided by that
    prorated plan to date or by 1 if it is smaller than 1, rounded half up — and since
    rounding is half away from zero, a value of −1166.67 becomes −1167."

    PRD §3.7: "Otherwise, at −400 basis points or below, it is `WATCH`."

    Design: Corner/calculations/variance_input_set_ignores_months_that_never_opened
    """
    scenario = _one_month_selling_scenario()
    post_actuals(
        scenario["months"][1]["id"],
        week_index=1,
        actual_sales_cents=7_000_000,
        actual_receipts_cents=5_000_000,
        actual_units_received=1800,
    )

    plan = get_plan(scenario["plan_id"])
    assert plan["sales_variance_bps"] == -667, (
        "the plan to date is one quarter of M1's 30,000,000 and nothing at all from "
        "M2, so 10000 * (7,000,000 - 7,500,000) / 7,500,000 rounds half away from "
        "zero to -667"
    )
    assert plan["variance_status"] == "WATCH", (
        "-667 bps is at or below -400 but above -1000, so the verdict is WATCH; "
        "admitting M2 on the plan side would have produced a BREACH"
    )


def test_locked_plan_month_stays_outside_the_variance_input_set(api):
    """PRD §3.7: "Which basis governs a month is not a choice: a month whose `status`
    is `DRAFT` or `LOCKED_PLAN`, and a month whose `status` is `IN_SEASON` with no
    actuals posted yet, is on `PLANNED_BASIS`; a month whose `status` is `IN_SEASON`
    with at least one actuals row is on `PROJECTED_BASIS`."

    PRD §3.7: "A `BREACH` verdict has two distinct consequences: it unconditionally
    forces the plan's `otb_posture` to `FROZEN` as the last step of the posture
    computation regardless of how much open budget remains, and, when the plan's
    `status` is `APPROVED` and its `reforecast_round` is still below 3, it drives the
    plan `APPROVED → REFORECAST_OPEN` and opens a reforecast cycle whose
    `trigger_reason` is `VARIANCE_BREACH`."

    Design: Corner/calculations/variance_input_set_ignores_months_that_never_opened
    """
    scenario = _one_month_selling_scenario()
    post_actuals(
        scenario["months"][1]["id"],
        week_index=1,
        actual_sales_cents=7_000_000,
        actual_receipts_cents=5_000_000,
        actual_units_received=1800,
    )

    month_two = get_month(scenario["months"][2]["id"])
    assert month_two["status"] == "LOCKED_PLAN", "M2 was never opened for the season"
    assert month_two["active_basis"] == "PLANNED_BASIS", (
        "a LOCKED_PLAN month is on PLANNED_BASIS, so it holds no actuals at all"
    )

    plan = get_plan(scenario["plan_id"])
    assert plan["status"] == "APPROVED", (
        "the verdict is WATCH rather than BREACH, so the plan stays APPROVED"
    )
    assert plan["reforecast_round"] == 0, (
        "no system-triggered VARIANCE_BREACH cycle opened, so the round counter has "
        "not moved"
    )


def test_otb_summary_reports_the_plan_verdict_and_still_counts_both_months(api):
    """PRD §3.7: "The plan-level summary likewise accepts an optional `basis` and
    rolls the plan's months whose `status` is `LOCKED_PLAN` or `IN_SEASON` — the same
    month set the posture computation uses — into `category_plan_id`, the `basis`
    evaluated, `receipt_budget_cents`, the summed `otb_planned_cents`,
    `otb_committed_cents`, `otb_received_cents` and `otb_open_cents`, plus
    `open_ratio_bps`, `otb_posture`, `variance_status`, `sales_variance_bps` and
    `month_count`, the number of months that contributed."

    Design: Corner/calculations/variance_input_set_ignores_months_that_never_opened
    """
    scenario = _one_month_selling_scenario()
    post_actuals(
        scenario["months"][1]["id"],
        week_index=1,
        actual_sales_cents=7_000_000,
        actual_receipts_cents=5_000_000,
        actual_units_received=1800,
    )

    summary = validate_success(
        api.get_otb_summary(
            scenario["plan_id"], PLANNER_HEADERS, params={"basis": "PROJECTED_BASIS"}
        )
    )
    assert summary["sales_variance_bps"] == -667, (
        "the summary reports the plan's verdict fields rather than recomputing them "
        "from a different month set"
    )
    assert summary["variance_status"] == "WATCH", "the summary echoes the WATCH verdict"
    assert summary["month_count"] == 2, (
        "month_count rolls every LOCKED_PLAN or IN_SEASON month, so the variance "
        "exclusion of M2 is specific to the verdict and not a general read filter"
    )


def _two_months_selling_scenario():
    """An APPROVED plan whose M1 (30,000,000) and M2 (36,000,000) are both selling."""
    return setup_plan_scenario(
        size_curve=TWO_SIZE_CURVE,
        approve=True,
        open_season_month_indexes=(1, 2),
    )


def test_variance_is_reevaluated_against_a_growing_prorated_base(api):
    """PRD §3.7: "For each month in the set, the weeks credited are the count of its
    actuals rows, capped at the four weeks a fiscal month holds, and that month's
    contribution to the plan side is its `planned_sales_cents` multiplied by the weeks
    credited and divided by four, **rounded half up per month before the months are
    summed**."

    PRD §3.7: "Otherwise, at −400 basis points or below, it is `WATCH`. Otherwise, at
    +1500 basis points or above, it is `BREACH` again — running far ahead of plan is as
    much a planning failure as running behind it."

    Design: Corner/calculations/variance_prorates_two_mid_flight_months_before_summing
    """
    scenario = _two_months_selling_scenario()
    month_one = scenario["months"][1]["id"]

    post_actuals(
        month_one, week_index=1, actual_sales_cents=7_000_000,
        actual_receipts_cents=5_000_000, actual_units_received=1800,
    )
    plan = get_plan(scenario["plan_id"])
    assert plan["sales_variance_bps"] == -667, (
        "one week of four credits 7,500,000 of plan against 7,000,000 of actuals"
    )
    assert plan["variance_status"] == "WATCH", "-667 bps is at or below -400"

    post_actuals(
        month_one, week_index=2, actual_sales_cents=7_500_000,
        actual_receipts_cents=4_000_000, actual_units_received=1500,
    )
    plan = get_plan(scenario["plan_id"])
    assert plan["sales_variance_bps"] == -333, (
        "two weeks credit 15,000,000 of plan against 14,500,000 of actuals"
    )
    assert plan["variance_status"] == "ON_PLAN", (
        "the verdict is allowed to improve as the prorated base grows"
    )

    post_actuals(
        month_one, week_index=3, actual_sales_cents=7_200_000,
        actual_receipts_cents=3_000_000, actual_units_received=1100,
    )
    plan = get_plan(scenario["plan_id"])
    assert plan["sales_variance_bps"] == -356, (
        "three weeks credit 22,500,000 of plan against 21,700,000 of actuals"
    )
    assert plan["variance_status"] == "ON_PLAN", "-356 bps is above -400"


def test_variance_prorates_each_mid_flight_month_before_summing(api):
    """PRD §3.7: "For each month in the set, the weeks credited are the count of its
    actuals rows, capped at the four weeks a fiscal month holds, and that month's
    contribution to the plan side is its `planned_sales_cents` multiplied by the weeks
    credited and divided by four, **rounded half up per month before the months are
    summed**."

    PRD §3.7: "A month with three of its four weeks posted therefore contributes
    exactly three quarters of its planned sales; comparing to-date actuals against a
    whole month's plan is explicitly not the rule, and summing the raw prorations and
    rounding once at the end is a different and incorrect answer whenever two months
    are mid-flight simultaneously."

    Design: Corner/calculations/variance_prorates_two_mid_flight_months_before_summing
    """
    scenario = _two_months_selling_scenario()
    month_one = scenario["months"][1]["id"]
    month_two = scenario["months"][2]["id"]

    post_actuals(
        month_one, week_index=1, actual_sales_cents=7_000_000,
        actual_receipts_cents=5_000_000, actual_units_received=1800,
    )
    post_actuals(
        month_one, week_index=2, actual_sales_cents=7_500_000,
        actual_receipts_cents=4_000_000, actual_units_received=1500,
    )
    post_actuals(
        month_one, week_index=3, actual_sales_cents=7_200_000,
        actual_receipts_cents=3_000_000, actual_units_received=1100,
    )
    post_actuals(
        month_two, week_index=1, actual_sales_cents=7_900_000,
        actual_receipts_cents=6_000_000, actual_units_received=2200,
    )

    plan = get_plan(scenario["plan_id"])
    assert plan["sales_variance_bps"] == -603, (
        "the plan side is 22,500,000 (M1, three of four weeks) plus 9,000,000 (M2, one "
        "of four weeks) = 31,500,000 against 29,600,000 of actuals; a single global "
        "week counter cannot produce 31,500,000"
    )
    assert plan["variance_status"] == "WATCH", (
        "-603 bps is at or below -400 and above -1000; comparing 29,600,000 against "
        "both whole plans (66,000,000) would instead have read BREACH"
    )
    assert plan["status"] == "APPROVED", (
        "no post in the sequence reached BREACH, so the plan never left APPROVED"
    )
    assert plan["reforecast_round"] == 0, (
        "no VARIANCE_BREACH cycle opened across the four posts"
    )


# ─── Overlay multiplier chain: per-step rounding, pinned order ───

# The logical clock is parked inside the overlay window 2026-08-05 .. 2026-08-31
# the overlay factory authors, so every activated overlay is applicable.
OVERLAY_CLOCK_UTC = "2026-08-10T00:00:00Z"


def _adopted_new_item_scenario():
    """An APPROVED plan with one ADOPTED NEW item on a BETTER cell for a cluster at
    sales_index 11500."""
    scenario = setup_plan_scenario(
        clock=OVERLAY_CLOCK_UTC,
        size_curve=TWO_SIZE_CURVE,
        approve=True,
    )
    item = propose_item(
        scenario["option_plan"]["id"],
        scenario["vendor"]["id"],
        headers=BUYER_HEADERS,
        sku_code="DR-3001",
        color_code="RED",
        lifecycle_stage="NEW",
        unit_cost_cents=2600,
        retail_price_cents=7900,
        prior_season_sell_through_bps=7100,
    )
    return scenario, adopt_item(item["id"])


def test_new_item_forecast_before_any_overlay_is_active(api):
    """PRD §3.5: "For an item whose stage is `NEW`, the **new-item basis** applies: the
    forecast is the tier benchmark of the item's cell — 6200 basis points for a `GOOD`
    cell, 5500 for `BETTER`, 4300 for `BEST` — multiplied by the cluster's
    `sales_index_bps` and by the item's `effective_overlay_multiplier_bps`, divided by
    one hundred million (that is, each of those two basis-point factors is divided by
    ten thousand), rounded half up, and then capped at 9800 basis points."

    PRD §3.5: "Overlays in `DRAFT`, `EXPIRED` or `SUPERSEDED` never participate."

    Design: Corner/calculations/overlay_chain_rounds_after_each_pinned_step
    """
    scenario, adopted = _adopted_new_item_scenario()

    assert adopted["effective_overlay_multiplier_bps"] == 10000, (
        "with no ACTIVE overlay the chain never leaves its starting value of 10000"
    )
    assert adopted["sell_through_bps"] == 6325, (
        "the BETTER benchmark 5500 times sales_index 11500 times 10000 over one "
        "hundred million is 6325"
    )
    assert adopted["sell_through_basis"] == "NEW_ITEM_BASIS", (
        "a NEW item is forecast on the new-item basis and its "
        "prior_season_sell_through_bps 7100 is ignored"
    )


def test_single_volume_overlay_applies_on_its_own(api):
    """PRD §3.5: "Activation immediately re-resolves the affected assortment: every
    item whose `status` is `ADOPTED` or `IN_SEASON`, and whose cell belongs to both the
    overlay's plan and the overlay's cluster, has its
    `effective_overlay_multiplier_bps` re-resolved and its `sell_through_bps`
    re-forecast, with each affected item's version advancing by 1."

    PRD §3.5: "Starting from 10000, for each of those three dimensions in that order,
    if an applicable overlay of that dimension exists the running value is multiplied
    by that overlay's `unit_multiplier_bps`, divided by ten thousand, and **rounded
    half up before the next dimension is applied**; multiplying all the factors
    together and rounding once at the end is explicitly not the rule."

    Design: Corner/calculations/overlay_chain_rounds_after_each_pinned_step
    """
    scenario, adopted = _adopted_new_item_scenario()
    volume = create_overlay(
        scenario["plan_id"], scenario["store_cluster"]["id"],
        overlay_type="VOLUME", unit_multiplier_bps=11000,
    )
    activate_overlay(volume["id"])

    item = get_item(adopted["id"])
    assert item["effective_overlay_multiplier_bps"] == 11000, (
        "a single applicable overlay is applied whatever its dimension; the pinned "
        "order only decides sequencing"
    )
    assert item["sell_through_bps"] == 6958, (
        "5500 * 11500 * 11000 / 100,000,000 is 6957.5, which rounds half up to 6958"
    )


def test_climate_is_applied_before_volume_regardless_of_creation_order(api):
    """PRD §3.5: "The application order is pinned by dimension and by nothing else —
    not by creation time, not by identifier: `CLIMATE` first, then `DEMOGRAPHIC`, then
    `VOLUME`."

    PRD §3.5: "Starting from 10000, for each of those three dimensions in that order,
    if an applicable overlay of that dimension exists the running value is multiplied
    by that overlay's `unit_multiplier_bps`, divided by ten thousand, and **rounded
    half up before the next dimension is applied**; multiplying all the factors
    together and rounding once at the end is explicitly not the rule."

    Design: Corner/calculations/overlay_chain_rounds_after_each_pinned_step
    """
    scenario, adopted = _adopted_new_item_scenario()
    # Authored and activated VOLUME first on purpose, so creation order is the
    # reverse of the application order.
    volume = create_overlay(
        scenario["plan_id"], scenario["store_cluster"]["id"],
        overlay_type="VOLUME", unit_multiplier_bps=11000,
    )
    climate = create_overlay(
        scenario["plan_id"], scenario["store_cluster"]["id"],
        overlay_type="CLIMATE", unit_multiplier_bps=10500,
    )
    activate_overlay(volume["id"])
    activate_overlay(climate["id"])

    item = get_item(adopted["id"])
    assert item["effective_overlay_multiplier_bps"] == 11550, (
        "the chain restarts from 10000 and walks CLIMATE first (10000 -> 10500) then "
        "VOLUME (10500 -> 11550), not the order the overlays were authored in"
    )
    assert item["sell_through_bps"] == 7305, (
        "5500 * 11500 * 11550 / 100,000,000 is 7305.375, which rounds half up to 7305"
    )


def test_three_dimension_chain_rounds_after_each_pinned_step(api):
    """PRD §3.5: "Starting from 10000, for each of those three dimensions in that
    order, if an applicable overlay of that dimension exists the running value is
    multiplied by that overlay's `unit_multiplier_bps`, divided by ten thousand, and
    **rounded half up before the next dimension is applied**; multiplying all the
    factors together and rounding once at the end is explicitly not the rule."

    PRD §3.5: "The resulting value is then clamped into the range 5000 to 15000 —
    floored at 5000 and ceilinged at 15000 — and stored as
    `effective_overlay_multiplier_bps`."

    PRD §3.5: "For an item whose stage is `NEW`, the **new-item basis** applies: the
    forecast is the tier benchmark of the item's cell — 6200 basis points for a `GOOD`
    cell, 5500 for `BETTER`, 4300 for `BEST` — multiplied by the cluster's
    `sales_index_bps` and by the item's `effective_overlay_multiplier_bps`, divided by
    one hundred million (that is, each of those two basis-point factors is divided by
    ten thousand), rounded half up, and then capped at 9800 basis points."

    Design: Corner/calculations/overlay_chain_rounds_after_each_pinned_step
    """
    scenario, adopted = _adopted_new_item_scenario()
    cluster_id = scenario["store_cluster"]["id"]
    volume = create_overlay(
        scenario["plan_id"], cluster_id,
        overlay_type="VOLUME", unit_multiplier_bps=11000,
    )
    climate = create_overlay(
        scenario["plan_id"], cluster_id,
        overlay_type="CLIMATE", unit_multiplier_bps=10500,
    )
    demographic = create_overlay(
        scenario["plan_id"], cluster_id,
        overlay_type="DEMOGRAPHIC", unit_multiplier_bps=10750,
    )
    activate_overlay(volume["id"])
    activate_overlay(climate["id"])
    activate_overlay(demographic["id"])

    item = get_item(adopted["id"])
    assert item["effective_overlay_multiplier_bps"] == 12417, (
        "the pinned walk is 10000 -> 10500 (CLIMATE) -> round_half_up(11287.5) = 11288 "
        "(DEMOGRAPHIC) -> round_half_up(12416.8) = 12417 (VOLUME); multiplying the "
        "three factors before rounding would have given 12416"
    )
    assert item["sell_through_bps"] == 7854, (
        "5500 * 11500 * 12417 / 100,000,000 is 7853.7525, which rounds half up to "
        "7854; the one-bps drift of 12416 would instead read 7853"
    )
    assert item["sell_through_basis"] == "NEW_ITEM_BASIS", (
        "the forecast basis is still selected by lifecycle_stage alone"
    )
