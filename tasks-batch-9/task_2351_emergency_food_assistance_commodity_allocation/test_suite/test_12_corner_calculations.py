"""The declared arithmetic: income limits, the eight-step split, per-line rounding and FEFO."""

from test_helpers import (
    AllocationStatus,
    CycleStatus,
    DistributionStatus,
    EligibilityDetermination,
    EligibilityPosture,
    FormulaVariant,
    MIN_ALLOCATION_CASES,
    OrderStatus,
    StorageClass,
    assert_allocation_sum_matches_pool,
    assert_lot_assignments,
    assert_pounds,
    assert_ratio,
    factories as f,
    fixtures as fx,
    find_by,
    make_agency_coordinator_headers,
    validate_success,
)

RICE_CODE = "BULK_RICE"
CHICKEN_CODE = "FROZEN_CHICKEN"


def _agency_holding_twenty_rice_cases(api):
    """An ELIGIBLE agency with 20 transferred cases and an OPEN cycle to record against."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    area = fx.create_service_area(
        api, name="Area North", county_code="C001", poverty_population=40000
    )
    agency = fx.create_agency(
        api,
        area["id"],
        name="Agency Alpha",
        cold_storage_pallet_capacity=10,
        prior_period_pounds_distributed=120000,
        prior_period_allocated_cases=400,
    )
    fx.make_agency_eligible(api, agency["id"])
    rice = fx.create_bulk_rice(api)
    warehouse = fx.create_warehouse(api, name="WH North")
    lot = fx.create_posted_lot(
        api,
        rice["id"],
        warehouse["id"],
        federal_lot_code="FL-R-001",
        cases_received=100,
        pack_date="2026-06-01",
        best_by_date="2028-06-01",
    )
    transfer = fx.propose_transfer(api, lot["id"], agency["id"], 20)
    fx.accept_transfer(api, transfer["id"], agency["id"])
    cycle = fx.create_cycle(
        api,
        cycle_code="FY27A",
        formula_variant=FormulaVariant.STANDARD,
        allocatable_cases=1000,
        admin_funds_pool_cents=5000000,
        offered_commodity_codes=[RICE_CODE],
    )
    fx.compute_allocations(api, cycle["id"])
    fx.open_window(api, cycle["id"])
    fx.set_clock(api, "2026-08-06T00:00:00Z")
    return {"agency": agency, "cycle": cycle, "rice": rice}


def _record_three_person_household(api, env):
    return api.create_household_distribution(
        f.household_distribution_payload(
            env["agency"]["id"],
            env["cycle"]["id"],
            env["rice"]["id"],
            household_size=3,
            declared_monthly_income_cents=330000,
            participates_in_snap=False,
            self_declaration_signed=True,
            cases_distributed=4,
            distribution_date="2026-08-06",
        ),
        headers=make_agency_coordinator_headers(env["agency"]["id"]),
    )


def test_01_the_income_limit_grows_by_the_per_person_figure_and_the_boundary_is_inclusive(api):
    """PRD §3.9: "The record's `income_limit_cents` is a base limit of 195,000 cents per
    month plus 68,000 cents for each person in the household beyond the first — that is,
    the base plus `household_size` less one, multiplied by the per-person figure." PRD
    §3.9: "If `declared_monthly_income_cents` is at or below that limit,
    `eligibility_determination` is written as `ELIGIBLE`; the boundary is inclusive." PRD
    §3.9: "The distribution's `pounds_distributed` is its `cases_distributed` multiplied
    by the commodity's `net_weight_lbs_per_case`, rounded half up to two decimals."

    Design: Corner/calculations/household_income_limit_and_distributed_pounds_are_computed_from_size_and_case_weight
    """
    env = _agency_holding_twenty_rice_cases(api)

    record = validate_success(_record_three_person_household(api, env), 201)

    assert record["income_limit_cents"] == 331000, (
        f"income_limit_cents expected 331000 but got {record['income_limit_cents']}"
    )
    assert record["eligibility_determination"] == EligibilityDetermination.ELIGIBLE, (
        f"eligibility_determination expected ELIGIBLE but got "
        f"{record['eligibility_determination']}"
    )
    assert record["status"] == DistributionStatus.RECORDED, (
        f"status expected RECORDED but got {record['status']}"
    )
    assert_pounds(record["pounds_distributed"], 80.0, "pounds_distributed")


def test_02_the_record_drains_the_agency_and_fills_the_entitlement_rollup(api):
    """PRD §3.9: "The `cases_distributed` figure must not exceed the agency's
    `agency_cases_on_hand`, otherwise `ERR_AGENCY_INVENTORY_INSUFFICIENT`; on success that
    counter falls by `cases_distributed`." PRD §3.9: "The entitlement's
    `distribution_record_count` is the number of such rows; its `distributed_pounds` is
    the sum of their `pounds_distributed` values, rounded half up to two decimals; and its
    `record_compliance_pct` is 0.0000 when the count is zero, and otherwise the number of
    those rows carrying `self_declaration_signed` equal to `true` divided by the count,
    rounded half up to four decimals."

    Design: Corner/calculations/household_income_limit_and_distributed_pounds_are_computed_from_size_and_case_weight
    """
    env = _agency_holding_twenty_rice_cases(api)

    validate_success(_record_three_person_household(api, env), 201)

    agency = fx.read_agency(api, env["agency"]["id"])
    assert agency["agency_cases_on_hand"] == 16, (
        f"agency_cases_on_hand expected 16 but got {agency['agency_cases_on_hand']}"
    )
    allocation = fx.read_allocation(api, env["cycle"]["id"], env["agency"]["id"])
    assert_pounds(allocation["distributed_pounds"], 80.0, "distributed_pounds")
    assert allocation["distribution_record_count"] == 1, (
        f"distribution_record_count expected 1 but got "
        f"{allocation['distribution_record_count']}"
    )
    assert_ratio(allocation["record_compliance_pct"], 1.0, "record_compliance_pct")


def _one_eligible_of_three_agencies(api):
    """Alpha is ELIGIBLE; Bravo is trained but unagreed; Charlie is untouched."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    area = fx.create_service_area(
        api, name="Area North", county_code="C001", poverty_population=40000
    )
    alpha = fx.create_agency(
        api,
        area["id"],
        name="Agency Alpha",
        cold_storage_pallet_capacity=10,
        prior_period_pounds_distributed=120000,
        prior_period_allocated_cases=400,
    )
    fx.make_agency_eligible(api, alpha["id"])
    bravo = fx.create_agency(
        api,
        area["id"],
        name="Agency Bravo",
        cold_storage_pallet_capacity=10,
        prior_period_pounds_distributed=60000,
        prior_period_allocated_cases=200,
    )
    fx.record_training(api, bravo["id"])
    charlie = fx.create_agency(
        api,
        area["id"],
        name="Agency Charlie",
        cold_storage_pallet_capacity=10,
        prior_period_pounds_distributed=60000,
        prior_period_allocated_cases=200,
    )
    fx.create_bulk_rice(api)
    cycle = fx.create_cycle(
        api,
        cycle_code="FY27SET",
        formula_variant=FormulaVariant.STANDARD,
        allocatable_cases=100,
        admin_funds_pool_cents=5000000,
        offered_commodity_codes=[RICE_CODE],
    )
    return {
        "area": area,
        "alpha": alpha,
        "bravo": bravo,
        "charlie": charlie,
        "cycle": cycle,
    }


