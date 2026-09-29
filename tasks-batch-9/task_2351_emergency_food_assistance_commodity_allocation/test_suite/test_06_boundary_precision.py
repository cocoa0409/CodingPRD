"""Exact thresholds: the inclusive monitor index, the empty included set, the income limit."""

from test_helpers import (
    ApiErrorId,
    CycleStatus,
    DistributionStatus,
    DrawPosture,
    EligibilityDetermination,
    EligibilityPosture,
    FormulaVariant,
    LotStatus,
    MonitorFlag,
    MonitorPolicy,
    assert_income_limit,
    assert_lot_ledger,
    assert_pounds,
    assert_ratio,
    factories as f,
    fixtures as fx,
    make_agency_coordinator_headers,
    validate_error,
    validate_success,
)


def _two_lots_astride_the_threshold(api):
    """Identical lots aged 75 days, one shipped 50 cases and one shipped 51."""
    fx.set_clock(api, "2026-06-01T00:00:00Z")
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
    fx.make_agency_eligible(
        api,
        agency["id"],
        completed_at="2026-06-01T00:00:00Z",
        agreement_start_date="2026-06-01",
        agreement_end_date="2027-05-31",
    )
    rice = fx.create_bulk_rice(api)
    warehouse = fx.create_warehouse_with_policy(
        api, MonitorPolicy.TURNOVER_BASED, name="WH North"
    )
    lots = {}
    for key, code, cases in (("x", "FL-X-001", 50), ("y", "FL-Y-001", 51)):
        lot = fx.create_posted_lot(
            api,
            rice["id"],
            warehouse["id"],
            federal_lot_code=code,
            cases_received=100,
            pack_date="2026-05-01",
            best_by_date="2028-05-01",
        )
        transfer = fx.propose_transfer(api, lot["id"], agency["id"], cases)
        fx.accept_transfer(api, transfer["id"], agency["id"])
        lots[key] = lot
    fx.set_clock(api, "2026-08-15T00:00:00Z")
    return {"agency": agency, "warehouse": warehouse, "lots": lots}


def test_01_an_index_landing_exactly_on_the_threshold_is_slow_moving(api):
    """PRD §3.3: "The threshold comparison is inclusive and is made against the
    *rounded* index, so an index of exactly 0.6000 is `SLOW_MOVING`." PRD §3.3: "A
    lot in `AVAILABLE` that scores `EXCESS` or `SLOW_MOVING` moves `AVAILABLE →
    WATCH`."

    Design: Difficulty/boundary_precision_check/slow_moving_index_exactly_at_threshold_is_flagged
    """
    env = _two_lots_astride_the_threshold(api)

    fx.run_monitor(api, env["warehouse"]["id"])

    lot = fx.read_lot(api, env["lots"]["x"]["id"])
    assert lot["slow_moving_index"] == 0.6, (
        f"slow_moving_index expected 0.6 but got {lot['slow_moving_index']}"
    )
    assert lot["monitor_flag"] == MonitorFlag.SLOW_MOVING, (
        f"an index of exactly 0.6000 expected SLOW_MOVING but got {lot['monitor_flag']}"
    )
    assert lot["status"] == LotStatus.WATCH, (
        f"status expected WATCH but got {lot['status']}"
    )


def test_02_one_more_shipped_case_falls_below_the_threshold(api):
    """PRD §3.3: "Under `TURNOVER_BASED`, the index is 70 percent of the unsold share
    — one minus the turnover ratio — plus 30 percent of the age saturation, where age
    saturation is the days on hand divided by a 90-day horizon, capped at 1.0 so that
    a lot older than 90 days saturates rather than growing without bound." PRD §3.3:
    "otherwise, if the rounded `slow_moving_index` is at least 0.60, the flag is
    `SLOW_MOVING`; otherwise the flag is `NONE`."

    Design: Difficulty/boundary_precision_check/slow_moving_index_exactly_at_threshold_is_flagged
    """
    env = _two_lots_astride_the_threshold(api)

    fx.run_monitor(api, env["warehouse"]["id"])

    lot = fx.read_lot(api, env["lots"]["y"]["id"])
    assert lot["slow_moving_index"] == 0.593, (
        f"slow_moving_index expected 0.593 but got {lot['slow_moving_index']}"
    )
    assert lot["monitor_flag"] == MonitorFlag.NONE, (
        f"an index below 0.60 expected NONE but got {lot['monitor_flag']}"
    )
    assert lot["status"] == LotStatus.AVAILABLE, (
        f"status expected AVAILABLE but got {lot['status']}"
    )


