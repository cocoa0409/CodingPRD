"""Multi-input formulas: the pinned per-line rounding order and the admin funds pass."""

from test_helpers import (
    CycleStatus,
    FormulaVariant,
    OrderStatus,
    assert_admin_funds_sum_matches_pool,
    assert_all_reconciled,
    assert_pounds,
    assert_ratio,
    fixtures as fx,
)

PEACH_CODE = "CANNED_PEACHES"
CHICKEN_CODE = "FROZEN_CHICKEN"


def _submitted_three_line_order(api):
    """Three lines — 10 and 15 peach cases plus 23 chicken cases — awaiting review."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    area = fx.create_service_area(
        api, name="Area One", county_code="C001", poverty_population=40000
    )
    agency = fx.create_agency(
        api,
        area["id"],
        name="Agency One",
        cold_storage_pallet_capacity=10,
        prior_period_pounds_distributed=120000,
        prior_period_allocated_cases=400,
    )
    agency = fx.make_agency_eligible(api, agency["id"])
    peaches = fx.create_canned_peaches(api, entitlement_value_cents_per_case=1800)
    chicken = fx.create_frozen_chicken(api)
    warehouse = fx.create_warehouse(api, name="WH North")
    fx.create_posted_lot(
        api,
        peaches["id"],
        warehouse["id"],
        federal_lot_code="FL-P-001",
        cases_received=100,
        pack_date="2026-05-01",
        best_by_date="2028-05-01",
    )
    fx.create_posted_lot(
        api,
        chicken["id"],
        warehouse["id"],
        federal_lot_code="FL-C-001",
        cases_received=100,
        pack_date="2026-05-01",
        best_by_date="2027-05-01",
    )
    cycle = fx.create_cycle(
        api,
        cycle_code="FY27ROUND",
        formula_variant=FormulaVariant.STANDARD,
        allocatable_cases=1001,
        admin_funds_pool_cents=5000000,
        offered_commodity_codes=[PEACH_CODE, CHICKEN_CODE],
    )
    fx.compute_allocations(api, cycle["id"])
    fx.open_window(api, cycle["id"])
    fx.set_clock(api, "2026-08-06T00:00:00Z")

    order = fx.create_order(api, cycle["id"], agency["id"], warehouse["id"])
    lines = [
        fx.add_line(api, order["id"], agency["id"], peaches["id"], 10),
        fx.add_line(api, order["id"], agency["id"], peaches["id"], 15),
        fx.add_line(api, order["id"], agency["id"], chicken["id"], 23),
    ]
    fx.submit_order(api, order["id"], agency["id"])
    return {
        "agency": agency,
        "cycle": cycle,
        "order": order,
        "line_ids": [line["id"] for line in lines],
    }


def test_01_each_line_rounds_its_own_pounds_half_up(api):
    """PRD §3.6: "With every line's `cases_approved` settled, each line's
    `line_pounds` is its `cases_approved` multiplied by its commodity's
    `net_weight_lbs_per_case`, rounded half up to two decimals; and each line's
    `line_pallets` is its `cases_approved` divided by its commodity's
    `cases_per_pallet`, rounded *up* to the next whole number."

    Design: Difficulty/combinatorial_formula/order_totals_round_each_line_then_sum_mode_b
    """
    env = _submitted_three_line_order(api)

    fx.approve_order(api, env["order"]["id"])

    lines = {row["id"]: row for row in fx.read_order_lines(api, env["order"]["id"])}
    expected = dict(zip(env["line_ids"], [243.75, 365.63, 692.88]))
    for line_id, line_pounds in expected.items():
        assert_pounds(lines[line_id]["line_pounds"], line_pounds, f"line_pounds of {line_id}")


def test_02_each_line_ceilings_its_own_pallets(api):
    """PRD §3.6: "**The order of rounding and summation is pinned: each line is
    rounded and each line is ceilinged first, and only then are the results
    summed.**"

    Design: Difficulty/combinatorial_formula/order_totals_round_each_line_then_sum_mode_b
    """
    env = _submitted_three_line_order(api)

    fx.approve_order(api, env["order"]["id"])

    lines = {row["id"]: row for row in fx.read_order_lines(api, env["order"]["id"])}
    for line_id in env["line_ids"]:
        assert lines[line_id]["line_pallets"] == 1, (
            f"line_pallets of {line_id} expected 1 but got {lines[line_id]['line_pallets']}"
        )


def test_03_order_totals_sum_the_per_line_rounded_figures(api):
    """PRD §3.6: "The order's `total_pounds` is the sum of the per-line rounded
    `line_pounds` values, and its `total_pallets` is the sum of the per-line
    ceilinged `line_pallets` values." PRD §3.6: "lines of 10 and 15 cases of canned
    peaches plus 23 cases of frozen chicken give a `total_pounds` of 1302.26 and a
    `total_pallets` of 3 under the pinned per-line order, against 1302.25 and 2
    under the rejected alternatives."

    Design: Difficulty/combinatorial_formula/order_totals_round_each_line_then_sum_mode_b
    """
    env = _submitted_three_line_order(api)

    order = fx.approve_order(api, env["order"]["id"])

    assert_pounds(order["total_pounds"], 1302.26, "total_pounds")
    assert order["total_pallets"] == 3, (
        f"total_pallets expected 3 but got {order['total_pallets']}"
    )
    assert order["total_cases_approved"] == 48, (
        f"total_cases_approved expected 48 but got {order['total_cases_approved']}"
    )
    assert order["status"] == OrderStatus.APPROVED, (
        f"status expected APPROVED but got {order['status']}"
    )
    allocation = fx.read_allocation(api, env["cycle"]["id"], env["agency"]["id"])
    assert allocation["cases_committed"] == 48, (
        f"cases_committed expected 48 but got {allocation['cases_committed']}"
    )
    assert allocation["cases_remaining"] == 953, (
        f"cases_remaining expected 953 but got {allocation['cases_remaining']}"
    )


def _closed_cycle_with_distributions(api):
    """Three entitlements with 600 / 300 / 100 distributed pounds, one of them unsigned."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    roster = fx.build_areas_and_agencies(api, fx.three_county_roster())
    agencies = roster["agencies"]
    rice = fx.create_bulk_rice(api)
    warehouse = fx.create_warehouse(api, name="WH North")
    lot = fx.create_posted_lot(
        api,
        rice["id"],
        warehouse["id"],
        federal_lot_code="FL-R-001",
        cases_received=300,
        pack_date="2026-06-01",
        best_by_date="2028-06-01",
    )
    cycle = fx.create_cycle(
        api,
        cycle_code="FY27ADM",
        formula_variant=FormulaVariant.STANDARD,
        allocatable_cases=1001,
        admin_funds_pool_cents=5000000,
        offered_commodity_codes=["BULK_RICE"],
    )
    fx.compute_allocations(api, cycle["id"])
    fx.open_window(api, cycle["id"])
    fx.set_clock(api, "2026-08-10T00:00:00Z")

    for agency, cases in zip(agencies, (30, 15, 5)):
        transfer = fx.propose_transfer(api, lot["id"], agency["id"], cases)
        fx.accept_transfer(api, transfer["id"], agency["id"])

    signed = {
        "household_size": 1,
        "declared_monthly_income_cents": 100000,
        "participates_in_snap": False,
        "self_declaration_signed": True,
        "distribution_date": "2026-08-10",
    }
    for agency, cases in zip(agencies, (30, 15, 2)):
        fx.record_distribution(
            api, agency["id"], cycle["id"], rice["id"], cases_distributed=cases, **signed
        )
    fx.record_distribution(
        api,
        agencies[2]["id"],
        cycle["id"],
        rice["id"],
        household_size=2,
        declared_monthly_income_cents=200000,
        participates_in_snap=False,
        self_declaration_signed=False,
        cases_distributed=3,
        distribution_date="2026-08-10",
    )
    fx.close_window(api, cycle["id"])
    return {"agencies": agencies, "cycle": cycle}


