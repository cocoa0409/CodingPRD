"""Need-basis variants on allocation runs and basis variants on cluster scorecards."""
from test_helpers import (
    line_for_store,
    lines_for_run,
    setup_network_with_staged_receipt,
    setup_receipt_network,
    create_receipt,
    create_committed_run,
    units_by_size,
    validate_success,
)


def _staged_sixty_unit_receipt():
    """Four graded stores, one SEASONAL SKU on the TOP-4SZ curve and a 60-unit
    STAGED receipt. No promotional event exists, so every store's lift is 10000."""
    return setup_network_with_staged_receipt(units_received=60)


def _open_run(api, receipt, need_basis, headers):
    return validate_success(
        api.create_allocation_run(
            receipt["id"],
            {
                "method": "DEMAND_DRIVEN",
                "need_basis": need_basis,
                "expected_receipt_version": receipt["version"],
            },
            headers,
        ),
        201,
    )


def test_forward_looking_need_rounds_weekly_demand_before_the_cover_multiply(
    api, allocator_headers
):
    """PRD §3.6: "Under a `need_basis` of `FORWARD_LOOKING`, weekly demand is the
    position's `weekly_forecast_units` multiplied by the lift in effect for that
    store from §3.5 expressed as a fraction of 10000, **rounded half up to a whole
    number of units first**, and only then multiplied by the four-week cover
    horizon to give the demand-driven target." "The pipeline under this basis is
    the position's `available_units` plus its `in_transit_units` plus its
    `on_order_units`".

    Store 0101 forecasts 9 units a week at the default 10000 lift, so its target
    is 9 x 4 = 36 and its pipeline is 6 available plus 4 on order, leaving a need
    of 26.

    Design: Difficulty/dual_variant_calc/store_need_forward_looking_vs_historical_sell_through
    """
    scenario = _staged_sixty_unit_receipt()
    run = _open_run(api, scenario["receipt"], "FORWARD_LOOKING", allocator_headers)

    proposed = validate_success(api.propose_run(run["id"], allocator_headers))

    line = line_for_store(run["id"], scenario["stores"]["0101"]["id"])
    assert line["need_units"] == 26
    assert line["units_proposed"] == 26
    assert units_by_size(line["size_breakdown"]) == {"S": 5, "M": 10, "L": 8, "XL": 3}
    assert proposed["units_proposed"] == 44
    assert proposed["unallocated_remainder_units"] == 16
    assert proposed["eligible_store_count"] == 3


def test_historical_sell_through_need_rounds_once_after_the_cover_multiply(
    api, allocator_headers
):
    """PRD §3.6: "Under a `need_basis` of `HISTORICAL_SELL_THROUGH`, weekly demand
    is the position's `trailing_4wk_sales_units` scaled by the store's
    `grade_index_bp` as a fraction of 10000 and then divided by four to convert
    four weeks of sales into one week, and that figure is kept as an **exact
    unrounded value**." "The pipeline under this basis is the position's
    `available_units` plus its `in_transit_units` and **nothing else** —
    `on_order_units` are deliberately ignored".

    Store 0101 sold 30 units in four weeks at a 13000 grade index, so its exact
    weekly figure is 9.75, its target is a single rounding of 39.0 and its
    pipeline is 6 available with the 4 on-order units invisible, leaving 33.

    Design: Difficulty/dual_variant_calc/store_need_forward_looking_vs_historical_sell_through
    """
    scenario = _staged_sixty_unit_receipt()
    run = _open_run(
        api, scenario["receipt"], "HISTORICAL_SELL_THROUGH", allocator_headers
    )

    proposed = validate_success(api.propose_run(run["id"], allocator_headers))

    line = line_for_store(run["id"], scenario["stores"]["0101"]["id"])
    assert line["need_units"] == 33
    assert line["units_proposed"] == 33
    assert units_by_size(line["size_breakdown"]) == {"S": 7, "M": 12, "L": 10, "XL": 4}
    assert proposed["units_proposed"] == 45
    assert proposed["unallocated_remainder_units"] == 15
    assert proposed["eligible_store_count"] == 3