def test_03_only_the_eligible_agency_enters_the_run(api):
    """PRD §3.4: "The **included set** is every agency whose `eligibility_posture` is
    `ELIGIBLE` at the instant the run executes." PRD §3.4: "Agencies in `PROBATION` or
    `INELIGIBLE` receive no entitlement row at all — not a zero row, no row." PRD §3.4:
    "The run stamps `allocation_locked_at` from the logical clock and records into the
    cycle's `eligible_agency_count` how many agencies the included set held."

    Design: Corner/calculations/compute_allocations_includes_only_eligible_agencies_in_the_input_set
    """
    env = _one_eligible_of_three_agencies(api)

    cycle = validate_success(
        api.compute_allocations(env["cycle"]["id"], headers=fx.ADMIN)
    )

    assert cycle["status"] == CycleStatus.ALLOCATED, (
        f"status expected ALLOCATED but got {cycle['status']}"
    )
    assert cycle["eligible_agency_count"] == 1, (
        f"eligible_agency_count expected 1 but got {cycle['eligible_agency_count']}"
    )
    assert cycle["total_allocated_cases"] == 100, (
        f"total_allocated_cases expected 100 but got {cycle['total_allocated_cases']}"
    )
    rows, meta = fx.list_rows_and_meta(
        api.list_cycle_allocations(env["cycle"]["id"], headers=fx.ADMIN)
    )
    assert meta["total_count"] == 1, (
        f"exactly one entitlement row was due but total_count is {meta['total_count']}"
    )
    assert rows[0]["agency_id"] == env["alpha"]["id"], (
        f"the only entitlement expected agency {env['alpha']['id']} but got "
        f"{rows[0]['agency_id']}"
    )


