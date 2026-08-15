"""Closeout: the variance gate and its regulatory coverage, CIAC application,
the unitization waterfall with its pinned remainder rule, in-service dating,
and unit retirement (PRD §3.7, §3.8, §3.9)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_reg_asset,
    assert_fixed_asset_unit,
    closeout_work_order,
    complete_work_order,
    create_catalog_entry,
    create_ciac,
    create_received_ciac,
    create_reg_asset,
    get_program,
    get_success_data,
    get_work_order,
    make_unitization_line,
    post_charge,
    setup_charging_world,
    setup_closeout_overrun_world,
    setup_completed_work_order,
    setup_unitized_transformer_world,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ENGINEER = TEST_USERS["engineer_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]
CONTROLLER = TEST_USERS["controller_headers"]
CLERK = TEST_USERS["clerk_headers"]
RATES = TEST_USERS["rates_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestCloseoutUnitizationCardinality:
    def test_capital_closeout_rejects_empty_unitization(self, api):
        """PRD §3.8: "Then the referential checks: no CIAC agreement of the order may still stand `PLEDGED` (`ERR_CIAC_PLEDGED_OUTSTANDING`); a `CAPITAL` order requires a non-empty `unitization_lines` while an `EXPENSE` order requires it empty, either violation rejected as `ERR_UNITIZATION_EMPTY`; every line must carry a `quantity` of at least one and reference an existing `unit_catalog_id`; and the lines' total target — the sum over the lines of each `quantity` multiplied by its catalog row's `standard_cost_cents` — must be greater than zero, else `ERR_UNITIZATION_ZERO_TARGET`, a condition reachable only when every referenced catalog row has a zero standard cost."
        PRD §3.8: "The gate passes outright whenever the overrun scaled by one hundred is less than or equal to the approved estimate scaled by fifteen, so underruns never block closeout."

        Design: Difficulty/boundary_precision_check/closeout_empty_unitization_set
        """
        create_catalog_entry()  # TRANSFORMER 50,000c @ 12%/yr
        world = setup_completed_work_order(estimate_cents=500_000, charges=())
        wo = world["work_order"]
        assert wo["status"] == "COMPLETED"
        assert wo["actual_direct_cents"] == 0

        resp = api.closeout_work_order(wo["id"], [], CONTROLLER)
        validate_error(resp, ApiErrorId.ERR_UNITIZATION_EMPTY, 422)
        assert get_work_order(wo["id"])["status"] == "COMPLETED", (
            "a rejected closeout leaves the order untouched")

    def test_capital_closeout_accepts_single_line(self, api):
        """PRD §3.8: "Then the referential checks: no CIAC agreement of the order may still stand `PLEDGED` (`ERR_CIAC_PLEDGED_OUTSTANDING`); a `CAPITAL` order requires a non-empty `unitization_lines` while an `EXPENSE` order requires it empty, either violation rejected as `ERR_UNITIZATION_EMPTY`; every line must carry a `quantity` of at least one and reference an existing `unit_catalog_id`; and the lines' total target — the sum over the lines of each `quantity` multiplied by its catalog row's `standard_cost_cents` — must be greater than zero, else `ERR_UNITIZATION_ZERO_TARGET`, a condition reachable only when every referenced catalog row has a zero standard cost."
        PRD §3.8: "On success the order's construction balance is snapshotted and the customer money settles. The `gross_cwip_cents` becomes the final `cwip_cents`, frozen at this instant. The `ciac_applied_cents` becomes the lesser of the total `received_cents` across the order's `RECEIVED` agreements and that gross CWIP."
        PRD §3.8: "One **Fixed Asset Unit** is created per line, carrying the final `allocated_cost_cents`, `status` `IN_SERVICE`, the `in_service_period_id` copied from the work order, the order reference recorded as its `work_order_id`, and a `line_no` equal to the line's zero-based index within the request's `unitization_lines` array."

        Design: Difficulty/boundary_precision_check/closeout_empty_unitization_set
        """
        catalog = create_catalog_entry()
        world = setup_completed_work_order(estimate_cents=500_000, charges=())
        wo = world["work_order"]

        closed = validate_success(api.closeout_work_order(
            wo["id"], [make_unitization_line(catalog["id"], 1)], CONTROLLER))
        assert closed["status"] == "CLOSED"
        assert closed["gross_cwip_cents"] == 0
        assert closed["ciac_applied_cents"] == 0
        assert closed["capitalizable_total_cents"] == 0, (
            "NET_OF_CIAC: gross 0 minus 0 applied")
        assert closed["closed_by_user_id"] == "ctrl-1"

        units, meta = validate_paginated(api.list_fixed_asset_units(
            AUDITOR, params={"work_order_id": wo["id"]}))
        assert meta["total_count"] == 1
        assert_fixed_asset_unit(units[0])
        assert units[0]["status"] == "IN_SERVICE"
        assert units[0]["allocated_cost_cents"] == 0
        assert units[0]["in_service_period_id"] == world["period"]["id"]


class TestUnitizationWaterfall:
    def _waterfall_world(self, api):
        """CAPITAL order with exactly 100,003c of actuals, completed — the PRD
        §3.8 pinned worked example."""
        cat_t = create_catalog_entry(asset_class="TRANSFORMER",
                                     standard_cost_cents=50_000,
                                     annual_depreciation_rate_pct=12.0)
        cat_p = create_catalog_entry(asset_class="POLE",
                                     standard_cost_cents=10_000,
                                     annual_depreciation_rate_pct=4.0)
        cat_c = create_catalog_entry(asset_class="CONDUCTOR",
                                     standard_cost_cents=6_000,
                                     annual_depreciation_rate_pct=3.0)
        world = setup_completed_work_order(
            estimate_cents=500_000,
            charges=({"base_amount_cents": 100_003, "charge_date": "2026-08-10"},))
        world["catalogs"] = (cat_t, cat_p, cat_c)
        return world

    def _closeout_lines(self, world):
        cat_t, cat_p, cat_c = world["catalogs"]
        return [make_unitization_line(cat_t["id"], 1),
                make_unitization_line(cat_p["id"], 2),
                make_unitization_line(cat_c["id"], 5)]

    def test_unitization_remainder_lands_on_greatest_target_line(self, api):
        """PRD §3.8: "A pinned worked example: with a total of 100,003 cents and line targets of 50,000, 20,000, and 30,000 (an S of 100,000), the raw allocations are 50,002, 20,001, and 30,001; the remainder of minus one cent lands on the `TRANSFORMER` line as the greatest target, producing final allocations of 50,001, 20,001, and 30,001 that sum to exactly 100,003."
        PRD §3.8: "The remainder, defined as the capitalizable total minus the sum of the raw allocations and therefore possibly negative, is applied in full to the line with the greatest target; a tie breaks toward the greatest `standard_cost_cents`, and a further tie breaks toward the `asset_class` that sorts earliest alphabetically."
        PRD §2.3: "Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order; fixed-asset-unit lists additionally break ties by `line_no` ascending, so the lines of a single closeout appear in their submitted order."

        Design: Difficulty/combinatorial_formula/unitization_largest_remainder_waterfall
        """
        world = self._waterfall_world(api)
        wo = world["work_order"]
        cat_t, cat_p, cat_c = world["catalogs"]

        closed = validate_success(api.closeout_work_order(
            wo["id"], self._closeout_lines(world), CONTROLLER))
        assert closed["status"] == "CLOSED"
        assert closed["capitalizable_total_cents"] == 100_003

        units, _ = validate_paginated(api.list_fixed_asset_units(
            AUDITOR, params={"work_order_id": wo["id"]}))
        assert len(units) == 3
        # Submitted order: TRANSFORMER, POLE, CONDUCTOR.
        assert [u["line_no"] for u in units] == [0, 1, 2]
        assert units[0]["unit_catalog_id"] == cat_t["id"]
        assert units[1]["unit_catalog_id"] == cat_p["id"]
        assert units[2]["unit_catalog_id"] == cat_c["id"]
        assert units[0]["quantity"] == 1
        assert units[1]["quantity"] == 2
        assert units[2]["quantity"] == 5
        assert units[0]["allocated_cost_cents"] == 50_001, (
            "the -1c remainder lands on the greatest-target line")
        assert units[1]["allocated_cost_cents"] == 20_001
        assert units[2]["allocated_cost_cents"] == 30_001

    def test_unitization_allocation_conserves_total(self, api):
        """PRD §3.8: "A pinned worked example: with a total of 100,003 cents and line targets of 50,000, 20,000, and 30,000 (an S of 100,000), the raw allocations are 50,002, 20,001, and 30,001; the remainder of minus one cent lands on the `TRANSFORMER` line as the greatest target, producing final allocations of 50,001, 20,001, and 30,001 that sum to exactly 100,003."
        PRD §3.8: "The program rollup completes the order's ledger: the program's `committed_amount_cents` decreases by the `approved_estimate_cents` and its `capitalized_actual_cents` increases by the `capitalizable_total_cents`; the order records its `closed_by_user_id` and its version increments by one."

        Design: Difficulty/combinatorial_formula/unitization_largest_remainder_waterfall
        """
        world = self._waterfall_world(api)
        program, wo = world["program"], world["work_order"]

        closed = validate_success(api.closeout_work_order(
            wo["id"], self._closeout_lines(world), CONTROLLER))
        assert closed["capitalizable_total_cents"] == 100_003

        units, _ = validate_paginated(api.list_fixed_asset_units(
            AUDITOR, params={"work_order_id": wo["id"]}))
        total = sum(u["allocated_cost_cents"] for u in units)
        assert total == 100_003, "the waterfall conserves the capitalizable total"
        assert total == closed["capitalizable_total_cents"]

        program_view = get_program(program["id"])
        assert program_view["capitalized_actual_cents"] == 100_003
        assert program_view["committed_amount_cents"] == 0, (
            "closeout releases the 500,000c commitment")


class TestUnitizationZeroTarget:
    def test_unitization_zero_target_rejected(self, api):
        """PRD §3.8: "Then the referential checks: no CIAC agreement of the order may still stand `PLEDGED` (`ERR_CIAC_PLEDGED_OUTSTANDING`); a `CAPITAL` order requires a non-empty `unitization_lines` while an `EXPENSE` order requires it empty, either violation rejected as `ERR_UNITIZATION_EMPTY`; every line must carry a `quantity` of at least one and reference an existing `unit_catalog_id`; and the lines' total target — the sum over the lines of each `quantity` multiplied by its catalog row's `standard_cost_cents` — must be greater than zero, else `ERR_UNITIZATION_ZERO_TARGET`, a condition reachable only when every referenced catalog row has a zero standard cost."
        PRD §3.1: "A `SystemAdmin` creates each entry with an `asset_class` — one of `POLE`, `TRANSFORMER`, `CONDUCTOR`, `METER`, or `REGULATOR`, unique across the catalog, with duplicates rejected as `ERR_VALIDATION` — a `standard_cost_cents` per unit that serves as the unitization weight and may be zero (a closeout whose lines all weight to zero is nonetheless rejected; see §3.8), and an `annual_depreciation_rate_pct`, the straight-line annual depreciation rate percentage, which must be greater than zero."

        Design: Corner/validations/unitization_zero_target_rejected
        """
        cat_m = create_catalog_entry(asset_class="METER", standard_cost_cents=0,
                                     annual_depreciation_rate_pct=6.0)
        cat_t = create_catalog_entry(asset_class="TRANSFORMER",
                                     standard_cost_cents=50_000,
                                     annual_depreciation_rate_pct=12.0)
        world = setup_completed_work_order(
            estimate_cents=500_000,
            charges=({"base_amount_cents": 120_000, "charge_date": "2026-08-05"},))
        wo = world["work_order"]

        # 3 zero-weight METER units: total target 0.
        resp = api.closeout_work_order(
            wo["id"], [make_unitization_line(cat_m["id"], 3)], CONTROLLER)
        validate_error(resp, ApiErrorId.ERR_UNITIZATION_ZERO_TARGET, 422)

        closed = validate_success(api.closeout_work_order(
            wo["id"], [make_unitization_line(cat_m["id"], 3),
                       make_unitization_line(cat_t["id"], 1)], CONTROLLER))
        assert closed["status"] == "CLOSED"

        units, _ = validate_paginated(api.list_fixed_asset_units(
            AUDITOR, params={"work_order_id": wo["id"]}))
        assert len(units) == 2
        assert units[0]["unit_catalog_id"] == cat_m["id"]
        assert units[0]["allocated_cost_cents"] == 0, "a zero-weight line gets 0c"
        assert units[1]["unit_catalog_id"] == cat_t["id"]
        assert units[1]["allocated_cost_cents"] == 120_000


class TestCloseoutCiacSettlement:
    def test_ciac_closeout_excess_refund(self, api):
        """PRD §3.8: "The `ciac_applied_cents` becomes the lesser of the total `received_cents` across the order's `RECEIVED` agreements and that gross CWIP. Each `RECEIVED` agreement moves to `APPLIED`, recording its `applied_cents` as the lesser of what it received and the gross CWIP share, and its `refunded_cents` as the received amount minus the applied amount — the closeout excess refund, with no forfeiture."
        PRD §3.7: "At closeout, by contrast, no forfeiture ever applies — excess contributions are simply refunded (§3.8)."

        Design: Corner/calculations/ciac_closeout_excess_refund
        """
        catalog = create_catalog_entry()
        world = setup_charging_world(estimate_cents=500_000)
        wo = world["work_order"]
        post_charge(wo["id"], base_amount_cents=120_000, charge_date="2026-08-05")
        ciac = create_received_ciac(wo["id"], pledged_cents=150_000)
        complete_work_order(wo["id"], "2026-08-20")

        closed = validate_success(api.closeout_work_order(
            wo["id"], [make_unitization_line(catalog["id"], 1)], CONTROLLER))
        assert closed["gross_cwip_cents"] == 120_000
        assert closed["ciac_applied_cents"] == 120_000, "capped at gross CWIP"
        assert closed["capitalizable_total_cents"] == 0

        ciac_view = validate_success(api.get_ciac_agreement(ciac["id"], AUDITOR))
        assert ciac_view["status"] == "APPLIED"
        assert ciac_view["applied_cents"] == 120_000
        assert ciac_view["refunded_cents"] == 30_000, "the excess is refunded"

        units, _ = validate_paginated(api.list_fixed_asset_units(
            AUDITOR, params={"work_order_id": wo["id"]}))
        assert units[0]["allocated_cost_cents"] == 0

    def test_ciac_pledged_outstanding_blocks_closeout(self, api):
        """PRD §3.8: "Then the referential checks: no CIAC agreement of the order may still stand `PLEDGED` (`ERR_CIAC_PLEDGED_OUTSTANDING`); a `CAPITAL` order requires a non-empty `unitization_lines` while an `EXPENSE` order requires it empty, either violation rejected as `ERR_UNITIZATION_EMPTY`; every line must carry a `quantity` of at least one and reference an existing `unit_catalog_id`; and the lines' total target — the sum over the lines of each `quantity` multiplied by its catalog row's `standard_cost_cents` — must be greater than zero, else `ERR_UNITIZATION_ZERO_TARGET`, a condition reachable only when every referenced catalog row has a zero standard cost."
        PRD §3.6: "And the work order must stand at `DRAFT`, `SUBMITTED`, `RETURNED`, `AUTHORIZED`, `IN_PROGRESS`, `SUSPENDED`, or `COMPLETED` — funds may legitimately arrive after the in-service date but before closeout — with any other order state rejected as `ERR_INVALID_STATE`."

        Design: Corner/validations/ciac_pledged_outstanding_blocks_closeout
        """
        catalog = create_catalog_entry()
        world = setup_charging_world(estimate_cents=500_000)
        wo = world["work_order"]
        post_charge(wo["id"], base_amount_cents=120_000, charge_date="2026-08-05")
        ciac = create_ciac(wo["id"], pledged_cents=50_000)
        complete_work_order(wo["id"], "2026-08-20")

        resp = api.closeout_work_order(
            wo["id"], [make_unitization_line(catalog["id"], 1)], CONTROLLER)
        validate_error(resp, ApiErrorId.ERR_CIAC_PLEDGED_OUTSTANDING, 422)

        # Receipt is still legal while the order is COMPLETED.
        received = validate_success(api.receive_ciac_agreement(ciac["id"], RATES))
        assert received["status"] == "RECEIVED"
        assert received["received_cents"] == 50_000

        closed = validate_success(api.closeout_work_order(
            wo["id"], [make_unitization_line(catalog["id"], 1)], CONTROLLER))
        assert closed["status"] == "CLOSED"
        assert closed["ciac_applied_cents"] == 50_000
        assert closed["capitalizable_total_cents"] == 70_000, "120,000 - 50,000"


class TestCloseoutVarianceGate:
    def test_closeout_rejected_with_proposed_coverage(self, api):
        """PRD §3.8: "Beyond tolerance, the order must carry regulatory coverage for the excess: the coverage needed is the overrun minus the tolerance, and the coverage available is the sum of `original_cents` over regulatory assets whose `source_work_order_id` is this order and whose `status` is `APPROVED`, `AMORTIZING`, or `FULLY_AMORTIZED`. With no qualifying coverage at all the closeout is rejected `ERR_CLOSEOUT_VARIANCE_EXCEEDS_TOLERANCE`; coverage that exists but sums below the needed amount is `ERR_REGULATORY_COVERAGE_INSUFFICIENT`; and coverage at least equal to the need passes — the boundary is inclusive. A concrete instance: an approved estimate of 100,000 cents against 116,000 cents of actuals yields a 15,000-cent tolerance and a 1,000-cent coverage requirement."

        Design: Difficulty/cross_entity_state_dependency/closeout_gated_by_regulatory_asset_state
        """
        world = setup_closeout_overrun_world(coverage_cents=1_000,
                                             coverage_approved=False)
        wo, catalog = world["work_order"], world["catalog"]
        assert world["reg_asset"]["status"] == "PROPOSED"
        assert get_work_order(wo["id"])["actual_direct_cents"] == 116_000

        # PROPOSED coverage does not count — there is no qualifying coverage.
        resp = api.closeout_work_order(
            wo["id"], [make_unitization_line(catalog["id"], 1)], CONTROLLER)
        validate_error(resp, ApiErrorId.ERR_CLOSEOUT_VARIANCE_EXCEEDS_TOLERANCE, 422)
        assert get_work_order(wo["id"])["status"] == "COMPLETED"

    def test_closeout_passes_with_approved_coverage_at_exact_need(self, api):
        """PRD §3.8: "Beyond tolerance, the order must carry regulatory coverage for the excess: the coverage needed is the overrun minus the tolerance, and the coverage available is the sum of `original_cents` over regulatory assets whose `source_work_order_id` is this order and whose `status` is `APPROVED`, `AMORTIZING`, or `FULLY_AMORTIZED`. With no qualifying coverage at all the closeout is rejected `ERR_CLOSEOUT_VARIANCE_EXCEEDS_TOLERANCE`; coverage that exists but sums below the needed amount is `ERR_REGULATORY_COVERAGE_INSUFFICIENT`; and coverage at least equal to the need passes — the boundary is inclusive. A concrete instance: an approved estimate of 100,000 cents against 116,000 cents of actuals yields a 15,000-cent tolerance and a 1,000-cent coverage requirement."
        PRD §3.8: "The program rollup completes the order's ledger: the program's `committed_amount_cents` decreases by the `approved_estimate_cents` and its `capitalized_actual_cents` increases by the `capitalizable_total_cents`; the order records its `closed_by_user_id` and its version increments by one."

        Design: Difficulty/cross_entity_state_dependency/closeout_gated_by_regulatory_asset_state
        """
        world = setup_closeout_overrun_world(coverage_cents=1_000,
                                             coverage_approved=True)
        program, wo, catalog = world["program"], world["work_order"], world["catalog"]
        assert world["reg_asset"]["status"] == "APPROVED"

        # Coverage of exactly 1,000c meets the 1,000c need — equality passes.
        closed = validate_success(api.closeout_work_order(
            wo["id"], [make_unitization_line(catalog["id"], 1)], CONTROLLER))
        assert closed["status"] == "CLOSED"
        assert closed["capitalizable_total_cents"] == 116_000

        program_view = get_program(program["id"])
        assert program_view["capitalized_actual_cents"] == 116_000
        assert program_view["committed_amount_cents"] == 0

    def test_closeout_coverage_insufficient_then_topped_up(self, api):
        """PRD §3.8: "Beyond tolerance, the order must carry regulatory coverage for the excess: the coverage needed is the overrun minus the tolerance, and the coverage available is the sum of `original_cents` over regulatory assets whose `source_work_order_id` is this order and whose `status` is `APPROVED`, `AMORTIZING`, or `FULLY_AMORTIZED`. With no qualifying coverage at all the closeout is rejected `ERR_CLOSEOUT_VARIANCE_EXCEEDS_TOLERANCE`; coverage that exists but sums below the needed amount is `ERR_REGULATORY_COVERAGE_INSUFFICIENT`; and coverage at least equal to the need passes — the boundary is inclusive. A concrete instance: an approved estimate of 100,000 cents against 116,000 cents of actuals yields a 15,000-cent tolerance and a 1,000-cent coverage requirement."

        Design: Corner/calculations/closeout_coverage_insufficient_then_topped_up
        """
        world = setup_closeout_overrun_world(coverage_cents=999,
                                             coverage_approved=True)
        wo, catalog = world["work_order"], world["catalog"]

        # 999c of approved coverage against a 1,000c need.
        resp = api.closeout_work_order(
            wo["id"], [make_unitization_line(catalog["id"], 1)], CONTROLLER)
        validate_error(resp, ApiErrorId.ERR_REGULATORY_COVERAGE_INSUFFICIENT, 422)

        # A second approved deferral of 1c tops coverage up to exactly the need.
        ra2 = create_reg_asset(description="Top-up cover", original_cents=1,
                               amortization_months=12,
                               source_work_order_id=wo["id"])
        approve_reg_asset(ra2["id"])

        closed = validate_success(api.closeout_work_order(
            wo["id"], [make_unitization_line(catalog["id"], 1)], CONTROLLER))
        assert closed["status"] == "CLOSED"


class TestCompletionDating:
    def test_complete_in_service_outside_open_period_rejected(self, api):
        """PRD §3.7: "A `WorkOrderSupervisor` completes an order (`IN_PROGRESS` → `COMPLETED`) by supplying the `in_service_date`, which must fall inside the single accounting period currently `OPEN` or `REOPENED`; a date outside that period is rejected with `ERR_IN_SERVICE_PERIOD_NOT_OPEN`. On success the containing period's id is recorded as the order's `in_service_period_id`, the caller is recorded as `completed_by_user_id`, and the version increments."

        Design: Corner/validations/complete_in_service_outside_open_period_rejected
        """
        world = setup_charging_world(estimate_cents=500_000)
        wo, period = world["work_order"], world["period"]

        # 2026-07-15 is outside the only OPEN period (2026-08).
        resp = api.complete_work_order(wo["id"], "2026-07-15", SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_IN_SERVICE_PERIOD_NOT_OPEN, 422)

        completed = validate_success(
            api.complete_work_order(wo["id"], "2026-08-20", SUPERVISOR))
        assert completed["status"] == "COMPLETED"
        assert completed["in_service_date"] == "2026-08-20"
        assert completed["in_service_period_id"] == period["id"]
        assert completed["completed_by_user_id"] == "sup-1"


class TestUnitRetirement:
    def test_unit_retire_period_guard_and_terminal_lockdown(self, api):
        """PRD §3.8: "A unit's service life ends when a `Controller` retires it (`IN_SERVICE` → `RETIRED`) by supplying a `retirement_date` that must fall inside the single accounting period currently `OPEN` or `REOPENED`, else `ERR_RETIREMENT_PERIOD_NOT_OPEN`; retiring a unit already `RETIRED` is rejected with `ERR_UNIT_ALREADY_RETIRED`."

        Design: Corner/state_machines/unit_retire_period_guard_and_terminal_lockdown
        """
        world = setup_unitized_transformer_world(
            estimate_cents=500_000,
            charges=({"base_amount_cents": 120_000, "charge_date": "2026-08-05"},))
        unit = world["units"][0]
        assert unit["status"] == "IN_SERVICE"
        assert unit["in_service_period_id"] == world["period"]["id"]

        # 2026-12-01 falls outside the currently OPEN 2026-08 period.
        resp = api.retire_fixed_asset_unit(unit["id"], "2026-12-01", CONTROLLER)
        validate_error(resp, ApiErrorId.ERR_RETIREMENT_PERIOD_NOT_OPEN, 422)

        retired = validate_success(
            api.retire_fixed_asset_unit(unit["id"], "2026-08-25", CONTROLLER))
        assert retired["status"] == "RETIRED"
        assert retired["retirement_period_id"] == world["period"]["id"]

        resp2 = api.retire_fixed_asset_unit(unit["id"], "2026-08-26", CONTROLLER)
        validate_error(resp2, ApiErrorId.ERR_UNIT_ALREADY_RETIRED, 409)