def test_two_need_bases_diverge_on_the_same_positions_and_the_superseded_run_keeps_its_numbers(
    api, allocator_headers
):
    """PRD §3.6: "Under `DEMAND_DRIVEN` the target is built from a weekly demand
    figure carried out to a **cover horizon of four weeks**, and both the demand
    figure and the placement of its rounding depend on the run's `need_basis`."
    PRD §3.6: "If any sibling run on the same receipt is sitting in `DRAFT` or
    `PROPOSED`, that sibling is driven to `CANCELLED`, the new run's
    `supersedes_run_id` is set to the superseded sibling's identifier, and every
    allocation line of the superseded run is driven to `RECALLED`."

    The same four positions produce 26 / 10 / 8 forward-looking and 33 / 6 / 6
    historical, and the retired run's audit figures survive its cancellation.

    Design: Difficulty/dual_variant_calc/store_need_forward_looking_vs_historical_sell_through
    """
    scenario = _staged_sixty_unit_receipt()
    stores = scenario["stores"]

    forward_run = _open_run(
        api, scenario["receipt"], "FORWARD_LOOKING", allocator_headers
    )
    validate_success(api.propose_run(forward_run["id"], allocator_headers))
    forward_needs = {
        code: line_for_store(forward_run["id"], stores[code]["id"])["need_units"]
        for code in ("0101", "0103", "0104")
    }
    forward_line = line_for_store(forward_run["id"], stores["0101"]["id"])

    refreshed = validate_success(api.get_receipt(scenario["receipt"]["id"], allocator_headers))
    historical_run = _open_run(
        api, refreshed, "HISTORICAL_SELL_THROUGH", allocator_headers
    )
    validate_success(api.propose_run(historical_run["id"], allocator_headers))
    historical_needs = {
        code: line_for_store(historical_run["id"], stores[code]["id"])["need_units"]
        for code in ("0101", "0103", "0104")
    }

    assert forward_needs == {"0101": 26, "0103": 10, "0104": 8}
    assert historical_needs == {"0101": 33, "0103": 6, "0104": 6}

    retired = validate_success(api.get_allocation_run(forward_run["id"], allocator_headers))
    assert retired["status"] == "CANCELLED"
    assert historical_run["supersedes_run_id"] == forward_run["id"]

    retired_line = validate_success(
        api.get_allocation_line(forward_line["id"], allocator_headers)
    )
    assert retired_line["fulfillment_status"] == "RECALLED"
    assert retired_line["units_proposed"] == 26


def _urban_cluster_after_a_committed_spread():
    """The same four positions with a 40-unit receipt spread FORWARD_LOOKING and
    committed. The URBAN cluster then holds exactly two positions: 0101 with 6
    available against a 12 minimum and 30 sold, and 0102 with 20 available against
    an 8 minimum and 16 sold. Store 0101 carries the only URBAN line, at 24 units."""
    scenario = setup_receipt_network()
    scenario["receipt"] = create_receipt(
        scenario["program"]["id"],
        scenario["item"]["id"],
        reference="ASN-9002",
        units_received=40,
        size_received=[
            {"size_code": "S", "units": 8},
            {"size_code": "M", "units": 14},
            {"size_code": "L", "units": 12},
            {"size_code": "XL", "units": 6},
        ],
    )
    scenario["run"] = create_committed_run(scenario["receipt"]["id"])
    return scenario


def test_simple_average_basis_truncates_each_position_ratio_then_averages_them(
    api, allocation_manager_headers
):
    """PRD §3.9: "Under `SIMPLE_AVERAGE`, each position is reduced to a ratio first
    and the ratios are then averaged." "Then `in_stock_pct_bp` is the arithmetic
    mean of the in-stock ratios across the included positions, rounded half up to
    a whole number of basis points, and `sell_through_pct_bp` is the arithmetic
    mean of the sell ratios, rounded half up the same way."

    The URBAN positions score 5000 and 10000 in stock for a mean of 7500, and
    8333 and 4444 on sell-through for a mean of 6388.5 rounded up to 6389.

    Design: Difficulty/dual_variant_calc/cluster_scorecard_simple_average_vs_unit_weighted
    """
    scenario = _urban_cluster_after_a_committed_spread()

    snapshot = validate_success(
        api.create_performance_snapshot(
            {
                "program_id": scenario["program"]["id"],
                "cluster_code": "URBAN",
                "basis": "SIMPLE_AVERAGE",
            },
            allocation_manager_headers,
        ),
        201,
    )

    assert snapshot["in_stock_pct_bp"] == 7500
    assert snapshot["sell_through_pct_bp"] == 6389
    assert snapshot["store_count"] == 2
    assert snapshot["included_position_count"] == 2