def test_04_the_sole_included_agency_takes_every_share_and_the_whole_pool(api):
    """PRD §3.4: "Each included agency's `poverty_factor` is its service area's
    `poverty_population` divided by that same area's `eligible_agency_count`, rounded half
    up to four decimals." PRD §3.4: "The poverty factors of all included agencies are
    summed, and each agency's `poverty_share` is its own `poverty_factor` divided by that
    sum, rounded half up to six decimals." PRD §3.2: "In every other combination —
    including an `ACTIVE` agreement whose training is still `REQUIRED`, and any agency
    whose agreement is `PENDING`, `EXPIRED`, or `TERMINATED` — the posture is
    `INELIGIBLE`." PRD §3.2: "Immediately after any posture write, the
    `eligible_agency_count` of that agency's service area is recomputed as the number of
    agencies in that area whose posture is `ELIGIBLE`."

    Design: Corner/calculations/compute_allocations_includes_only_eligible_agencies_in_the_input_set
    """
    env = _one_eligible_of_three_agencies(api)

    fx.compute_allocations(api, env["cycle"]["id"])

    area = fx.read_service_area(api, env["area"]["id"])
    assert area["eligible_agency_count"] == 1, (
        f"the area's eligible_agency_count expected 1 but got "
        f"{area['eligible_agency_count']}"
    )
    allocation = fx.read_allocation(api, env["cycle"]["id"], env["alpha"]["id"])
    assert_ratio(allocation["poverty_factor"], 40000.0, "poverty_factor")
    assert_ratio(allocation["poverty_share"], 1.0, "poverty_share")
    assert_ratio(allocation["prior_share"], 1.0, "prior_share")
    assert_ratio(allocation["raw_score"], 1.0, "raw_score")
    assert allocation["allocated_cases"] == 100, (
        f"allocated_cases expected 100 but got {allocation['allocated_cases']}"
    )
    for label, agency_id in (("Bravo", env["bravo"]["id"]), ("Charlie", env["charlie"]["id"])):
        agency = fx.read_agency(api, agency_id)
        assert agency["eligibility_posture"] == EligibilityPosture.INELIGIBLE, (
            f"{label} expected INELIGIBLE but got {agency['eligibility_posture']}"
        )


