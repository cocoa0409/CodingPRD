"""The two declared variant switches: the allocation formula and the monitor policy."""

from test_helpers import (
    FormulaVariant,
    LotStatus,
    MonitorFlag,
    MonitorPolicy,
    assert_allocation_sum_matches_pool,
    assert_instant,
    assert_lot_ledger,
    assert_ratio,
    fixtures as fx,
)

STANDARD_CODE = "FY27STD"
HOLD_HARMLESS_CODE = "FY27HH"


def _three_county_program(api):
    """Three counties, one eligible agency each, and a single dry commodity."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    roster = fx.build_areas_and_agencies(api, fx.three_county_roster())
    commodity = fx.create_canned_peaches(api, entitlement_value_cents_per_case=1800)
    return roster["agencies"], commodity


def _cycle(api, cycle_code, formula_variant):
    return fx.create_cycle(
        api,
        cycle_code=cycle_code,
        formula_variant=formula_variant,
        allocatable_cases=1001,
        admin_funds_pool_cents=5000000,
        offered_commodity_codes=["CANNED_PEACHES"],
    )


def test_01_standard_variant_scores_agencies_on_the_blended_weights(api):
    """PRD §3.4: "each agency's `prior_share` is its own
    `prior_period_pounds_distributed` divided by that sum, rounded half up to six
    decimals, and its `raw_score` is 60 percent of its `poverty_share` plus 40
    percent of its `prior_share`, rounded half up to six decimals."

    Design: Difficulty/dual_variant_calc/allocation_formula_standard_vs_hold_harmless_diverges_on_same_inputs
    """
    agencies, _commodity = _three_county_program(api)
    cycle = _cycle(api, STANDARD_CODE, FormulaVariant.STANDARD)

    cycle = fx.compute_allocations(api, cycle["id"])
    first = fx.read_allocation(api, cycle["id"], agencies[0]["id"])

    assert_ratio(first["poverty_share"], 0.4, "poverty_share of the largest county")
    assert_ratio(first["prior_share"], 0.5, "prior_share of the largest distributor")
    assert_ratio(first["raw_score"], 0.44, "raw_score under the 60/40 blend")
    assert cycle["eligible_agency_count"] == 3, (
        "the run records how many agencies the included set held, expected 3 but got "
        f"{cycle['eligible_agency_count']}"
    )


def test_02_standard_variant_leaves_every_floor_at_zero(api):
    """PRD §3.4: "Under `STANDARD`, `floor_cases` stays 0 for every agency and
    `allocated_cases` is simply the provisional figure."

    Design: Difficulty/dual_variant_calc/allocation_formula_standard_vs_hold_harmless_diverges_on_same_inputs
    """
    agencies, _commodity = _three_county_program(api)
    cycle = _cycle(api, STANDARD_CODE, FormulaVariant.STANDARD)

    cycle = fx.compute_allocations(api, cycle["id"])

    expected = [441, 300, 260]
    for agency, allocated_cases in zip(agencies, expected):
        row = fx.read_allocation(api, cycle["id"], agency["id"])
        assert row["allocated_cases"] == allocated_cases, (
            f"{agency['name']} expected {allocated_cases} allocated cases but got "
            f"{row['allocated_cases']}"
        )
        assert row["floor_cases"] == 0, (
            f"{agency['name']} carries floor_cases {row['floor_cases']} under STANDARD"
        )
    assert cycle["total_allocated_cases"] == 1001, (
        f"total_allocated_cases expected 1001 but got {cycle['total_allocated_cases']}"
    )


def test_03_hold_harmless_variant_lifts_floors_and_claws_back_from_the_donors(api):
    """PRD §3.4: "Under `HOLD_HARMLESS`, each agency's `floor_cases` is 90 percent
    of its `prior_period_allocated_cases` with the fractional part discarded, and
    no agency may finish below that floor." PRD §3.4: "every donor except the last
    in rank order is reduced by the total shortfall multiplied by that donor's own
    excess divided by the total excess, with the fractional part discarded; the
    last donor in rank order absorbs whatever remains of the total shortfall after
    those earlier reductions, which is what makes the clawback sum exactly."

    Design: Difficulty/dual_variant_calc/allocation_formula_standard_vs_hold_harmless_diverges_on_same_inputs
    """
    agencies, _commodity = _three_county_program(api)
    cycle = _cycle(api, HOLD_HARMLESS_CODE, FormulaVariant.HOLD_HARMLESS)

    cycle = fx.compute_allocations(api, cycle["id"])

    expected = [(360, 420), (342, 342), (180, 239)]
    for agency, (floor_cases, allocated_cases) in zip(agencies, expected):
        row = fx.read_allocation(api, cycle["id"], agency["id"])
        assert row["floor_cases"] == floor_cases, (
            f"{agency['name']} expected floor_cases {floor_cases} but got "
            f"{row['floor_cases']}"
        )
        assert row["allocated_cases"] == allocated_cases, (
            f"{agency['name']} expected {allocated_cases} allocated cases but got "
            f"{row['allocated_cases']}"
        )


def test_04_both_variants_split_the_same_pool_exactly(api):
    """PRD §3.4: "The sum of `allocated_cases` across the cycle's entitlement rows
    equals the cycle's `allocatable_cases` exactly, and the cycle's
    `total_allocated_cases` is written from that sum."

    Design: Difficulty/dual_variant_calc/allocation_formula_standard_vs_hold_harmless_diverges_on_same_inputs
    """
    agencies, _commodity = _three_county_program(api)
    standard = _cycle(api, STANDARD_CODE, FormulaVariant.STANDARD)
    hold_harmless = _cycle(api, HOLD_HARMLESS_CODE, FormulaVariant.HOLD_HARMLESS)

    standard = fx.compute_allocations(api, standard["id"])
    hold_harmless = fx.compute_allocations(api, hold_harmless["id"])

    standard_rows = fx.list_cycle_allocations(api, standard["id"])
    hold_harmless_rows = fx.list_cycle_allocations(api, hold_harmless["id"])
    assert_allocation_sum_matches_pool(standard_rows, 1001)
    assert_allocation_sum_matches_pool(hold_harmless_rows, 1001)

    standard_cases = [
        fx.read_allocation(api, standard["id"], agency["id"])["allocated_cases"]
        for agency in agencies
    ]
    hold_harmless_cases = [
        fx.read_allocation(api, hold_harmless["id"], agency["id"])["allocated_cases"]
        for agency in agencies
    ]
    assert standard_cases != hold_harmless_cases, (
        "the two variants must disagree on identical inputs, both answered "
        f"{standard_cases}"
    )


def _two_policy_warehouses(api):
    """One lot per monitor policy, each with 40 of its 100 cases already shipped."""
    fx.set_clock(api, "2026-06-01T00:00:00Z")
    roster = fx.build_areas_and_agencies(
        api,
        [
            {
                "name": "Area One",
                "county_code": "C001",
                "poverty_population": 40000,
                "urban_rural": "URBAN",
                "agencies": [
                    {
                        "name": "Agency One",
                        "cold_storage_pallet_capacity": 10,
                        "prior_period_pounds_distributed": 120000,
                        "prior_period_allocated_cases": 400,
                        "training": "2026-06-01T00:00:00Z",
                        "attendee_count": 4,
                        "agreement": ("2026-06-01", "2027-05-31"),
                    }
                ],
            }
        ],
    )
    agency = roster["agencies"][0]
    rice = fx.create_bulk_rice(api)
    north = fx.create_warehouse_with_policy(
        api, MonitorPolicy.TURNOVER_BASED, name="WH North"
    )
    south = fx.create_warehouse_with_policy(
        api, MonitorPolicy.SHELF_LIFE_BASED, name="WH South"
    )
    lots = {}
    for key, warehouse, code in (
        ("north", north, "FL-N-001"),
        ("south", south, "FL-S-001"),
    ):
        lot = fx.create_posted_lot(
            api,
            rice["id"],
            warehouse["id"],
            federal_lot_code=code,
            cases_received=100,
            pack_date="2026-05-01",
            best_by_date="2026-11-01",
        )
        transfer = fx.propose_transfer(api, lot["id"], agency["id"], 40)
        fx.accept_transfer(api, transfer["id"], agency["id"])
        lots[key] = lot
    fx.set_clock(api, "2026-08-15T00:00:00Z")
    return lots


def test_05_turnover_based_policy_flags_the_lot_and_moves_it_to_watch(api):
    """PRD §3.3: "Under `TURNOVER_BASED`, the index is 70 percent of the unsold
    share — one minus the turnover ratio — plus 30 percent of the age saturation,
    where age saturation is the days on hand divided by a 90-day horizon, capped
    at 1.0 so that a lot older than 90 days saturates rather than growing without
    bound." PRD §3.3: "A lot in `AVAILABLE` that scores `EXCESS` or `SLOW_MOVING`
    moves `AVAILABLE → WATCH`."

    Design: Difficulty/dual_variant_calc/lot_monitor_turnover_vs_shelf_life_flags_different_lots
    """
    lots = _two_policy_warehouses(api)

    fx.run_monitor(api)

    northern = fx.read_lot(api, lots["north"]["id"])
    assert northern["slow_moving_index"] == 0.67, (
        f"slow_moving_index expected 0.67 but got {northern['slow_moving_index']}"
    )
    assert northern["monitor_flag"] == MonitorFlag.SLOW_MOVING, (
        f"monitor_flag expected SLOW_MOVING but got {northern['monitor_flag']}"
    )
    assert northern["status"] == LotStatus.WATCH, (
        f"status expected WATCH but got {northern['status']}"
    )
    assert_lot_ledger(northern, cases_on_hand=60, cases_committed=0, cases_shipped_to_date=40)


def test_06_shelf_life_based_policy_scores_the_same_data_below_the_threshold(api):
    """PRD §3.3: "Under `SHELF_LIFE_BASED`, the index is half of the consumed shelf
    life — one minus the shelf remaining fraction — plus half of the unsold share
    — one minus the turnover ratio." PRD §3.3: "otherwise, if the rounded
    `slow_moving_index` is at least 0.60, the flag is `SLOW_MOVING`; otherwise the
    flag is `NONE`."

    Design: Difficulty/dual_variant_calc/lot_monitor_turnover_vs_shelf_life_flags_different_lots
    """
    lots = _two_policy_warehouses(api)

    fx.run_monitor(api)

    southern = fx.read_lot(api, lots["south"]["id"])
    assert southern["slow_moving_index"] == 0.5881, (
        f"slow_moving_index expected 0.5881 but got {southern['slow_moving_index']}"
    )
    assert southern["monitor_flag"] == MonitorFlag.NONE, (
        f"monitor_flag expected NONE but got {southern['monitor_flag']}"
    )
    assert southern["status"] == LotStatus.AVAILABLE, (
        f"status expected AVAILABLE but got {southern['status']}"
    )


def test_07_every_scored_lot_is_stamped_with_the_run_instant(api):
    """PRD §3.3: "Every scored lot has `monitor_flag`, `slow_moving_index`, and
    `last_monitored_at` written and its `version` incremented by one."

    Design: Difficulty/dual_variant_calc/lot_monitor_turnover_vs_shelf_life_flags_different_lots
    """
    lots = _two_policy_warehouses(api)
    versions = {
        key: fx.read_lot(api, lot["id"])["version"] for key, lot in lots.items()
    }

    fx.run_monitor(api)

    for key, lot in lots.items():
        row = fx.read_lot(api, lot["id"])
        assert_instant(
            row["last_monitored_at"],
            "2026-08-15T00:00:00Z",
            f"last_monitored_at of the {key} lot",
        )
        assert row["version"] == versions[key] + 1, (
            f"the {key} lot version expected {versions[key] + 1} but got {row['version']}"
        )