def test_unit_weighted_basis_sums_both_sides_then_divides_and_truncates_once(
    api, allocation_manager_headers
):
    """PRD §3.9: "Under `UNIT_WEIGHTED`, numerators and denominators are summed
    across the whole cluster first, divided once, and truncated once." "There is a
    single division and a single truncation, so no per-position rounding error
    accumulates."

    On the identical URBAN data the covered units sum to 14 against a 20 minimum
    for 7000, and 46 sold against a base of 72 truncates to 6388 rather than the
    6389 the averaged ratios produced.

    Design: Difficulty/dual_variant_calc/cluster_scorecard_simple_average_vs_unit_weighted
    """
    scenario = _urban_cluster_after_a_committed_spread()

    snapshot = validate_success(
        api.create_performance_snapshot(
            {
                "program_id": scenario["program"]["id"],
                "cluster_code": "URBAN",
                "basis": "UNIT_WEIGHTED",
            },
            allocation_manager_headers,
        ),
        201,
    )

    assert snapshot["in_stock_pct_bp"] == 7000
    assert snapshot["sell_through_pct_bp"] == 6388


def test_allocation_accuracy_is_identical_under_both_bases(
    api, allocation_manager_headers
):
    """PRD §3.9: "`allocation_accuracy_bp` is **identical under both bases**,
    because it is always unit-weighted." "Otherwise it is 10000 less the deviation
    multiplied by 10000 and divided by total sold with the quotient truncated down,
    and that result floored at 0 so the figure never goes negative."

    The URBAN deviation is 6 for store 0101 and 16 for store 0102 against 46 units
    sold, so both snapshots score 5218 even though their in-stock and sell-through
    figures differ.

    Design: Difficulty/dual_variant_calc/cluster_scorecard_simple_average_vs_unit_weighted
    """
    scenario = _urban_cluster_after_a_committed_spread()

    simple = validate_success(
        api.create_performance_snapshot(
            {
                "program_id": scenario["program"]["id"],
                "cluster_code": "URBAN",
                "basis": "SIMPLE_AVERAGE",
            },
            allocation_manager_headers,
        ),
        201,
    )
    weighted = validate_success(
        api.create_performance_snapshot(
            {
                "program_id": scenario["program"]["id"],
                "cluster_code": "URBAN",
                "basis": "UNIT_WEIGHTED",
            },
            allocation_manager_headers,
        ),
        201,
    )

    assert simple["allocation_accuracy_bp"] == 5218
    assert weighted["allocation_accuracy_bp"] == 5218
    assert simple["in_stock_pct_bp"] != weighted["in_stock_pct_bp"]


def test_snapshot_without_a_basis_falls_back_to_the_programs_scorecard_basis(
    api, allocation_manager_headers
):
    """PRD §3.9: "optionally naming a `basis` of `SIMPLE_AVERAGE` or
    `UNIT_WEIGHTED`; when `basis` is omitted it falls back to the program's
    `scorecard_basis`." PRD §3.1: "`scorecard_basis` is the default variant used
    for cluster scorecards when a snapshot request does not name one, and when
    omitted it defaults to `UNIT_WEIGHTED`".

    The program was created without a `scorecard_basis`, so a snapshot that names
    no basis is measured unit-weighted and reports 7000 rather than 7500.

    Design: Difficulty/dual_variant_calc/cluster_scorecard_simple_average_vs_unit_weighted
    """
    scenario = _urban_cluster_after_a_committed_spread()

    snapshot = validate_success(
        api.create_performance_snapshot(
            {"program_id": scenario["program"]["id"], "cluster_code": "URBAN"},
            allocation_manager_headers,
        ),
        201,
    )

    assert snapshot["basis"] == "UNIT_WEIGHTED"
    assert snapshot["in_stock_pct_bp"] == 7000
    assert snapshot["sell_through_pct_bp"] == 6388
