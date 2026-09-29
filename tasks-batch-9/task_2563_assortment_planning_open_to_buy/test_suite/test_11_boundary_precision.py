"""Probes placed one unit either side of a declared threshold, on three metrics.

Each test translates one instance of the difficulty rule ``boundary_precision_check``:
money in integer cents on a commitment's fiscal gate, basis points on the variance
verdict, and whole units on the size-curve allocation.
"""
from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    BUYER_HEADERS,
    DIRECTOR_HEADERS,
    PLANNER_HEADERS,
    assert_actuals_post,
    assert_otb_conservation,
    commit_commitment,
    get_month,
    get_option_plan,
    get_plan,
    get_size_curve_cells,
    get_success_data,
    month_version,
    post_actuals,
    propose_item,
    receipt_commitment_payload,
    setup_canonical_approved_plan,
    setup_draft_plan,
    setup_in_season_plan,
    size_curve_payload,
    validate_error,
    validate_success,
)
from test_helpers.constants import CANONICAL

M1_ONLY = [dict(CANONICAL["month_1"])]
JUNE_MONTH = {"month_index": 1, "fiscal_month_label": "2027-06",
              "first_receipt_date": "2027-06-04T00:00:00Z",
              "bom_inventory_cents": 20_000_000, "planned_sales_cents": 30_000_000,
              "planned_markdown_cents": 2_000_000, "planned_eom_cents": 22_000_000}


def _cent_boundary_scenario():
    """A canonical two-month plan bought through a one-unit-minimum vendor."""
    scenario = setup_canonical_approved_plan(
        vendor_overrides={"name": "Cinder Sample Co", "code": "CIND",
                          "lead_time_days": 45, "weekly_unit_capacity": 500,
                          "min_order_units": 1, "cancel_cutoff_days": 0},
        max_open_units=500,
    )
    item = propose_item(scenario["option_plan"]["id"], scenario["vendor"]["id"],
                        sku_code="DRSS-SAMPLE-1", color_code="STONE",
                        lifecycle_stage="CARRYOVER", unit_cost_cents=2500,
                        retail_price_cents=6900, prior_season_sell_through_bps=7100)
    return scenario, item


def _one_unit_probe(api, month_id, item_id, vendor_id, unit_cost_cents):
    payload = receipt_commitment_payload(
        month_id, item_id, vendor_id, month_version(month_id),
        units=1, unit_cost_cents=unit_cost_cents,
    )
    return api.create_receipt_commitment(payload, BUYER_HEADERS)


def test_one_cent_over_the_open_balance_is_refused_and_the_exact_balance_is_accepted(api):
    """The fiscal gate is an exact integer-cent comparison with no tolerance either side.

    PRD: "The commitment's `cost_cents` -- its `units` multiplied by its `unit_cost_cents` --
    is compared against the month's `otb_open_cents`: a cost exactly equal to the open balance
    is accepted, and one cent more is refused with `ERR_OTB_EXCEEDED`." The three probes are
    placed at balance + 1, balance - 1 and balance exactly, all at one unit so the vendor's
    capacity and minimum rules can never be the deciding ones.

    Design: Difficulty/boundary_precision_check/otb_open_exact_cent_boundary_on_commitment_create
    """
    scenario, item = _cent_boundary_scenario()
    month_id, vendor_id = scenario["m1"]["id"], scenario["vendor"]["id"]
    assert get_month(month_id)["otb_open_cents"] == 18_200_000
    assert get_month(month_id)["otb_committed_cents"] == 0

    over = _one_unit_probe(api, month_id, item["id"], vendor_id, 18_200_001)
    validate_error(over, ApiErrorId.ERR_OTB_EXCEEDED, expected_status=422)

    under = _one_unit_probe(api, month_id, item["id"], vendor_id, 18_199_999)
    validate_success(under, expected_status=201)
    rc_under = get_success_data(under)
    assert rc_under["cost_cents"] == 18_199_999
    assert rc_under["commit_status"] == "PROPOSED"

    # A proposal debits nothing, which is why the next probe may still ask for the whole
    # balance: PRD -- "a `PROPOSED` commitment has not yet entered the month's committed
    # figure".
    assert get_month(month_id)["otb_open_cents"] == 18_200_000

    exact = _one_unit_probe(api, month_id, item["id"], vendor_id, 18_200_000)
    validate_success(exact, expected_status=201)
    rc_exact = get_success_data(exact)
    assert rc_exact["cost_cents"] == 18_200_000
    assert rc_exact["open_cost_cents"] == 18_200_000