def _separable_poverty_and_prior_weights(api):
    """Poverty shares 0.75/0.25 against prior shares 0.2/0.8 in two one-agency areas."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    north = fx.create_service_area(
        api, name="Area North", county_code="C001", poverty_population=30000
    )
    south = fx.create_service_area(
        api, name="Area South", county_code="C002", poverty_population=10000
    )
    alpha = fx.create_agency(
        api,
        north["id"],
        name="Agency Alpha",
        cold_storage_pallet_capacity=10,
        prior_period_pounds_distributed=20000,
        prior_period_allocated_cases=400,
    )
    bravo = fx.create_agency(
        api,
        south["id"],
        name="Agency Bravo",
        cold_storage_pallet_capacity=10,
        prior_period_pounds_distributed=80000,
        prior_period_allocated_cases=400,
    )
    for agency in (alpha, bravo):
        fx.make_agency_eligible(api, agency["id"])
    fx.create_bulk_rice(api)
    cycle = fx.create_cycle(
        api,
        cycle_code="FY27WGT",
        formula_variant=FormulaVariant.STANDARD,
        allocatable_cases=100,
        admin_funds_pool_cents=5000000,
        offered_commodity_codes=[RICE_CODE],
    )
    return {"alpha": alpha, "bravo": bravo, "cycle": cycle}


def test_05_the_blended_score_weights_poverty_at_sixty_and_prior_at_forty(api):
    """PRD §3.4: "Otherwise each agency's `prior_share` is its own
    `prior_period_pounds_distributed` divided by that sum, rounded half up to six
    decimals, and its `raw_score` is 60 percent of its `poverty_share` plus 40 percent of
    its `prior_share`, rounded half up to six decimals."

    Design: Corner/calculations/raw_score_applies_the_declared_poverty_and_prior_weights
    """
    env = _separable_poverty_and_prior_weights(api)

    fx.compute_allocations(api, env["cycle"]["id"])

    alpha = fx.read_allocation(api, env["cycle"]["id"], env["alpha"]["id"])
    assert_ratio(alpha["poverty_share"], 0.75, "Alpha poverty_share")
    assert_ratio(alpha["prior_share"], 0.2, "Alpha prior_share")
    assert_ratio(alpha["raw_score"], 0.53, "Alpha raw_score")
    bravo = fx.read_allocation(api, env["cycle"]["id"], env["bravo"]["id"])
    assert_ratio(bravo["poverty_share"], 0.25, "Bravo poverty_share")
    assert_ratio(bravo["prior_share"], 0.8, "Bravo prior_share")
    assert_ratio(bravo["raw_score"], 0.47, "Bravo raw_score")


def test_06_the_weighted_scores_carry_straight_into_the_case_counts(api):
    """PRD §3.4: "Each agency's exact entitlement is the cycle's `allocatable_cases`
    multiplied by its `raw_score`; its base entitlement is that exact figure with the
    fractional part discarded." PRD §3.4: "Under `STANDARD`, `floor_cases` stays 0 for
    every agency and `allocated_cases` is simply the provisional figure." PRD §3.4: "The
    sum of `allocated_cases` across the cycle's entitlement rows equals the cycle's
    `allocatable_cases` exactly, and the cycle's `total_allocated_cases` is written from
    that sum."

    Design: Corner/calculations/raw_score_applies_the_declared_poverty_and_prior_weights
    """
    env = _separable_poverty_and_prior_weights(api)

    fx.compute_allocations(api, env["cycle"]["id"])

    alpha = fx.read_allocation(api, env["cycle"]["id"], env["alpha"]["id"])
    assert alpha["allocated_cases"] == 53, (
        f"Alpha allocated_cases expected 53 but got {alpha['allocated_cases']}"
    )
    assert alpha["floor_cases"] == 0, (
        f"Alpha floor_cases expected 0 under STANDARD but got {alpha['floor_cases']}"
    )
    bravo = fx.read_allocation(api, env["cycle"]["id"], env["bravo"]["id"])
    assert bravo["allocated_cases"] == 47, (
        f"Bravo allocated_cases expected 47 but got {bravo['allocated_cases']}"
    )
    assert bravo["floor_cases"] == 0, (
        f"Bravo floor_cases expected 0 under STANDARD but got {bravo['floor_cases']}"
    )
    cycle = fx.read_cycle(api, env["cycle"]["id"])
    assert cycle["total_allocated_cases"] == 100, (
        f"total_allocated_cases expected 100 but got {cycle['total_allocated_cases']}"
    )
    assert_allocation_sum_matches_pool(
        fx.list_cycle_allocations(api, env["cycle"]["id"]), 100
    )


def _submitted_three_case_frozen_line(api):
    """A submitted order carrying a single 3-case FROZEN_CHICKEN line."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    area = fx.create_service_area(
        api, name="Area North", county_code="C001", poverty_population=40000
    )
    agency = fx.create_agency(
        api,
        area["id"],
        name="Agency Alpha",
        cold_storage_pallet_capacity=10,
        prior_period_pounds_distributed=120000,
        prior_period_allocated_cases=400,
    )
    fx.make_agency_eligible(api, agency["id"])
    chicken = fx.create_frozen_chicken(api)
    warehouse = fx.create_warehouse(api, name="WH North")
    fx.create_posted_lot(
        api,
        chicken["id"],
        warehouse["id"],
        federal_lot_code="FL-C-001",
        cases_received=50,
        pack_date="2026-06-01",
        best_by_date="2027-06-01",
    )
    cycle = fx.create_cycle(
        api,
        cycle_code="FY27F",
        formula_variant=FormulaVariant.STANDARD,
        allocatable_cases=1000,
        admin_funds_pool_cents=5000000,
        offered_commodity_codes=[CHICKEN_CODE],
    )
    fx.compute_allocations(api, cycle["id"])
    fx.open_window(api, cycle["id"])
    fx.set_clock(api, "2026-08-06T00:00:00Z")

    order = fx.create_order(api, cycle["id"], agency["id"], warehouse["id"])
    line = fx.add_line(api, order["id"], agency["id"], chicken["id"], 3)
    fx.submit_order(api, order["id"], agency["id"])
    return {"agency": agency, "order": order, "line": line}