def test_04_the_rollup_counts_recorded_rows_and_their_signature_share(api):
    """PRD §3.9: "The entitlement's `distribution_record_count` is the number of
    such rows; its `distributed_pounds` is the sum of their `pounds_distributed`
    values, rounded half up to two decimals; and its `record_compliance_pct` is
    0.0000 when the count is zero, and otherwise the number of those rows carrying
    `self_declaration_signed` equal to `true` divided by the count, rounded half up
    to four decimals."

    Design: Difficulty/combinatorial_formula/admin_funds_withhold_then_redistribute_single_pass_mode_c
    """
    env = _closed_cycle_with_distributions(api)

    fx.finalize_cycle(api, env["cycle"]["id"])

    first = fx.read_allocation(api, env["cycle"]["id"], env["agencies"][0]["id"])
    assert_pounds(first["distributed_pounds"], 600.0, "distributed_pounds of Agency One")
    assert_ratio(first["record_compliance_pct"], 1.0, "record_compliance_pct of Agency One")

    third = fx.read_allocation(api, env["cycle"]["id"], env["agencies"][2]["id"])
    assert_pounds(third["distributed_pounds"], 100.0, "distributed_pounds of Agency Three")
    assert third["distribution_record_count"] == 2, (
        "distribution_record_count of Agency Three expected 2 but got "
        f"{third['distribution_record_count']}"
    )
    assert_ratio(third["record_compliance_pct"], 0.5, "record_compliance_pct of Agency Three")