def test_03_the_two_lots_differ_by_exactly_one_shipped_case(api):
    """PRD §3.3: "Its **turnover ratio** is 0.0000 when `cases_received` is zero, and
    otherwise `cases_shipped_to_date` divided by `cases_received`, rounded half up to
    four decimals."

    Design: Difficulty/boundary_precision_check/slow_moving_index_exactly_at_threshold_is_flagged
    """
    env = _two_lots_astride_the_threshold(api)

    fx.run_monitor(api, env["warehouse"]["id"])

    x = fx.read_lot(api, env["lots"]["x"]["id"])
    assert_lot_ledger(x, cases_on_hand=50, cases_committed=0, cases_shipped_to_date=50)
    y = fx.read_lot(api, env["lots"]["y"]["id"])
    assert_lot_ledger(y, cases_on_hand=49, cases_committed=0, cases_shipped_to_date=51)
    agency = fx.read_agency(api, env["agency"]["id"])
    assert agency["agency_cases_on_hand"] == 101, (
        f"agency_cases_on_hand expected 101 but got {agency['agency_cases_on_hand']}"
    )


def _cycle_with_no_eligible_agency(api):
    """A DRAFT cycle whose only agency has neither training nor agreement."""
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
    fx.create_bulk_rice(api)
    cycle = fx.create_cycle(
        api,
        cycle_code="FY27EMPTY",
        formula_variant=FormulaVariant.STANDARD,
        allocatable_cases=1001,
        admin_funds_pool_cents=5000000,
        offered_commodity_codes=["BULK_RICE"],
    )
    return {"area": area, "agency": agency, "cycle": cycle}


def test_04_an_empty_included_set_refuses_the_allocation_run(api):
    """PRD §3.4: "Three preconditions guard it: at least one agency must currently
    hold posture `ELIGIBLE`, otherwise `ERR_NO_ELIGIBLE_AGENCIES`; every entry of
    `offered_commodity_codes` must resolve to an existing commodity `code`, otherwise
    `ERR_COMMODITY_NOT_FOUND`; and under the `HOLD_HARMLESS` variant the floor lift
    must be fundable, otherwise `ERR_ALLOCATION_INFEASIBLE`."

    Design: Difficulty/boundary_precision_check/compute_allocations_with_empty_eligible_set_is_rejected
    """
    env = _cycle_with_no_eligible_agency(api)

    response = api.compute_allocations(env["cycle"]["id"], headers=fx.ADMIN, payload={})

    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_AGENCIES, 422)


def test_05_the_refused_run_leaves_the_cycle_in_draft_with_no_entitlement_rows(api):
    """PRD §3.4: "The cycle lands in `status` `DRAFT` with `draw_posture`
    `NOT_STARTED`, `total_allocated_cases` at 0, `eligible_agency_count` at 0,
    `admin_funds_allocated_cents` at 0, and `allocation_locked_at` null." PRD §3.4:
    "The run stamps `allocation_locked_at` from the logical clock and records into
    the cycle's `eligible_agency_count` how many agencies the included set held."

    Design: Difficulty/boundary_precision_check/compute_allocations_with_empty_eligible_set_is_rejected
    """
    env = _cycle_with_no_eligible_agency(api)

    api.compute_allocations(env["cycle"]["id"], headers=fx.ADMIN, payload={})

    cycle = fx.read_cycle(api, env["cycle"]["id"])
    assert cycle["status"] == CycleStatus.DRAFT, (
        f"cycle status must stay DRAFT but got {cycle['status']}"
    )
    assert cycle["draw_posture"] == DrawPosture.NOT_STARTED, (
        f"draw_posture must stay NOT_STARTED but got {cycle['draw_posture']}"
    )
    assert cycle["total_allocated_cases"] == 0, (
        f"total_allocated_cases must stay 0 but got {cycle['total_allocated_cases']}"
    )
    assert cycle["eligible_agency_count"] == 0, (
        f"eligible_agency_count must stay 0 but got {cycle['eligible_agency_count']}"
    )
    assert cycle["allocation_locked_at"] is None, (
        f"allocation_locked_at must stay null but got {cycle['allocation_locked_at']}"
    )
    _rows, meta = fx.list_rows_and_meta(
        api.list_cycle_allocations(env["cycle"]["id"], headers=fx.ADMIN)
    )
    assert meta["total_count"] == 0, (
        f"no entitlement row may exist but total_count is {meta['total_count']}"
    )