def _only_line(api, order_id):
    lines = fx.read_order_lines(api, order_id)
    assert len(lines) == 1, f"expected exactly one order line but got {len(lines)}"
    return lines[0]


def test_07_the_line_rounds_half_up_at_two_decimals_and_ceilings_its_pallets(api):
    """PRD §3.6: "With every line's `cases_approved` settled, each line's `line_pounds` is
    its `cases_approved` multiplied by its commodity's `net_weight_lbs_per_case`, rounded
    half up to two decimals; and each line's `line_pallets` is its `cases_approved`
    divided by its commodity's `cases_per_pallet`, rounded *up* to the next whole number."

    Design: Corner/calculations/line_pounds_round_half_up_at_two_decimals_and_pallets_ceil_per_line
    """
    env = _submitted_three_case_frozen_line(api)
    before_line = _only_line(api, env["order"]["id"])
    assert_pounds(before_line["line_pounds"], 0.0, "line_pounds before approval")
    before_order = fx.read_order(api, env["order"]["id"])
    assert_pounds(before_order["total_pounds"], 0.0, "total_pounds before approval")

    validate_success(api.approve_order(env["order"]["id"], headers=fx.SECOND_REVIEWER))

    line = _only_line(api, env["order"]["id"])
    assert line["cases_approved"] == 3, (
        f"cases_approved expected 3 but got {line['cases_approved']}"
    )
    assert line["storage_class"] == StorageClass.FROZEN, (
        f"storage_class expected FROZEN but got {line['storage_class']}"
    )
    assert_pounds(line["line_pounds"], 90.38, "line_pounds")
    assert line["line_pallets"] == 1, (
        f"line_pallets expected ceil(3/45) == 1 but got {line['line_pallets']}"
    )


def test_08_the_order_totals_sum_the_already_rounded_per_line_figures(api):
    """PRD §3.6: "The order's `total_pounds` is the sum of the per-line rounded
    `line_pounds` values, and its `total_pallets` is the sum of the per-line ceilinged
    `line_pallets` values."

    Design: Corner/calculations/line_pounds_round_half_up_at_two_decimals_and_pallets_ceil_per_line
    """
    env = _submitted_three_case_frozen_line(api)

    order = validate_success(
        api.approve_order(env["order"]["id"], headers=fx.SECOND_REVIEWER)
    )

    assert order["status"] == OrderStatus.APPROVED, (
        f"status expected APPROVED but got {order['status']}"
    )
    assert_pounds(order["total_pounds"], 90.38, "total_pounds")
    assert order["total_pallets"] == 1, (
        f"total_pallets expected 1 but got {order['total_pallets']}"
    )
    assert order["total_cases_approved"] == 3, (
        f"total_cases_approved expected 3 but got {order['total_cases_approved']}"
    )