def test_05_the_withheld_pool_is_redistributed_over_the_compliant_rows_only(api):
    """PRD §3.9: "A row whose `record_compliance_pct` is below the 0.9500 compliance
    minimum has 10 percent of its `admin_funds_base_cents` withheld, with the
    fractional part discarded, written to `admin_funds_withheld_cents`; a compliant
    row has `admin_funds_withheld_cents` of 0." PRD §3.9: "Each row's
    `admin_funds_cents` is its `admin_funds_base_cents` less its
    `admin_funds_withheld_cents` plus its redistribution share."

    Design: Difficulty/combinatorial_formula/admin_funds_withhold_then_redistribute_single_pass_mode_c
    """
    env = _closed_cycle_with_distributions(api)

    fx.finalize_cycle(api, env["cycle"]["id"])

    expected = [
        (3000000, 0, 3033333),
        (1500000, 0, 1516667),
        (500000, 50000, 450000),
    ]
    for agency, (base, withheld, final) in zip(env["agencies"], expected):
        row = fx.read_allocation(api, env["cycle"]["id"], agency["id"])
        assert row["admin_funds_base_cents"] == base, (
            f"{agency['name']} admin_funds_base_cents expected {base} but got "
            f"{row['admin_funds_base_cents']}"
        )
        assert row["admin_funds_withheld_cents"] == withheld, (
            f"{agency['name']} admin_funds_withheld_cents expected {withheld} but got "
            f"{row['admin_funds_withheld_cents']}"
        )
        assert row["admin_funds_cents"] == final, (
            f"{agency['name']} admin_funds_cents expected {final} but got "
            f"{row['admin_funds_cents']}"
        )


def test_06_finalization_closes_the_fiscal_invariant_and_reconciles_every_row(api):
    """PRD §3.9: "The sum of `admin_funds_cents` across the cycle's rows equals the
    cycle's `admin_funds_pool_cents` exactly, in cents, and the cycle's
    `admin_funds_allocated_cents` is written from that sum." PRD §3.9: "Every
    entitlement row of the cycle then moves to `status` `RECONCILED`."

    Design: Difficulty/combinatorial_formula/admin_funds_withhold_then_redistribute_single_pass_mode_c
    """
    env = _closed_cycle_with_distributions(api)

    cycle = fx.finalize_cycle(api, env["cycle"]["id"])

    assert cycle["admin_funds_allocated_cents"] == 5000000, (
        "admin_funds_allocated_cents expected 5000000 but got "
        f"{cycle['admin_funds_allocated_cents']}"
    )
    assert cycle["status"] == CycleStatus.RECONCILED, (
        f"cycle status expected RECONCILED but got {cycle['status']}"
    )
    rows = fx.list_cycle_allocations(api, env["cycle"]["id"])
    assert_admin_funds_sum_matches_pool(rows, 5000000)
    assert_all_reconciled(rows)

    report = fx.admin_funds_report(api, env["cycle"]["id"])
    assert report["withheld_cents_total"] == 50000, (
        f"withheld_cents_total expected 50000 but got {report['withheld_cents_total']}"
    )
    assert report["redistributed_cents_total"] == 50000, (
        "redistributed_cents_total expected 50000 but got "
        f"{report['redistributed_cents_total']}"
    )
    assert report["allocation_line_count"] == 3, (
        f"allocation_line_count expected 3 but got {report['allocation_line_count']}"
    )
    assert report["non_compliant_line_count"] == 1, (
        f"non_compliant_line_count expected 1 but got {report['non_compliant_line_count']}"
    )
