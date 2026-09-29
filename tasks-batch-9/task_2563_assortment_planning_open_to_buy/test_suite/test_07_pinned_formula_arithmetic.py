"""Pinned multi-input formulas: the receipt budget, the size allocation and the reserve.

Each test translates one instance of the difficulty rule ``combinatorial_formula``.
"""
from test_helpers import (
    CANONICAL_RECEIPT_BUDGET_CENTS,
    commit_commitment,
    get_month,
    get_option_plan,
    get_plan,
    get_size_curve_cells,
    post_actuals,
    propose_commitment,
    propose_item,
    setup_canonical_approved_plan,
    setup_in_season_plan,
    setup_plan_scenario,
)

# The plan-B shape: a bigger department, a SEASONAL category and a sub-two-turn plan.
PLAN_B_DEPARTMENT = {
    "name": "Home Textiles", "code": "HOME", "fiscal_year": 2027,
    "sales_target_cents": 900_000_000, "margin_target_bps": 5200,
    "turn_target_x100": 150,
}
PLAN_B_CATEGORY = {"name": "Bedding", "code": "BEDD", "role": "SEASONAL",
                   "sales_share_bps": 4000}
PLAN_B_PLAN = {"season_code": "SPRING", "fiscal_year": 2027,
               "planned_sales_cents": 150_000_000, "planned_margin_bps": 5500,
               "planned_turn_x100": 150}
PLAN_B_MONTH = {"month_index": 1, "fiscal_month_label": "2027-03",
                "first_receipt_date": "2027-03-05T00:00:00Z",
                "bom_inventory_cents": 30_000_000, "planned_sales_cents": 40_000_000,
                "planned_markdown_cents": 2_500_000, "planned_eom_cents": 32_000_000}
PLAN_B_OPTION_PLAN = {"tier": "GOOD", "breadth_target": 10, "depth_units_per_option": 8,
                      "assumed_unit_cost_cents": 1800}
PLAN_B_CURVE = [
    {"size_label": "S", "size_sort_order": 1, "pct_bps": 2500},
    {"size_label": "M", "size_sort_order": 2, "pct_bps": 2500},
    {"size_label": "L", "size_sort_order": 3, "pct_bps": 2500},
    {"size_label": "XL", "size_sort_order": 4, "pct_bps": 2500},
]


def test_receipt_budget_department_ceiling_binds_the_outer_minimum():
    """On the canonical DESTINATION plan the department's hard ceiling wins.

    PRD: "`receipt_budget_cents` is the smaller of the department ceiling and the larger
    of the role capacity and the turn capacity." Cost of goods is 67_500_000; a
    `DESTINATION` category is allowed "10000" basis points of it, so role capacity is
    67_500_000; the turn capacity is "the cost of goods multiplied by 300 and divided by
    that turn basis" == 63_281_250; the department ceiling is 500_000_000 x 1200 / 10000
    == 60_000_000. The outer minimum therefore binds at 60_000_000 even though
    merchandising appetite offered 67_500_000.

    Design: Difficulty/combinatorial_formula/receipt_budget_nested_min_max_department_cap
    """
    scenario = setup_canonical_approved_plan()

    plan = get_plan(scenario["plan_id"])
    assert plan["status"] == "APPROVED"
    assert plan["receipt_budget_cents"] == 60_000_000
    assert plan["receipt_budget_cents"] == CANONICAL_RECEIPT_BUDGET_CENTS
    assert plan["receipt_budget_cents"] != 67_500_000
    assert get_month(scenario["m1"]["id"])["otb_planned_cents"] == 18_200_000
    assert get_option_plan(scenario["option_plan"]["id"])["option_slots_total"] == 14