def _later_lot_created_before_the_earlier_one(api):
    """A 2028 lot of 50 cases posted first, then a 2027 lot of only 8 cases."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    area = fx.create_service_area(
        api, name="Area North", county_code="C001", poverty_population=40000
    )
    agency = fx.create_agency(
        api,
        area["id"],
        name="Agency Alpha",
        cold_storage_pallet_capacity=10,
        prior_period_pounds_distributed=120000,
        prior_period_allocated_cases=400,
    )
    fx.make_agency_eligible(api, agency["id"])
    rice = fx.create_bulk_rice(api)
    warehouse = fx.create_warehouse(api, name="WH North")
    late = fx.create_posted_lot(
        api,
        rice["id"],
        warehouse["id"],
        federal_lot_code="FL-LATE",
        cases_received=50,
        pack_date="2026-06-01",
        best_by_date="2028-01-01",
    )
    early = fx.create_posted_lot(
        api,
        rice["id"],
        warehouse["id"],
        federal_lot_code="FL-EARLY",
        cases_received=8,
        pack_date="2026-06-01",
        best_by_date="2027-01-01",
    )
    cycle = fx.create_cycle(
        api,
        cycle_code="FY27FEFO",
        formula_variant=FormulaVariant.STANDARD,
        allocatable_cases=1000,
        admin_funds_pool_cents=5000000,
        offered_commodity_codes=[RICE_CODE],
    )
    fx.compute_allocations(api, cycle["id"])
    fx.open_window(api, cycle["id"])
    fx.set_clock(api, "2026-08-06T00:00:00Z")

    order = fx.create_order(api, cycle["id"], agency["id"], warehouse["id"])
    fx.add_line(api, order["id"], agency["id"], rice["id"], 10)
    fx.submit_order(api, order["id"], agency["id"])
    return {
        "agency": agency,
        "cycle": cycle,
        "early": early,
        "late": late,
        "order": order,
    }


def test_09_the_selector_exhausts_the_earliest_best_by_lot_before_the_later_one(api):
    """PRD §3.6: "The candidates are ranked by `best_by_date` ascending, with ties broken
    by `created_at` ascending and by nothing else; the selector walks that ranking in
    order, taking from each candidate the lesser of the cases still needed and that
    candidate's available cases, until the line's need is met." PRD §3.6: "Each amount
    taken is appended to the line's `lot_assignments` in fill order as a pairing of the
    `lot_id` drawn from and the `cases` taken, and is added to that lot's
    `cases_committed`."

    Design: Corner/calculations/fefo_reserves_the_earliest_best_by_lot_first_and_splits_across_two_lots
    """
    env = _later_lot_created_before_the_earlier_one(api)

    validate_success(api.approve_order(env["order"]["id"], headers=fx.SECOND_REVIEWER))

    line = _only_line(api, env["order"]["id"])
    assert_lot_assignments(line, [(env["early"]["id"], 8), (env["late"]["id"], 2)])


def test_10_the_split_commits_cases_on_both_lots_without_moving_any(api):
    """PRD §3.6: "For each line, the candidate lots are those at the order's
    `warehouse_id` whose `commodity_id` matches the line's, whose `status` is `AVAILABLE`
    or `WATCH`, and whose available cases — `cases_on_hand` minus `cases_committed` — are
    greater than zero." PRD §2.9: "Approval adds each line's reserved cases to that lot's
    `cases_committed` and adds the order's `total_cases_approved` to the allocation's
    `cases_committed`."

    Design: Corner/calculations/fefo_reserves_the_earliest_best_by_lot_first_and_splits_across_two_lots
    """
    env = _later_lot_created_before_the_earlier_one(api)

    validate_success(api.approve_order(env["order"]["id"], headers=fx.SECOND_REVIEWER))

    early = fx.read_lot(api, env["early"]["id"])
    assert early["cases_committed"] == 8, (
        f"the early lot cases_committed expected 8 but got {early['cases_committed']}"
    )
    assert early["cases_on_hand"] == 8, (
        f"a commitment may not move cases but cases_on_hand is {early['cases_on_hand']}"
    )
    late = fx.read_lot(api, env["late"]["id"])
    assert late["cases_committed"] == 2, (
        f"the late lot cases_committed expected 2 but got {late['cases_committed']}"
    )
    assert late["cases_on_hand"] == 50, (
        f"a commitment may not move cases but cases_on_hand is {late['cases_on_hand']}"
    )
    line = _only_line(api, env["order"]["id"])
    assert_pounds(line["line_pounds"], 200.0, "line_pounds")
    assert line["line_pallets"] == 1, (
        f"line_pallets expected 1 but got {line['line_pallets']}"
    )
    allocation = fx.read_allocation(api, env["cycle"]["id"], env["agency"]["id"])
    assert allocation["cases_committed"] == 10, (
        f"cases_committed expected 10 but got {allocation['cases_committed']}"
    )


def _ninety_nine_to_one_split(api):
    """Poverty 99000 against 1000 with no prior distribution anywhere in the program."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    rich = fx.create_service_area(
        api, name="Area Rich", county_code="C001", poverty_population=99000
    )
    thin = fx.create_service_area(
        api, name="Area Thin", county_code="C002", poverty_population=1000
    )
    alpha = fx.create_agency(
        api,
        rich["id"],
        name="Agency Alpha",
        cold_storage_pallet_capacity=10,
        prior_period_pounds_distributed=0,
        prior_period_allocated_cases=0,
    )
    bravo = fx.create_agency(
        api,
        thin["id"],
        name="Agency Bravo",
        cold_storage_pallet_capacity=10,
        prior_period_pounds_distributed=0,
        prior_period_allocated_cases=0,
    )
    for agency in (alpha, bravo):
        fx.make_agency_eligible(api, agency["id"])
    fx.create_bulk_rice(api)
    cycle = fx.create_cycle(
        api,
        cycle_code="FY27LIFT",
        formula_variant=FormulaVariant.STANDARD,
        allocatable_cases=100,
        admin_funds_pool_cents=5000000,
        offered_commodity_codes=[RICE_CODE],
    )
    return {"alpha": alpha, "bravo": bravo, "cycle": cycle}