def test_a_single_cent_is_refused_once_the_balance_has_been_consumed(api):
    """Committing the exact balance leaves zero open, and zero admits nothing at all.

    PRD rule 37: "The commitment's cost does not exceed the month's open balance --
    `ERR_OTB_EXCEEDED` (422)". With the whole balance committed the month's open figure is 0,
    so a one-unit one-cent buy is still a cost greater than the balance and is refused. The
    plan's posture is `OPEN` at that moment, so priority 16 cannot be what fires.

    Design: Difficulty/boundary_precision_check/otb_open_exact_cent_boundary_on_commitment_create
    """
    scenario, item = _cent_boundary_scenario()
    month_id, vendor_id = scenario["m1"]["id"], scenario["vendor"]["id"]

    rc_under = get_success_data(
        _one_unit_probe(api, month_id, item["id"], vendor_id, 18_199_999))
    rc_exact = get_success_data(
        _one_unit_probe(api, month_id, item["id"], vendor_id, 18_200_000))
    commit_commitment(rc_exact["id"])

    month = get_month(month_id)
    assert month["otb_committed_cents"] == 18_200_000
    assert month["otb_open_cents"] == 0
    assert month["otb_received_cents"] == 0
    assert_otb_conservation(month)
    version_before = month["version"]

    plan = get_plan(scenario["plan_id"])
    assert plan["open_ratio_bps"] == 5469
    assert plan["otb_posture"] == "OPEN"

    one_cent = _one_unit_probe(api, month_id, item["id"], vendor_id, 1)
    validate_error(one_cent, ApiErrorId.ERR_OTB_EXCEEDED, expected_status=422)

    assert month_version(month_id) == version_before
    listed = get_success_data(
        api.list_receipt_commitments(BUYER_HEADERS,
                                     params={"plan_month_id": month_id, "limit": 50}))
    assert sorted(row["id"] for row in listed) == sorted([rc_under["id"], rc_exact["id"]])


def _ledger(api, month_id):
    return get_success_data(api.get_otb_ledger(month_id, PLANNER_HEADERS))


def _cycles_of(api, plan_id):
    return get_success_data(
        api.list_reforecast_cycles(DIRECTOR_HEADERS,
                                   params={"category_plan_id": plan_id, "limit": 50}))