def test_06_the_only_agency_is_ineligible_so_the_area_counts_nobody(api):
    """PRD §3.4: "The **included set** is every agency whose `eligibility_posture` is
    `ELIGIBLE` at the instant the run executes." PRD §3.2: "In every other
    combination — including an `ACTIVE` agreement whose training is still `REQUIRED`,
    and any agency whose agreement is `PENDING`, `EXPIRED`, or `TERMINATED` — the
    posture is `INELIGIBLE`."

    Design: Difficulty/boundary_precision_check/compute_allocations_with_empty_eligible_set_is_rejected
    """
    env = _cycle_with_no_eligible_agency(api)

    api.compute_allocations(env["cycle"]["id"], headers=fx.ADMIN, payload={})

    agency = fx.read_agency(api, env["agency"]["id"])
    assert agency["eligibility_posture"] == EligibilityPosture.INELIGIBLE, (
        f"eligibility_posture expected INELIGIBLE but got {agency['eligibility_posture']}"
    )
    area = fx.read_service_area(api, env["area"]["id"])
    assert area["eligible_agency_count"] == 0, (
        f"eligible_agency_count expected 0 but got {area['eligible_agency_count']}"
    )


def _agency_holding_twenty_rice_cases(api):
    """An eligible agency with 20 cases on hand and an entitlement row in the cycle."""
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
        cycle_code="FY27HH3",
        formula_variant=FormulaVariant.STANDARD,
        allocatable_cases=1001,
        admin_funds_pool_cents=5000000,
        offered_commodity_codes=["BULK_RICE"],
    )
    fx.compute_allocations(api, cycle["id"])
    fx.set_clock(api, "2026-08-10T00:00:00Z")
    return {"agency": agency, "cycle": cycle, "commodity": rice}


def _distribution_at(api, env, income_cents, *, participates_in_snap):
    return api.create_household_distribution(
        f.household_distribution_payload(
            env["agency"]["id"],
            env["cycle"]["id"],
            env["commodity"]["id"],
            household_size=3,
            declared_monthly_income_cents=income_cents,
            participates_in_snap=participates_in_snap,
            self_declaration_signed=True,
            cases_distributed=2,
            distribution_date="2026-08-10",
        ),
        headers=make_agency_coordinator_headers(env["agency"]["id"]),
    )


def test_07_income_exactly_at_the_limit_is_eligible(api):
    """PRD §3.9: "The record's `income_limit_cents` is a base limit of 195,000 cents
    per month plus 68,000 cents for each person in the household beyond the first —
    that is, the base plus `household_size` less one, multiplied by the per-person
    figure." PRD §3.9: "If `declared_monthly_income_cents` is at or below that limit,
    `eligibility_determination` is written as `ELIGIBLE`; the boundary is inclusive."

    Design: Difficulty/boundary_precision_check/household_income_limit_is_inclusive_and_one_cent_over_is_refused
    """
    env = _agency_holding_twenty_rice_cases(api)

    row = validate_success(_distribution_at(api, env, 331000, participates_in_snap=False), 201)

    assert row["income_limit_cents"] == 331000, (
        f"income_limit_cents expected 331000 but got {row['income_limit_cents']}"
    )
    assert_income_limit(row)
    assert row["eligibility_determination"] == EligibilityDetermination.ELIGIBLE, (
        "eligibility_determination expected ELIGIBLE but got "
        f"{row['eligibility_determination']}"
    )
    assert_pounds(row["pounds_distributed"], 40.0, "pounds_distributed")
    assert row["status"] == DistributionStatus.RECORDED, (
        f"status expected RECORDED but got {row['status']}"
    )