def test_receipt_budget_inner_maximum_picks_turn_capacity_against_the_two_turn_floor():
    """A sub-two-turn SEASONAL plan is funded by turn capacity under a loose ceiling.

    PRD: "the turn basis is the greater of the plan's `planned_turn_x100` and a floor of
    200 (two turns) ... so a plan targeting fewer than two turns is treated as if it
    targeted exactly two." With the same 150_000_000 of planned sales at 5500 bps of
    margin: cost of goods 67_500_000, `SEASONAL` role capacity "12500" bps == 84_375_000,
    turn capacity 67_500_000 x 300 / 200 == 101_250_000 and a department ceiling of
    900_000_000 x 1200 / 10000 == 108_000_000. The inner maximum picks turn capacity and
    the outer minimum does not bind.

    Design: Difficulty/combinatorial_formula/receipt_budget_nested_min_max_department_cap
    """
    scenario = setup_plan_scenario(
        department_overrides=PLAN_B_DEPARTMENT,
        category_overrides=PLAN_B_CATEGORY,
        plan_overrides=PLAN_B_PLAN,
        month_specs=[dict(PLAN_B_MONTH)],
        option_plan_specs=[dict(PLAN_B_OPTION_PLAN)],
        size_curve=PLAN_B_CURVE,
        approve=True,
    )

    plan = get_plan(scenario["plan_id"])
    assert plan["receipt_budget_cents"] == 101_250_000
    assert plan["receipt_budget_cents"] != 84_375_000
    assert plan["receipt_budget_cents"] != 67_500_000
    assert plan["receipt_budget_cents"] != 108_000_000

    assert get_month(scenario["m1"]["id"])["otb_planned_cents"] == 24_300_000

    cell = get_option_plan(scenario["option_plan"]["id"])
    assert cell["option_slots_total"] == 10
    assert cell["target_units_per_option"] == 368
    cells = get_size_curve_cells(cell["id"])
    assert [row["allocated_units"] for row in
            sorted(cells, key=lambda r: r["size_sort_order"])] == [92, 92, 92, 92]


def _curve_by_label(option_plan_id):
    return {row["size_label"]: row for row in get_size_curve_cells(option_plan_id)}


def test_size_curve_rounds_each_cell_then_reconciles_the_remainder():
    """Per-cell rounding over-allocates by one unit and XS gives it back.

    PRD: "**The order is pinned: each size row is rounded on its own and only then are the
    rows summed.** Summing the raw demands and rounding once at the end is explicitly not
    the rule". Per-cell rounding of 220800/607200/938400/717600/276000 ten-thousandths
    yields 22 + 61 + 94 + 72 + 28 == 277 against a cell target of 276, and PRD: "When the
    difference is negative ... rows are visited in ascending order of fractional part,
    ties broken by ascending `size_sort_order`, and one unit is subtracted from each row
    visited." XS holds the smallest fractional part, 800, so XS stores 21.

    Design: Difficulty/combinatorial_formula/size_curve_per_cell_round_then_sum
    """
    scenario = setup_plan_scenario()
    cells = _curve_by_label(scenario["option_plan"]["id"])

    assert {label: row["raw_units_x10000"] for label, row in cells.items()} == {
        "XS": 220_800, "S": 607_200, "M": 938_400, "L": 717_600, "XL": 276_000,
    }
    assert {label: row["allocated_units"] for label, row in cells.items()} == {
        "XS": 21, "S": 61, "M": 94, "L": 72, "XL": 28,
    }
    total = sum(row["allocated_units"] for row in cells.values())
    assert total == 276
    assert total != 277

    # PRD: the replacement "does **not** write the option plan's
    # `target_units_per_option`, which stays null for as long as the cell's `status` is
    # `OPEN`".
    cell = get_option_plan(scenario["option_plan"]["id"])
    assert cell["status"] == "OPEN"
    assert cell["target_units_per_option"] is None


def test_slotting_re_derives_the_identical_per_cell_allocation():
    """The slotting cascade re-runs the same formula and only then pins the target.

    PRD: "The slotting cascade described in §3.4 re-runs the identical formula and
    additionally persists `target_units_per_option`. The per-row numbers it re-derives are
    necessarily identical to the ones the replacement wrote". The target itself is
    round-half-up(6 x 40 x 11500 / 10000) == 276, matching the reconciled row sum.

    Design: Difficulty/combinatorial_formula/size_curve_per_cell_round_then_sum
    """
    scenario = setup_canonical_approved_plan()
    cell = get_option_plan(scenario["option_plan"]["id"])

    assert cell["status"] == "SLOTTED"
    assert cell["target_units_per_option"] == 276
    assert cell["option_slots_total"] == 14

    cells = _curve_by_label(cell["id"])
    assert cells["XS"]["allocated_units"] == 21
    assert cells["S"]["allocated_units"] == 61
    assert sum(row["allocated_units"] for row in cells.values()) == 276
    assert cells["XS"]["raw_units_x10000"] == 220_800


