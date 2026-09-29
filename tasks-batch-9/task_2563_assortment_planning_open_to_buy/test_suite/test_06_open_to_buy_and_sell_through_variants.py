"""Dual-variant calculations: the two open-to-buy bases and the two sell-through bases.

Each test translates one instance of the difficulty rule ``dual_variant_calc``.
"""
from test_helpers import (
    CANONICAL,
    CANONICAL_M1_OTB_PLANNED_CENTS,
    CANONICAL_M2_OTB_PLANNED_CENTS,
    CANONICAL_TARGET_UNITS_PER_OPTION,
    adopt_item,
    get_item,
    get_month,
    get_option_plan,
    get_plan,
    get_success_data,
    post_actuals,
    propose_item,
    setup_canonical_approved_plan,
    setup_in_season_plan,
    validate_success,
)


def _ledger(api, month_id, headers, basis=None):
    params = {} if basis is None else {"basis": basis}
    resp = api.get_otb_ledger(month_id, headers, params=params)
    validate_success(resp)
    return get_success_data(resp)


def test_planned_basis_ledger_before_any_actuals(api, planner_headers):
    """The planned basis reads the authored month at face value.

    PRD: "Under `PLANNED_BASIS` the month's cost of sales is its `planned_sales_cents`
    converted to cost by the plan's margin and rounded half up, and the inventory base
    is the authored `bom_inventory_cents`". The canonical M1 therefore carries cost of
    sales 13_500_000 against a denominator of 20_000_000, a provisional sell-through of
    6750 bps, the 350 bps band ("from 6500 up to but not including 8500 it is 350") and
    a reserve of 700_000 cents.

    Design: Difficulty/dual_variant_calc/otb_basis_divergence_planned_vs_projected
    """
    scenario = setup_in_season_plan()
    month_id = scenario["m1"]["id"]

    ledger = _ledger(api, month_id, planner_headers, "PLANNED_BASIS")

    assert ledger["basis"] == "PLANNED_BASIS"
    assert ledger["weeks_posted"] == 0
    assert ledger["bom_inventory_cents"] == CANONICAL["month_1"]["bom_inventory_cents"]
    assert ledger["planned_sales_cost_cents"] == 13_500_000
    assert ledger["provisional_sell_through_bps"] == 6750
    assert ledger["reserve_rate_bps"] == 350
    assert ledger["markdown_reserve_cents"] == 700_000
    assert ledger["otb_planned_cents"] == CANONICAL_M1_OTB_PLANNED_CENTS
    assert ledger["otb_planned_cents"] == 18_200_000
    assert ledger["otb_open_cents"] == 18_200_000


def test_projected_basis_rebuilds_the_month_from_the_posted_week(api, planner_headers):
    """One posted week re-projects sales and rebuilds the opening inventory.

    PRD: "the weekly run rate is the actual sales to date divided by the number of weeks
    posted, kept as an exact rational and **not rounded**; projected sales for the month
    are the actual sales to date plus that run rate multiplied by the number of unposted
    weeks, where a fiscal month always contains four weeks" and "`projected_bom_cents`
    is the month's authored `bom_inventory_cents` plus the actual receipts to date less
    that actual cost of sales". With week 1 at 7_500_000 of sales and 6_000_000 of
    receipts: projected sales 30_000_000 -> cost 13_500_000, projected BOM
    20_000_000 + 6_000_000 - 3_375_000 == 22_625_000, sell-through 5967 bps, the
    600 bps band and a reserve of 1_357_500, so `otb_planned_cents` is 16_232_500.

    Design: Difficulty/dual_variant_calc/otb_basis_divergence_planned_vs_projected
    """
    scenario = setup_in_season_plan()
    month_id = scenario["m1"]["id"]

    post_actuals(month_id, week_index=1, actual_sales_cents=7_500_000,
                 actual_receipts_cents=6_000_000, actual_units_received=2500)

    month = get_month(month_id)
    assert month["active_basis"] == "PROJECTED_BASIS"
    assert month["provisional_sell_through_bps"] == 5967
    assert month["reserve_rate_bps"] == 600
    assert month["markdown_reserve_cents"] == 1_357_500
    assert month["otb_planned_cents"] == 16_232_500
    assert month["otb_open_cents"] == 16_232_500

    ledger = _ledger(api, month_id, planner_headers, "PROJECTED_BASIS")
    assert ledger["basis"] == "PROJECTED_BASIS"
    assert ledger["weeks_posted"] == 1
    assert ledger["projected_sales_cost_cents"] == 13_500_000
    assert ledger["projected_bom_cents"] == 22_625_000
    assert ledger["otb_planned_cents"] == 16_232_500