def test_08_one_cent_over_the_limit_without_snap_is_refused(api):
    """PRD §3.9: "If the declared income exceeds the limit and `participates_in_snap`
    is `false`, the request is refused with `ERR_HOUSEHOLD_INELIGIBLE`, no row is
    persisted, and no rollup figure or on-hand counter moves at all."

    Design: Difficulty/boundary_precision_check/household_income_limit_is_inclusive_and_one_cent_over_is_refused
    """
    env = _agency_holding_twenty_rice_cases(api)
    validate_success(_distribution_at(api, env, 331000, participates_in_snap=False), 201)

    response = _distribution_at(api, env, 331001, participates_in_snap=False)

    validate_error(response, ApiErrorId.ERR_HOUSEHOLD_INELIGIBLE, 422)
    allocation = fx.read_allocation(api, env["cycle"]["id"], env["agency"]["id"])
    assert allocation["distribution_record_count"] == 1, (
        "distribution_record_count must stay 1 but got "
        f"{allocation['distribution_record_count']}"
    )
    agency = fx.read_agency(api, env["agency"]["id"])
    assert agency["agency_cases_on_hand"] == 18, (
        f"agency_cases_on_hand must stay 18 but got {agency['agency_cases_on_hand']}"
    )


def test_09_the_same_income_with_snap_qualifies_categorically(api):
    """PRD §3.9: "If the declared income exceeds the limit but `participates_in_snap`
    is `true`, the household qualifies categorically regardless of income and
    `eligibility_determination` is written as `CATEGORICALLY_ELIGIBLE`." PRD §3.9:
    "Worked at a `household_size` of 3, the limit comes to 331,000 cents: a declared
    331,000 is `ELIGIBLE`, a declared 331,001 is refused, and a declared 331,001 with
    SNAP participation is `CATEGORICALLY_ELIGIBLE`."

    Design: Difficulty/boundary_precision_check/household_income_limit_is_inclusive_and_one_cent_over_is_refused
    """
    env = _agency_holding_twenty_rice_cases(api)
    validate_success(_distribution_at(api, env, 331000, participates_in_snap=False), 201)
    _distribution_at(api, env, 331001, participates_in_snap=False)

    row = validate_success(_distribution_at(api, env, 331001, participates_in_snap=True), 201)

    assert row["eligibility_determination"] == EligibilityDetermination.CATEGORICALLY_ELIGIBLE, (
        "eligibility_determination expected CATEGORICALLY_ELIGIBLE but got "
        f"{row['eligibility_determination']}"
    )
    assert row["income_limit_cents"] == 331000, (
        f"income_limit_cents expected 331000 but got {row['income_limit_cents']}"
    )
    _rows, meta = fx.list_rows_and_meta(
        api.list_household_distributions(
            headers=fx.ADMIN, params={"agency_id": env["agency"]["id"]}
        )
    )
    assert meta["total_count"] == 2, (
        f"exactly the two accepted rows may exist but total_count is {meta['total_count']}"
    )
    allocation = fx.read_allocation(api, env["cycle"]["id"], env["agency"]["id"])
    assert allocation["distribution_record_count"] == 2, (
        f"distribution_record_count expected 2 but got {allocation['distribution_record_count']}"
    )
    assert_pounds(allocation["distributed_pounds"], 80.0, "distributed_pounds")
    assert_ratio(allocation["record_compliance_pct"], 1.0, "record_compliance_pct")
    agency = fx.read_agency(api, env["agency"]["id"])
    assert agency["agency_cases_on_hand"] == 16, (
        f"agency_cases_on_hand expected 16 but got {agency['agency_cases_on_hand']}"
    )
