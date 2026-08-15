"""The period-close checkpoint: AFUDC accrual (both conventions, the pinned
base evaluation order, CIAC exclusion), depreciation (half-month factors, NET
vs GROSS CIAC basis), amortization scheduling, reopen compensation, and the
EXPENSE-order carve-outs (PRD §3.8, §3.9)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    close_period,
    closeout_work_order,
    complete_work_order,
    create_approved_reg_asset,
    create_catalog_entry,
    create_in_progress_work_order,
    create_period,
    create_program,
    create_received_ciac,
    create_schedule,
    get_success_data,
    get_work_order,
    list_afudc_entries,
    list_amortization_entries,
    list_depreciation_entries,
    make_unitization_line,
    post_charge,
    reopen_period,
    setup_charging_world,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ENGINEER = TEST_USERS["engineer_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]
CONTROLLER = TEST_USERS["controller_headers"]
CLERK = TEST_USERS["clerk_headers"]
RATES = TEST_USERS["rates_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def _afudc_world(afudc_method):
    """An IN_PROGRESS CAPITAL order under a program with the given AFUDC base
    convention, holding one 200,000c MATERIAL charge in period 2026-08."""
    world = setup_charging_world(
        estimate_cents=9_000_000,
        program_overrides={"afudc_method": afudc_method})
    post_charge(world["work_order"]["id"], base_amount_cents=200_000,
                charge_date="2026-08-10")
    return world


class TestAfudcBaseConventions:
    def test_afudc_half_month_base_convention(self, api):
        """PRD §3.9: "Fourth, the base follows the program's `afudc_method`: under `HALF_MONTH` it is the net beginning plus one half of the period's charges, a mid-period convention; under `FULL_MONTH` it is the net beginning plus the period's full charges."
        PRD §3.9: "The two conventions diverge predictably: 200,000 cents of current-period charges at a one-percent monthly rate accrue 1,000 cents under the half-month convention, while identical inputs accrue 2,000 cents under the full-month convention — exactly double the half-month result when the beginning CWIP is zero."
        PRD §3.9: "Each created AFUDC entry records its `work_order_id`, the closing period's id as `accounting_period_id`, a snapshot of the program's convention in `method` (`HALF_MONTH` or `FULL_MONTH`), the `base_cents` used, the `rate_pct_applied`, and a `status` of `ACCRUED`; the order's `afudc_total_cents` and `cwip_cents` update accordingly."

        Design: Difficulty/dual_variant_calc/afudc_half_vs_full_month_base
        """
        world = _afudc_world("HALF_MONTH")
        wo, period = world["work_order"], world["period"]

        close_period(period["id"])
        entries = list_afudc_entries(work_order_id=wo["id"],
                                     accounting_period_id=period["id"])
        assert len(entries) == 1
        entry = entries[0]
        assert entry["method"] == "HALF_MONTH"
        assert entry["base_cents"] == 100_000, "0 + 0.5 * 200,000"
        assert entry["rate_pct_applied"] == 1.0
        assert entry["amount_cents"] == 1_000
        assert entry["status"] == "ACCRUED"

        wo_view = get_work_order(wo["id"])
        assert wo_view["afudc_total_cents"] == 1_000
        assert wo_view["cwip_cents"] == 201_000

    def test_afudc_full_month_base_convention(self, api):
        """PRD §3.9: "Fourth, the base follows the program's `afudc_method`: under `HALF_MONTH` it is the net beginning plus one half of the period's charges, a mid-period convention; under `FULL_MONTH` it is the net beginning plus the period's full charges."
        PRD §3.9: "The two conventions diverge predictably: 200,000 cents of current-period charges at a one-percent monthly rate accrue 1,000 cents under the half-month convention, while identical inputs accrue 2,000 cents under the full-month convention — exactly double the half-month result when the beginning CWIP is zero."

        Design: Difficulty/dual_variant_calc/afudc_half_vs_full_month_base
        """
        world = _afudc_world("FULL_MONTH")
        wo, period = world["work_order"], world["period"]

        close_period(period["id"])
        entries = list_afudc_entries(work_order_id=wo["id"],
                                     accounting_period_id=period["id"])
        assert len(entries) == 1
        entry = entries[0]
        assert entry["method"] == "FULL_MONTH"
        assert entry["base_cents"] == 200_000, "0 + 1.0 * 200,000"
        assert entry["amount_cents"] == 2_000, (
            "exactly double the half-month result when the beginning CWIP is zero")
        assert entry["status"] == "ACCRUED"

        wo_view = get_work_order(wo["id"])
        assert wo_view["afudc_total_cents"] == 2_000
        assert wo_view["cwip_cents"] == 202_000


class TestAfudcCompoundingOrder:
    def test_afudc_period1_base_excludes_own_accrual(self, api):
        """PRD §3.9: "First, the beginning CWIP is the order's `cwip_cents` before this period's accrual — it includes all prior periods' AFUDC, because AFUDC compounds across periods, and it never includes this period's own accrual."

        Design: Difficulty/combinatorial_formula/afudc_circular_base_order
        """
        world = _afudc_world("HALF_MONTH")
        wo, period = world["work_order"], world["period"]

        close_period(period["id"])
        entries = list_afudc_entries(work_order_id=wo["id"],
                                     accounting_period_id=period["id"])
        assert len(entries) == 1
        assert entries[0]["base_cents"] == 100_000, (
            "begin 0 plus half of the 200,000c current-period charges; this "
            "period's own accrual is never in its own base")
        assert entries[0]["amount_cents"] == 1_000

    def test_afudc_period2_compounds_prior_accrual(self, api):
        """PRD §3.9: "First, the beginning CWIP is the order's `cwip_cents` before this period's accrual — it includes all prior periods' AFUDC, because AFUDC compounds across periods, and it never includes this period's own accrual."
        PRD §3.9: "Periods accrue in chronological close order: each period's beginning position is the prior period's ending position."

        Design: Difficulty/combinatorial_formula/afudc_circular_base_order
        """
        world = _afudc_world("HALF_MONTH")
        wo, period = world["work_order"], world["period"]

        close_period(period["id"])
        period9 = create_period(fiscal_year=2026, period_no=9,
                                start_date="2026-09-01", end_date="2026-09-30")
        close_period(period9["id"])

        entries = list_afudc_entries(work_order_id=wo["id"],
                                     accounting_period_id=period9["id"])
        assert len(entries) == 1
        assert entries[0]["base_cents"] == 201_000, (
            "prior AFUDC of 1,000c compounds into the second period's begin "
            "balance even with zero period-2 charges")
        assert entries[0]["amount_cents"] == 2_010

        wo_view = get_work_order(wo["id"])
        assert wo_view["afudc_total_cents"] == 3_010
        assert wo_view["cwip_cents"] == 203_010


class TestAfudcCiacExclusion:
    def test_afudc_ciac_exclusion_from_begin_balance(self, api):
        """PRD §3.9: "Second, the net beginning is the greater of zero and the beginning CWIP minus the CIAC received to date — the sum of `received_cents` over the order's agreements in `RECEIVED` or `APPLIED` — because CIAC-financed CWIP earns no AFUDC."

        Design: Corner/calculations/afudc_ciac_exclusion_from_begin_balance
        """
        world = _afudc_world("HALF_MONTH")
        wo, period = world["work_order"], world["period"]
        create_received_ciac(wo["id"], pledged_cents=150_000)

        close_period(period["id"])
        period9 = create_period(fiscal_year=2026, period_no=9,
                                start_date="2026-09-01", end_date="2026-09-30")
        close_period(period9["id"])

        entries = list_afudc_entries(work_order_id=wo["id"],
                                     accounting_period_id=period9["id"])
        assert len(entries) == 1
        assert entries[0]["base_cents"] == 51_000, (
            "max(0, 201,000 - 150,000): CIAC-financed CWIP earns no AFUDC")
        assert entries[0]["amount_cents"] == 510

    def test_afudc_base_floor_zero_skips_entry(self, api):
        """PRD §3.9: "Fifth, the entry's `amount_cents` is the base multiplied by the composite monthly rate percentage and divided by one hundred, rounded half up to a whole cent; when that result rounds to zero, no entry is created for the order at all."
        PRD §3.9: "Second, the net beginning is the greater of zero and the beginning CWIP minus the CIAC received to date — the sum of `received_cents` over the order's agreements in `RECEIVED` or `APPLIED` — because CIAC-financed CWIP earns no AFUDC."

        Design: Corner/calculations/afudc_base_floor_zero_skips_entry
        """
        world = _afudc_world("HALF_MONTH")
        wo, period = world["work_order"], world["period"]
        create_received_ciac(wo["id"], pledged_cents=250_000)

        close_period(period["id"])
        period9 = create_period(fiscal_year=2026, period_no=9,
                                start_date="2026-09-01", end_date="2026-09-30")
        close_period(period9["id"])

        entries = list_afudc_entries(work_order_id=wo["id"],
                                     accounting_period_id=period9["id"])
        assert entries == [], (
            "250,000c of CIAC floors the 201,000c begin balance to zero, and "
            "a zero-amount entry is skipped")
        wo_view = get_work_order(wo["id"])
        assert wo_view["afudc_total_cents"] == 1_000, (
            "only the first period's 1,000c accrual stands")


def _closed_transformer_world(api, ciac_method="NET_OF_CIAC", ciac_cents=None,
                              charge_cents=120_000):
    """A CAPITAL order charged `charge_cents`, optionally CIAC-financed,
    completed 2026-08-20 and closed out to one TRANSFORMER unit while period
    2026-08 is still OPEN. Returns dict of world pieces."""
    program = create_program(ciac_method=ciac_method)
    catalog = create_catalog_entry()  # TRANSFORMER 50,000c @ 12%/yr
    create_schedule()  # MATERIAL / CAPITAL @ 0%
    period = create_period()
    wo = create_in_progress_work_order(program["id"],
                                       initial_estimated_cost_cents=500_000)
    post_charge(wo["id"], base_amount_cents=charge_cents,
                charge_date="2026-08-05")
    if ciac_cents is not None:
        create_received_ciac(wo["id"], pledged_cents=ciac_cents)
    complete_work_order(wo["id"], "2026-08-20")
    wo = closeout_work_order(wo["id"], [make_unitization_line(catalog["id"], 1)])
    units = get_success_data(
        api.list_fixed_asset_units(AUDITOR, params={"work_order_id": wo["id"]}))
    return {"program": program, "catalog": catalog, "period": period,
            "work_order": wo, "units": units}


class TestDepreciationHalfMonthFactors:
    def _world_through_period9(self, api):
        world = _closed_transformer_world(api)
        close_period(world["period"]["id"])  # in-service month
        period9 = create_period(fiscal_year=2026, period_no=9,
                                start_date="2026-09-01", end_date="2026-09-30")
        close_period(period9["id"])  # first full month
        world["period9"] = period9
        return world

    def test_depreciation_in_service_and_full_month_factors(self, api):
        """PRD §3.9: "The computation rounds at each step. The full monthly amount is the unit's `allocated_cost_cents` multiplied by the `annual_depreciation_rate_pct` of its catalog asset class and divided by twelve hundred, rounded half up to a whole cent. A factor then applies: one half when the closing period is the unit's in-service period, one half when it is the retirement period, and one otherwise — and a unit placed in service and retired within the same period receives a single half-month entry, not a full one."
        PRD §3.9: "The close posts one depreciation entry for each unit `IN_SERVICE` whose in-service period's `start_date` falls on or before the closing period's `end_date`, plus one final entry for each unit `RETIRED` whose `retirement_period_id` is the closing period; periods strictly before a unit's in-service period and strictly after its retirement period receive nothing."

        Design: Difficulty/combinatorial_formula/depreciation_half_month_factors
        """
        world = self._world_through_period9(api)
        unit = world["units"][0]
        assert unit["allocated_cost_cents"] == 120_000
        assert unit["status"] == "IN_SERVICE"

        # In-service month: round_half_up(120,000 * 12 / 1200) * 0.5 = 600.
        entries1 = list_depreciation_entries(
            fixed_asset_unit_id=unit["id"],
            accounting_period_id=world["period"]["id"])
        assert len(entries1) == 1
        assert entries1[0]["amount_cents"] == 600
        assert entries1[0]["status"] == "POSTED"

        # First full month: factor 1.0.
        entries2 = list_depreciation_entries(
            fixed_asset_unit_id=unit["id"],
            accounting_period_id=world["period9"]["id"])
        assert len(entries2) == 1
        assert entries2[0]["amount_cents"] == 1_200

    def test_depreciation_retirement_month_and_nbv(self, api):
        """PRD §3.9: "The computation rounds at each step. The full monthly amount is the unit's `allocated_cost_cents` multiplied by the `annual_depreciation_rate_pct` of its catalog asset class and divided by twelve hundred, rounded half up to a whole cent. A factor then applies: one half when the closing period is the unit's in-service period, one half when it is the retirement period, and one otherwise — and a unit placed in service and retired within the same period receives a single half-month entry, not a full one."
        PRD §3.9: "For units retired in this period, the close then sets `retirement_nbv_cents` to the `allocated_cost_cents` minus the accumulated depreciation including this final entry."
        PRD §3.8: "A unit's service life ends when a `Controller` retires it (`IN_SERVICE` → `RETIRED`) by supplying a `retirement_date` that must fall inside the single accounting period currently `OPEN` or `REOPENED`, else `ERR_RETIREMENT_PERIOD_NOT_OPEN`; retiring a unit already `RETIRED` is rejected with `ERR_UNIT_ALREADY_RETIRED`."

        Design: Difficulty/combinatorial_formula/depreciation_half_month_factors
        """
        world = self._world_through_period9(api)
        unit = world["units"][0]

        period10 = create_period(fiscal_year=2026, period_no=10,
                                 start_date="2026-10-01", end_date="2026-10-31")
        retired = validate_success(
            api.retire_fixed_asset_unit(unit["id"], "2026-10-10", CONTROLLER))
        assert retired["status"] == "RETIRED"
        assert retired["retirement_period_id"] == period10["id"]

        close_period(period10["id"])

        # Retirement month: a final half-month entry.
        entries3 = list_depreciation_entries(
            fixed_asset_unit_id=unit["id"],
            accounting_period_id=period10["id"])
        assert len(entries3) == 1
        assert entries3[0]["amount_cents"] == 600

        unit_view = validate_success(api.get_fixed_asset_unit(unit["id"], AUDITOR))
        assert unit_view["accumulated_depreciation_cents"] == 2_400
        assert unit_view["retirement_nbv_cents"] == 117_600, (
            "120,000 allocated minus the 2,400 accumulated including the "
            "final half-month entry")
        assert unit_view["status"] == "RETIRED"


class TestDepreciationCiacBasis:
    def test_depreciation_net_of_ciac_basis(self, api):
        """PRD §3.8: "The `capitalizable_total_cents` then follows the program's `ciac_method`: under `NET_OF_CIAC` it is the gross CWIP minus the applied contribution, so depreciation later runs on the net basis; under `GROSS_WITH_CONTRA` it is the full gross CWIP, and the program's `ciac_contra_balance_cents` increases by the `ciac_applied_cents`, establishing the contra-asset that subsequent depreciation contra credits will draw down (§3.9)."
        PRD §3.9: "The two methods diverge on identical physical data: a net basis of 100,000 cents at a twelve-percent annual rate yields a full month of 1,000 cents and an in-service month of 500 cents with no contra credit, while the gross basis of 120,000 cents at the same rate yields a full month of 1,200 cents and an in-service month of 600 cents, with a 600-cent entry carrying a 100-cent contra credit when 20,000 cents of the 120,000-cent gross was CIAC-financed."
        PRD §3.9: "Under a `GROSS_WITH_CONTRA` program each entry additionally carries a `ciac_contra_credit_cents`: the entry's amount multiplied by the order's `ciac_applied_cents` and divided by its `gross_cwip_cents`, rounded half up, and the credits draw down the program's `ciac_contra_balance_cents`; under `NET_OF_CIAC` the credit is always zero."

        Design: Difficulty/dual_variant_calc/depreciation_net_vs_gross_ciac_basis
        """
        world = _closed_transformer_world(api, ciac_method="NET_OF_CIAC",
                                          ciac_cents=20_000)
        wo, unit = world["work_order"], world["units"][0]
        assert wo["gross_cwip_cents"] == 120_000
        assert wo["ciac_applied_cents"] == 20_000
        assert wo["capitalizable_total_cents"] == 100_000
        assert unit["allocated_cost_cents"] == 100_000

        close_period(world["period"]["id"])
        entries = list_depreciation_entries(
            fixed_asset_unit_id=unit["id"],
            accounting_period_id=world["period"]["id"])
        assert len(entries) == 1
        assert entries[0]["amount_cents"] == 500, "in-service month on net basis"
        assert entries[0]["ciac_contra_credit_cents"] == 0, (
            "under NET_OF_CIAC the credit is always zero")

    def test_depreciation_gross_with_contra_basis(self, api):
        """PRD §3.8: "The `capitalizable_total_cents` then follows the program's `ciac_method`: under `NET_OF_CIAC` it is the gross CWIP minus the applied contribution, so depreciation later runs on the net basis; under `GROSS_WITH_CONTRA` it is the full gross CWIP, and the program's `ciac_contra_balance_cents` increases by the `ciac_applied_cents`, establishing the contra-asset that subsequent depreciation contra credits will draw down (§3.9)."
        PRD §3.9: "The two methods diverge on identical physical data: a net basis of 100,000 cents at a twelve-percent annual rate yields a full month of 1,000 cents and an in-service month of 500 cents with no contra credit, while the gross basis of 120,000 cents at the same rate yields a full month of 1,200 cents and an in-service month of 600 cents, with a 600-cent entry carrying a 100-cent contra credit when 20,000 cents of the 120,000-cent gross was CIAC-financed."
        PRD §3.9: "Under a `GROSS_WITH_CONTRA` program each entry additionally carries a `ciac_contra_credit_cents`: the entry's amount multiplied by the order's `ciac_applied_cents` and divided by its `gross_cwip_cents`, rounded half up, and the credits draw down the program's `ciac_contra_balance_cents`; under `NET_OF_CIAC` the credit is always zero."

        Design: Difficulty/dual_variant_calc/depreciation_net_vs_gross_ciac_basis
        """
        world = _closed_transformer_world(api, ciac_method="GROSS_WITH_CONTRA",
                                          ciac_cents=20_000)
        program, wo, unit = world["program"], world["work_order"], world["units"][0]
        assert wo["capitalizable_total_cents"] == 120_000, (
            "GROSS_WITH_CONTRA capitalizes the full gross CWIP")
        assert unit["allocated_cost_cents"] == 120_000

        close_period(world["period"]["id"])
        entries = list_depreciation_entries(
            fixed_asset_unit_id=unit["id"],
            accounting_period_id=world["period"]["id"])
        assert len(entries) == 1
        assert entries[0]["amount_cents"] == 600, "in-service month on gross basis"
        # round_half_up(600 * 20,000 / 120,000) == 100
        assert entries[0]["ciac_contra_credit_cents"] == 100

        program_view = validate_success(
            api.get_capital_program(program["id"], AUDITOR))
        assert program_view["ciac_contra_balance_cents"] == 19_900, (
            "20,000 applied at closeout, drawn down by the 100c credit")


class TestPeriodCloseReopenCycle:
    def _world_with_charge(self):
        world = setup_charging_world(estimate_cents=9_000_000)
        post_charge(world["work_order"]["id"], base_amount_cents=200_000,
                    charge_date="2026-08-10")
        return world

    def test_period_reopen_compensates_afudc_entry(self, api):
        """PRD §3.9: "Reopening is the compensating mirror, available to a `Controller` under two guards: no accounting period may currently stand `OPEN` or `REOPENED`, else `ERR_PERIOD_ALREADY_OPEN`, and the target must be the most recently created `CLOSED` period, else `ERR_PERIOD_REOPEN_NOT_LATEST`. The reopen compensates everything the period's close produced: every AFUDC, depreciation, and amortization entry posted by that close and still `ACCRUED` or `POSTED` flips to `REVERSED`, and the affected balances — each order's `afudc_total_cents` and `cwip_cents`, each unit's `accumulated_depreciation_cents` and `retirement_nbv_cents`, each asset's `remaining_cents`, and each program's `ciac_contra_balance_cents` — are recomputed without the reversed entries."

        Design: Difficulty/non_linear_state_machine/accounting_period_close_reopen_reclose_cycle
        """
        world = self._world_with_charge()
        wo, period = world["work_order"], world["period"]

        close_period(period["id"])
        assert get_work_order(wo["id"])["cwip_cents"] == 201_000

        reopened = reopen_period(period["id"])
        assert reopened["status"] == "REOPENED"

        wo_view = get_work_order(wo["id"])
        assert wo_view["cwip_cents"] == 200_000, (
            "the reopen compensates the accrual out of the CWIP balance")
        assert wo_view["afudc_total_cents"] == 0

        entries = list_afudc_entries(work_order_id=wo["id"],
                                     accounting_period_id=period["id"])
        assert len(entries) == 1
        assert entries[0]["status"] == "REVERSED"
        assert entries[0]["amount_cents"] == 1_000

    def test_period_reclose_recomputes_accrual(self, api):
        """PRD §3.9: "Re-closing a `REOPENED` period recomputes every accrual fresh from the state current at that moment, so charges posted during the reopen window are included in the new close."
        PRD §3.9: "The period itself ends at `REOPENED`, from which a fresh close repeats the same five steps."

        Design: Difficulty/non_linear_state_machine/accounting_period_close_reopen_reclose_cycle
        """
        world = self._world_with_charge()
        wo, period = world["work_order"], world["period"]

        close_period(period["id"])
        reopen_period(period["id"])
        assert get_work_order(wo["id"])["cwip_cents"] == 200_000

        reclosed = close_period(period["id"])
        assert reclosed["status"] == "CLOSED"

        wo_view = get_work_order(wo["id"])
        assert wo_view["cwip_cents"] == 201_000, (
            "no charges were posted during the reopen window, so the fresh "
            "accrual reproduces the original 1,000c")
        assert wo_view["afudc_total_cents"] == 1_000

        accrued = list_afudc_entries(work_order_id=wo["id"],
                                     accounting_period_id=period["id"],
                                     status="ACCRUED")
        assert len(accrued) == 1
        assert accrued[0]["amount_cents"] == 1_000


class TestAmortizationCascade:
    def _approved_asset_world(self):
        period8 = create_period()
        ra = create_approved_reg_asset(description="Storm cost deferral",
                                       original_cents=10_000,
                                       amortization_months=3)
        return period8, ra

    def test_amortization_entries_decrement_remaining(self, api):
        """PRD §3.9: "The standard monthly installment is the `original_cents` divided by the `amortization_months`, rounded half up to a whole cent. For the final scheduled month — when the number of entries already `POSTED` for the asset is one less than the amortization term — the entry is whatever `remaining_cents` remains, so the final entry absorbs the rounding remainder; in every other month the entry is the lesser of the monthly installment and the remaining balance. The entry records its `regulatory_asset_id`, the closing period as `accounting_period_id`, and a `status` of `POSTED`, and the asset's `remaining_cents` falls by the entry amount. The first such entry moves the asset `APPROVED` → `AMORTIZING`, and an entry that brings `remaining_cents` to exactly zero moves it `AMORTIZING` → `FULLY_AMORTIZED`."

        Design: Difficulty/transitive_cascade/period_close_amortization_completion_cascade
        """
        period8, ra = self._approved_asset_world()

        close_period(period8["id"])
        view1 = validate_success(api.get_regulatory_asset(ra["id"], AUDITOR))
        assert view1["remaining_cents"] == 6_667, "10,000 - 3,333"
        assert view1["status"] == "AMORTIZING"

        period9 = create_period(fiscal_year=2026, period_no=9,
                                start_date="2026-09-01", end_date="2026-09-30")
        close_period(period9["id"])
        view2 = validate_success(api.get_regulatory_asset(ra["id"], AUDITOR))
        assert view2["remaining_cents"] == 3_334
        assert view2["status"] == "AMORTIZING"

    def test_final_amortization_entry_plugs_remainder(self, api):
        """PRD §3.9: "The standard monthly installment is the `original_cents` divided by the `amortization_months`, rounded half up to a whole cent. For the final scheduled month — when the number of entries already `POSTED` for the asset is one less than the amortization term — the entry is whatever `remaining_cents` remains, so the final entry absorbs the rounding remainder; in every other month the entry is the lesser of the monthly installment and the remaining balance. The entry records its `regulatory_asset_id`, the closing period as `accounting_period_id`, and a `status` of `POSTED`, and the asset's `remaining_cents` falls by the entry amount. The first such entry moves the asset `APPROVED` → `AMORTIZING`, and an entry that brings `remaining_cents` to exactly zero moves it `AMORTIZING` → `FULLY_AMORTIZED`. A worked instance: an original 10,000 cents over three months amortizes 3,333, then 3,333, then 3,334, the final scheduled month plugging the remainder."

        Design: Difficulty/transitive_cascade/period_close_amortization_completion_cascade
        """
        period8, ra = self._approved_asset_world()
        close_period(period8["id"])
        period9 = create_period(fiscal_year=2026, period_no=9,
                                start_date="2026-09-01", end_date="2026-09-30")
        close_period(period9["id"])
        period10 = create_period(fiscal_year=2026, period_no=10,
                                 start_date="2026-10-01", end_date="2026-10-31")
        close_period(period10["id"])

        final_entries = list_amortization_entries(
            regulatory_asset_id=ra["id"], accounting_period_id=period10["id"])
        assert len(final_entries) == 1
        assert final_entries[0]["amount_cents"] == 3_334, (
            "the final scheduled month plugs the rounding remainder")

        view = validate_success(api.get_regulatory_asset(ra["id"], AUDITOR))
        assert view["remaining_cents"] == 0
        assert view["status"] == "FULLY_AMORTIZED"


class TestExpenseOrderLifecycle:
    def test_expense_order_lifecycle_no_capitalization(self, api):
        """PRD §3.3: "An `EXPENSE` order earns no AFUDC while it is being built and unitizes zero lines at closeout."
        PRD §3.9: "For each `CAPITAL` work order standing at `AUTHORIZED`, `IN_PROGRESS`, or `SUSPENDED` whose program is still `OPEN`, the close accrues an allowance for funds used during construction; `EXPENSE` orders never accrue AFUDC, and accrual stops at completion."
        PRD §3.5: "The applicable rate is the unique schedule row whose `cost_type` matches the charge, whose `order_type` equals the work order's `order_type`, and whose half-open interval covers the charge date — on or after `effective_from` and strictly before `effective_to`, or open-ended when `effective_to` is null."
        PRD §3.8: "Then the referential checks: no CIAC agreement of the order may still stand `PLEDGED` (`ERR_CIAC_PLEDGED_OUTSTANDING`); a `CAPITAL` order requires a non-empty `unitization_lines` while an `EXPENSE` order requires it empty, either violation rejected as `ERR_UNITIZATION_EMPTY`; every line must carry a `quantity` of at least one and reference an existing `unit_catalog_id`; and the lines' total target — the sum over the lines of each `quantity` multiplied by its catalog row's `standard_cost_cents` — must be greater than zero, else `ERR_UNITIZATION_ZERO_TARGET`, a condition reachable only when every referenced catalog row has a zero standard cost."

        Design: Corner/state_machines/expense_order_lifecycle_no_capitalization
        """
        world = setup_charging_world(estimate_cents=500_000, order_type="EXPENSE",
                                     cost_type="MATERIAL", rate_pct=10.0)
        wo, period = world["work_order"], world["period"]
        assert wo["order_type"] == "EXPENSE"

        charge = post_charge(wo["id"], base_amount_cents=10_000,
                             charge_date="2026-08-10")
        assert charge["overhead_amount_cents"] == 1_000, (
            "the 10% O&M loading rate applies to the EXPENSE order")
        assert charge["total_cents"] == 11_000

        close_period(period["id"])
        entries = list_afudc_entries(work_order_id=wo["id"])
        assert entries == [], "EXPENSE orders never accrue AFUDC"

        create_period(fiscal_year=2026, period_no=9,
                      start_date="2026-09-01", end_date="2026-09-30")
        completed = get_success_data(
            api.complete_work_order(wo["id"], "2026-09-10", SUPERVISOR))
        assert completed["status"] == "COMPLETED"

        closed = validate_success(api.closeout_work_order(wo["id"], [], CONTROLLER))
        assert closed["status"] == "CLOSED", (
            "an EXPENSE order requires the unitization list to be empty")

        units = get_success_data(
            api.list_fixed_asset_units(AUDITOR, params={"work_order_id": wo["id"]}))
        assert units == [], "an EXPENSE order unitizes zero lines at closeout"