def test_planned_basis_read_never_consults_actuals_and_basis_is_per_month(
    api, planner_headers
):
    """The same stored month answers both bases, and the switch is per month.

    PRD: "Passing `PLANNED_BASIS` or `PROJECTED_BASIS` in `basis` returns that variant on
    demand for the same month" and "The same authored month therefore yields a different
    `otb_planned_cents` under the two bases". PRD: "a month whose `status` is `IN_SEASON`
    with at least one actuals row is on `PROJECTED_BASIS`" — M2, still `LOCKED_PLAN`,
    stays on the planned basis. The variance verdict prorates the plan side, so one of
    four weeks credits 7_500_000 against 7_500_000 of actuals: "Otherwise it is
    `ON_PLAN`".

    Design: Difficulty/dual_variant_calc/otb_basis_divergence_planned_vs_projected
    """
    scenario = setup_in_season_plan()
    m1_id, m2_id = scenario["m1"]["id"], scenario["m2"]["id"]

    post_actuals(m1_id, week_index=1, actual_sales_cents=7_500_000,
                 actual_receipts_cents=6_000_000, actual_units_received=2500)

    planned = _ledger(api, m1_id, planner_headers, "PLANNED_BASIS")
    projected = _ledger(api, m1_id, planner_headers, "PROJECTED_BASIS")
    assert planned["otb_planned_cents"] == 18_200_000
    assert projected["otb_planned_cents"] == 16_232_500
    assert planned["otb_planned_cents"] - projected["otb_planned_cents"] == 1_967_500

    m2 = get_month(m2_id)
    assert m2["active_basis"] == "PLANNED_BASIS"
    assert m2["otb_planned_cents"] == CANONICAL_M2_OTB_PLANNED_CENTS

    plan = get_plan(scenario["plan_id"])
    assert plan["sales_variance_bps"] == 0
    assert plan["variance_status"] == "ON_PLAN"
    assert plan["open_ratio_bps"] == 10000
    assert plan["otb_posture"] == "OPEN"


def test_new_item_basis_ignores_prior_season_history():
    """A `NEW` option is forecast from its tier benchmark and the cluster's sales index.

    PRD: "For an item whose stage is `NEW`, the **new-item basis** applies: the forecast
    is the tier benchmark of the item's cell — 6200 basis points for a `GOOD` cell, 5500
    for `BETTER`, 4300 for `BEST` — multiplied by the cluster's `sales_index_bps` and by
    the item's `effective_overlay_multiplier_bps`, divided by one hundred million ...
    rounded half up, and then capped at 9800 basis points. Under this basis the item's
    `prior_season_sell_through_bps` is ignored even when it is populated". 5500 x 11500 x
    10000 / 100_000_000 == 6325, and the authored history of 9000 contributes nothing.

    Design: Difficulty/dual_variant_calc/sell_through_basis_divergence_new_vs_carryover
    """
    scenario = setup_canonical_approved_plan()
    item = propose_item(
        scenario["option_plan"]["id"], scenario["vendor"]["id"],
        sku_code="DRSS-NEW-01", color_code="BLK", lifecycle_stage="NEW",
        unit_cost_cents=2500, retail_price_cents=6900,
        prior_season_sell_through_bps=9000,
    )

    adopted = adopt_item(item["id"])

    assert adopted["sell_through_basis"] == "NEW_ITEM_BASIS"
    assert adopted["sell_through_bps"] == 6325
    assert adopted["prior_season_sell_through_bps"] == 9000
    assert adopted["sell_through_bps"] != adopted["prior_season_sell_through_bps"]
    assert adopted["effective_overlay_multiplier_bps"] == 10000
    assert adopted["planned_units"] == CANONICAL_TARGET_UNITS_PER_OPTION == 276
    assert adopted["status"] == "ADOPTED"


def test_carryover_basis_scales_own_history_by_the_demographic_index():
    """A `CARRYOVER` option is forecast from its own history and the demographic index.

    PRD: "For an item whose stage is `CARRYOVER`, `CORE` or `EXIT`, the **carryover
    basis** applies: the forecast is the item's own `prior_season_sell_through_bps`
    multiplied by the cluster's `demographic_index_bps`, divided by ten thousand, rounded
    half up ... Under this basis the tier benchmark, the cluster's sales index and the
    overlay multiplier are all ignored". 7100 x 10500 / 10000 == 7455, a different answer
    from the new-item basis on a row that differs only in `lifecycle_stage`; PRD: "On
    success the item's `planned_units` is set to the cell's `target_units_per_option`" —
    basis-independent, so both rows land on 276.

    Design: Difficulty/dual_variant_calc/sell_through_basis_divergence_new_vs_carryover
    """
    scenario = setup_canonical_approved_plan()
    option_plan_id = scenario["option_plan"]["id"]
    new_item = propose_item(
        option_plan_id, scenario["vendor"]["id"], sku_code="DRSS-NEW-02",
        color_code="BLK", lifecycle_stage="NEW", unit_cost_cents=2500,
        retail_price_cents=6900, prior_season_sell_through_bps=9000,
    )
    carryover_item = propose_item(
        option_plan_id, scenario["vendor"]["id"], sku_code="DRSS-CAR-02",
        color_code="NVY", lifecycle_stage="CARRYOVER", unit_cost_cents=2500,
        retail_price_cents=6900, prior_season_sell_through_bps=7100,
    )

    adopt_item(new_item["id"])
    adopted_carryover = adopt_item(carryover_item["id"])

    assert adopted_carryover["sell_through_basis"] == "CARRYOVER_BASIS"
    assert adopted_carryover["sell_through_bps"] == 7455
    assert adopted_carryover["effective_overlay_multiplier_bps"] == 10000
    assert adopted_carryover["planned_units"] == 276
    assert get_item(new_item["id"])["sell_through_bps"] == 6325
    assert adopted_carryover["sell_through_bps"] != 6325

    cell = get_option_plan(option_plan_id)
    assert cell["option_slots_total"] == 14
    assert cell["option_slots_assigned"] == 2
    assert cell["option_slots_open"] == 12