def test_11_the_minimum_lift_takes_its_cases_from_the_largest_allocation(api):
    """PRD §3.4: "Under both variants, a single pass then lifts every agency whose
    `allocated_cases` is below the five-case programme minimum up to exactly five cases."
    PRD §3.4: "Each lifted case is funded one at a time from whichever agency currently
    holds the largest `allocated_cases`, with ties broken by the entitlement row's
    `created_at` ascending, and no agency may be taken below the greater of the five-case
    minimum and its own `floor_cases`." PRD §3.4: "If that sum is zero, every agency's
    `prior_share` is 0.000000 and its `raw_score` is set equal to its `poverty_share` —
    the weights collapse entirely onto poverty."

    Design: Corner/calculations/min_allocation_lift_pulls_cases_from_the_largest_allocation
    """
    env = _ninety_nine_to_one_split(api)

    cycle = validate_success(
        api.compute_allocations(env["cycle"]["id"], headers=fx.ADMIN)
    )

    assert cycle["status"] == CycleStatus.ALLOCATED, (
        f"status expected ALLOCATED but got {cycle['status']}"
    )
    alpha = fx.read_allocation(api, env["cycle"]["id"], env["alpha"]["id"])
    assert alpha["allocated_cases"] == 95, (
        f"the donor expected 95 cases after funding the lift but got "
        f"{alpha['allocated_cases']}"
    )
    bravo = fx.read_allocation(api, env["cycle"]["id"], env["bravo"]["id"])
    assert bravo["allocated_cases"] == 5, (
        f"the lifted agency expected exactly 5 cases but got {bravo['allocated_cases']}"
    )
    assert_ratio(bravo["prior_share"], 0.0, "Bravo prior_share")
    assert_ratio(bravo["raw_score"], 0.01, "Bravo raw_score")


def test_12_the_lift_conserves_the_pool_and_leaves_nobody_under_the_minimum(api):
    """PRD §3.4: "The sum of `allocated_cases` across the cycle's entitlement rows equals
    the cycle's `allocatable_cases` exactly, and the cycle's `total_allocated_cases` is
    written from that sum." PRD §3.4: "The lift runs exactly once and is never
    re-evaluated against its own output — an agency pushed down to the five-case minimum
    by funding someone else's lift does not itself trigger a further lift."

    Design: Corner/calculations/min_allocation_lift_pulls_cases_from_the_largest_allocation
    """
    env = _ninety_nine_to_one_split(api)

    fx.compute_allocations(api, env["cycle"]["id"])

    rows = fx.list_cycle_allocations(api, env["cycle"]["id"])
    assert len(rows) == 2, f"expected two entitlement rows but got {len(rows)}"
    assert_allocation_sum_matches_pool(rows, 100)
    cycle = fx.read_cycle(api, env["cycle"]["id"])
    assert cycle["total_allocated_cases"] == 100, (
        f"total_allocated_cases expected 100 but got {cycle['total_allocated_cases']}"
    )
    for row in rows:
        assert row["allocated_cases"] >= MIN_ALLOCATION_CASES, (
            f"agency {row['agency_id']} sits below the five-case minimum with "
            f"{row['allocated_cases']} cases"
        )
        assert row["status"] == AllocationStatus.ENTITLED, (
            f"entitlement status expected ENTITLED but got {row['status']}"
        )
    donor = find_by(rows, agency_id=env["alpha"]["id"])
    assert donor["allocated_cases"] == 95, (
        f"the donor expected 95 cases but got {donor['allocated_cases']}"
    )