def test_variance_of_exactly_minus_1000_bps_is_a_breach_and_not_a_watch(api):
    """The breach edge is inclusive, and it is read off an exactly representable variance.

    PRD: "At -1000 basis points or below, `variance_status` is `BREACH`. Otherwise, at -400
    basis points or below, it is `WATCH`... Exactly -1000 is therefore `BREACH` and not
    `WATCH`." One week of 6,750,000 against a prorated plan of 7,500,000 (30,000,000 * 1 / 4)
    gives 10000 * -750,000 / 7,500,000 == -1000 with no rounding involved at all, and PRD adds
    that a breach "unconditionally forces the plan's `otb_posture` to `FROZEN`... regardless of
    how much open budget remains" and opens a `VARIANCE_BREACH` cycle.

    Design: Difficulty/boundary_precision_check/variance_bps_breach_watch_boundary_on_actuals_post
    """
    scenario = setup_in_season_plan(month_specs=M1_ONLY)
    month_id, plan_id = scenario["m1"]["id"], scenario["plan_id"]
    assert get_month(month_id)["otb_planned_cents"] == 18_200_000
    assert get_month(month_id)["active_basis"] == "PLANNED_BASIS"
    assert get_plan(plan_id)["variance_status"] == "ON_PLAN"

    post_actuals(month_id, week_index=1, actual_sales_cents=6_750_000,
                 actual_receipts_cents=0, actual_units_received=0)

    plan = get_plan(plan_id)
    assert plan["sales_variance_bps"] == -1000
    assert plan["variance_status"] == "BREACH"
    assert plan["open_ratio_bps"] == 10000
    assert plan["otb_posture"] == "FROZEN"
    assert plan["status"] == "REFORECAST_OPEN"
    assert plan["reforecast_round"] == 1

    cycles = _cycles_of(api, plan_id)
    assert len(cycles) == 1
    assert cycles[0]["trigger_reason"] == "VARIANCE_BREACH"
    assert cycles[0]["round_index"] == 1
    assert cycles[0]["status"] == "OPEN"
    assert cycles[0]["snapshot_sales_variance_bps"] == -1000

    month = get_month(month_id)
    assert month["active_basis"] == "PROJECTED_BASIS"
    assert month["provisional_sell_through_bps"] == 7163
    assert month["reserve_rate_bps"] == 350
    assert month["markdown_reserve_cents"] == 593_688
    assert month["otb_planned_cents"] == 19_781_188
    ledger = _ledger(api, month_id)
    assert ledger["basis"] == "PROJECTED_BASIS"
    assert ledger["weeks_posted"] == 1
    assert ledger["projected_sales_cost_cents"] == 12_150_000
    assert ledger["projected_bom_cents"] == 16_962_500

    posts = get_success_data(
        api.list_month_actuals_posts(month_id, ADMIN_HEADERS, params={"limit": 10}))
    assert len(posts) == 1
    assert_actuals_post(posts[0])
    assert posts[0]["week_index"] == 1
    assert posts[0]["actual_sales_cents"] == 6_750_000


def test_seven_hundred_fifty_cents_more_lands_on_minus_999_and_only_watches(api):
    """One basis point inside the edge changes four plan fields and suppresses the cycle.

    PRD: "at -400 basis points or below, it is `WATCH`". 6,750,750 against the same prorated
    7,500,000 gives 10000 * -749,250 / 7,500,000 == -999 exactly, which is not at or below
    -1000, so there is no breach: no `FROZEN` override, no `APPROVED -> REFORECAST_OPEN`
    transition and, per PRD, no cycle -- the system "opens one itself when a weekly actuals
    post produces a `BREACH` verdict" and this verdict is not one.

    Design: Difficulty/boundary_precision_check/variance_bps_breach_watch_boundary_on_actuals_post
    """
    scenario = setup_in_season_plan(
        month_specs=[dict(JUNE_MONTH)],
        plan_overrides={"season_code": "SUMMER", "fiscal_year": 2027,
                        "planned_sales_cents": 150_000_000, "planned_margin_bps": 5500,
                        "planned_turn_x100": 320},
    )
    month_id, plan_id = scenario["m1"]["id"], scenario["plan_id"]
    assert get_month(month_id)["otb_planned_cents"] == 18_200_000

    post_actuals(month_id, week_index=1, actual_sales_cents=6_750_750,
                 actual_receipts_cents=0, actual_units_received=0)

    plan = get_plan(plan_id)
    assert plan["sales_variance_bps"] == -999
    assert plan["variance_status"] == "WATCH"
    assert plan["open_ratio_bps"] == 10000
    assert plan["otb_posture"] == "OPEN"
    assert plan["status"] == "APPROVED"
    assert plan["reforecast_round"] == 0
    assert _cycles_of(api, plan_id) == []

    month = get_month(month_id)
    assert month["active_basis"] == "PROJECTED_BASIS"
    assert month["provisional_sell_through_bps"] == 7164
    assert month["reserve_rate_bps"] == 350
    assert month["markdown_reserve_cents"] == 593_676
    assert month["otb_planned_cents"] == 19_782_864
    ledger = _ledger(api, month_id)
    assert ledger["projected_sales_cost_cents"] == 12_151_350
    assert ledger["projected_bom_cents"] == 16_962_162