def _committed_month(scenario, units=6800, unit_cost_cents=2500):
    item = propose_item(
        scenario["option_plan"]["id"], scenario["vendor"]["id"],
        sku_code="DRSS-BUY-01", color_code="BLK", lifecycle_stage="CARRYOVER",
        unit_cost_cents=unit_cost_cents, retail_price_cents=6900,
        prior_season_sell_through_bps=7100,
    )
    commitment = propose_commitment(
        scenario["m1"]["id"], item["id"], scenario["vendor"]["id"],
        units=units, unit_cost_cents=unit_cost_cents,
    )
    return commit_commitment(commitment["id"])


def test_committing_receipts_never_re_enters_the_reserve_formula():
    """Committing 17_000_000 moves only the committed and open figures.

    PRD: "**The reserve is recomputed on exactly two events and no others** — when a month
    advances `DRAFT → LOCKED_PLAN`, and when a week of actuals is posted against the
    month. Committing a commitment, cancelling one, or posting receipts against one
    changes only `otb_committed_cents`, `otb_received_cents` and `otb_open_cents`;
    `provisional_sell_through_bps`, `reserve_rate_bps`, `markdown_reserve_cents` and
    `otb_planned_cents` all retain the values written by the previous reserve event".

    Design: Difficulty/combinatorial_formula/markdown_reserve_pinned_single_pass
    """
    scenario = setup_in_season_plan()
    commitment = _committed_month(scenario)

    assert commitment["commit_status"] == "COMMITTED"
    assert commitment["open_cost_cents"] == 17_000_000

    month = get_month(scenario["m1"]["id"])
    assert month["provisional_sell_through_bps"] == 6750
    assert month["reserve_rate_bps"] == 350
    assert month["markdown_reserve_cents"] == 700_000
    assert month["otb_planned_cents"] == 18_200_000
    assert month["otb_committed_cents"] == 17_000_000
    assert month["otb_open_cents"] == 1_200_000

    plan = get_plan(scenario["plan_id"])
    assert plan["open_ratio_bps"] == 5768
    assert plan["otb_posture"] == "OPEN"


def test_committed_dollars_enter_the_reserve_denominator_exactly_once_at_the_next_post():
    """The next actuals post admits the committed dollars, and only once.

    PRD: "To either base the system adds the month's already-committed receipt cost — the
    sum, over the month's commitments whose `commit_status` is `COMMITTED` or `CLOSED`, of
    each one's `open_cost_cents` plus its `received_cost_cents`" and "Newly committed
    dollars first enter the sell-through denominator at that next event, and they enter it
    exactly once. The formula must never be iterated to a fixed point." Projected cost of
    sales 13_500_000 over 19_625_000 + 17_000_000 == 36_625_000 gives 3686 bps, which
    falls "below 4000 basis points" so "the rate is 900", a reserve of 3_296_250 and an
    `otb_planned_cents` of 21_171_250.

    Design: Difficulty/combinatorial_formula/markdown_reserve_pinned_single_pass
    """
    scenario = setup_in_season_plan()
    commitment = _committed_month(scenario)

    post_actuals(scenario["m1"]["id"], week_index=1, actual_sales_cents=7_500_000,
                 actual_receipts_cents=3_000_000, actual_units_received=1200)

    month = get_month(scenario["m1"]["id"])
    assert month["provisional_sell_through_bps"] == 3686
    assert month["reserve_rate_bps"] == 900
    assert month["markdown_reserve_cents"] == 3_296_250
    assert month["markdown_reserve_cents"] != 700_000
    assert month["otb_planned_cents"] == 21_171_250
    assert month["otb_committed_cents"] == 17_000_000
    assert month["otb_open_cents"] == 4_171_250

    plan = get_plan(scenario["plan_id"])
    assert plan["open_ratio_bps"] == 6059
    assert plan["otb_posture"] == "OPEN"
    assert plan["variance_status"] == "ON_PLAN"
    assert plan["sales_variance_bps"] == 0
    assert get_month(scenario["m1"]["id"])["otb_received_cents"] == 0
    assert commitment["open_cost_cents"] == 17_000_000