THIN_XS_CURVE = [
    {"size_label": "XS", "size_sort_order": 1, "pct_bps": 18},
    {"size_label": "S", "size_sort_order": 2, "pct_bps": 2182},
    {"size_label": "M", "size_sort_order": 3, "pct_bps": 3400},
    {"size_label": "L", "size_sort_order": 4, "pct_bps": 2600},
    {"size_label": "XL", "size_sort_order": 5, "pct_bps": 1800},
]
STOCKABLE_XS_CURVE = [
    {"size_label": "XS", "size_sort_order": 1, "pct_bps": 19},
    {"size_label": "S", "size_sort_order": 2, "pct_bps": 2181},
    {"size_label": "M", "size_sort_order": 3, "pct_bps": 3400},
    {"size_label": "L", "size_sort_order": 4, "pct_bps": 2600},
    {"size_label": "XL", "size_sort_order": 5, "pct_bps": 1800},
]


def _cell_without_a_curve():
    scenario = setup_draft_plan(size_curve=[])
    return scenario["option_plan"]


def test_a_cell_rounding_to_zero_units_is_refused_and_persists_nothing(api):
    """Half a unit is the threshold, and 0.4968 of a unit falls below it.

    PRD: "The row's `allocated_units` is then `raw_units_x10000` divided by ten thousand and
    rounded half up to a whole unit... Should any row end this reconciliation with zero
    `allocated_units`, its share is too thin to stock and the whole submission is rejected with
    `ERR_SIZE_CURVE_ZERO_CELL`." The cell's total target is 6 * 40 * 11500 / 10000 == 276
    units, so XS at 18 basis points has `raw_units_x10000` 4968, which is below 5000 and rounds
    to 0. The other four rows already sum to 276, so no remainder reconciliation can rescue it.

    Design: Difficulty/boundary_precision_check/size_curve_zero_unit_cell_boundary
    """
    cell = _cell_without_a_curve()
    assert cell["target_units_per_option"] is None
    version_before = cell["version"]

    resp = api.replace_size_curve(cell["id"], size_curve_payload(THIN_XS_CURVE),
                                  PLANNER_HEADERS)

    validate_error(resp, ApiErrorId.ERR_SIZE_CURVE_ZERO_CELL, expected_status=422)
    assert get_size_curve_cells(cell["id"]) == []
    after = get_option_plan(cell["id"])
    assert after["target_units_per_option"] is None
    assert after["version"] == version_before


def test_one_basis_point_more_makes_the_thinnest_cell_stockable(api):
    """At 5244 ten-thousandths the same row rounds up to one unit and the curve is accepted.

    PRD: "each size row is rounded on its own and only then are the rows summed" and, when the
    rows over-allocate, "rows are visited in ascending order of fractional part... and one unit
    is subtracted from each row visited". XS at 19 basis points gives 5244 -> 1 unit, taking the
    naive sum to 277, so exactly one unit is removed from S, whose fractional part 1956 is the
    smallest -- not from the newly stockable XS. PRD also pins that the replacement "does
    **not** write the option plan's `target_units_per_option`, which stays null for as long as
    the cell's `status` is `OPEN`".

    Design: Difficulty/boundary_precision_check/size_curve_zero_unit_cell_boundary
    """
    cell = _cell_without_a_curve()
    version_before = cell["version"]

    resp = api.replace_size_curve(cell["id"], size_curve_payload(STOCKABLE_XS_CURVE),
                                  PLANNER_HEADERS)
    validate_success(resp, expected_status=200)

    rows = get_size_curve_cells(cell["id"])
    assert [row["size_label"] for row in rows] == ["XS", "S", "M", "L", "XL"]
    assert [row["raw_units_x10000"] for row in rows] == [
        5244, 601_956, 938_400, 717_600, 496_800]
    assert [row["allocated_units"] for row in rows] == [1, 59, 94, 72, 50]
    assert sum(row["allocated_units"] for row in rows) == 276

    after = get_option_plan(cell["id"])
    assert after["status"] == "OPEN"
    assert after["option_slots_total"] is None
    assert after["target_units_per_option"] is None
    assert after["version"] == version_before + 1
