"""Preparation arithmetic: the two interest variants, apportionment rounding and
the five-step penalty ladder.

Preparation is where every number on an amendment is written, so the cases here
pin the agency-selected interest variant, the per-line rounding discipline of the
jurisdiction apportionment, the statutory penalty floor's position in the ladder,
and the failure-to-deposit tier edge.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_amendment_money, assert_case_rollups
from test_helpers.test_users import ADMIN_HEADERS, ANALYST_HEADERS, OFFICER_HEADERS, PREPARER_HEADERS


def _state_scenario(api, interest_method: str):
    """The New York state quarter: one withholding variance of 250000 cents and two
    cleared deposits that fully satisfy their own obligations."""
    fx.set_clock(api, "2026-04-30T00:00:00Z")
    employer = fx.make_employer(api)
    agency = fx.make_state_agency(
        api, penalty_multiplier_bps=5000, interest_method=interest_method
    )
    account = validate_success(
        api.create_agency_account(
            f.agency_account_payload(
                employer["id"],
                agency["id"],
                account_number="NY-ACCT-0001",
                effective_from_tax_year=2025,
                effective_from_quarter=1,
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    validate_success(
        api.activate_agency_account(
            account["id"], {"account_number": "NY-ACCT-0001"}, ADMIN_HEADERS
        )
    )
    first = fx.make_employee(api, employer["id"], full_name="Dana Reed", national_id_last4="4821")
    second = fx.make_employee(api, employer["id"], full_name="Lee Park", national_id_last4="7130")
    for employee, (wage, withheld) in zip((first, second), ((3000000, 450000), (2000000, 300000))):
        fx.make_register_line(
            api,
            employer["id"],
            employee["id"],
            agency["id"],
            taxable_wage_cents=wage,
            withheld_cents=withheld,
            work_jurisdiction_code="NY",
        )
    fx.make_filed_return(
        api,
        employer["id"],
        agency["id"],
        form_code="NYS-45X",
        reported_taxable_wage_cents=5000000,
        reported_withheld_cents=500000,
    )
    for due, amount in (("2025-02-19", 150000), ("2025-03-19", 100000)):
        fx.make_deposit_record(
            api,
            employer["id"],
            agency["id"],
            deposit_due_date=due,
            deposit_date=due,
            amount_cents=amount,
            obligation_amount_cents=amount,
        )
    case = fx.make_correction_case(api, employer["id"], agency["id"])
    validate_success(api.reconcile_case(case["id"], {}, ANALYST_HEADERS))
    rows = fx.discrepancies_by_detected_category(api, case["id"])
    assert set(rows) == {"WITHHOLDING"}, rows
    validate_success(
        api.categorize_discrepancy(
            rows["WITHHOLDING"]["id"],
            f.categorize_payload("WITHHOLDING", "THIRD_PARTY_FEED_ERROR"),
            ANALYST_HEADERS,
        )
    )
    amendment = fx.open_amendment(api, case["id"], form_code="NYS-45X")
    return {"case_id": case["id"], "amended_return_id": amendment["id"]}


class TestStatutoryDailyInterest:
    def test_statutory_daily_accrues_the_whole_tax_delta_from_the_statutory_due_date(
        self, api, federal_case
    ):
        """One simple-interest accrual over 365 whole days on a 250000-cent delta at
        800 basis points is exactly 20000 cents.

        PRD: "Under the `STATUTORY_DAILY` variant — the federal-style regime — one simple-interest accrual runs on the whole tax delta from the filed return's statutory due date."
        PRD: "Take the amendment's `tax_delta_cents`, multiply by the annual rate, multiply by `days_late` (the whole-day count from the filed return's `original_due_date` to `accrual_through_date`, floored at zero), divide by 365, and round the result to the nearest whole cent with ties rounded upward."

        Design: Difficulty/dual_variant_calc/interest_statutory_daily_variant_on_federal_amendment
        """
        amendment = fx.open_amendment(api, federal_case["case_id"])
        prepared = validate_success(
            api.prepare_amended_return(amendment["id"], {}, PREPARER_HEADERS)
        )

        assert prepared["status"] == "PREPARED"
        assert_amendment_money(
            prepared,
            interest_variant="STATUTORY_DAILY",
            tax_delta_cents=250000,
            wage_delta_cents=250000,
            deposit_shortfall_cents=250000,
            days_late=365,
            interest_cents=20000,
            penalty_cents=65625,
            voluntary_reduction_applied=True,
        )
        assert_case_rollups(
            fx.read_case(api, federal_case["case_id"]), total_exposure_cents=335625
        )

    def test_statutory_daily_ignores_the_agencys_deposit_obligations(self, api):
        """With no deposit record anywhere on the scope the accrual is unchanged in
        form: 50000 cents at 800 basis points over 365 days is 4000 cents.

        PRD: "The annual rate is the agency's `interest_rate_bps_annual` divided by ten thousand, and every accrual divides by a year of 365 days."
        PRD: "That single figure is `interest_cents`."

        Design: Difficulty/dual_variant_calc/interest_statutory_daily_variant_on_federal_amendment
        """
        ctx = fx.federal_scenario(
            api,
            with_deposit=False,
            register_totals=((1000000, 200000),),
            filed_return_overrides={
                "reported_taxable_wage_cents": 1000000,
                "reported_withheld_cents": 150000,
            },
        )
        validate_success(api.reconcile_case(ctx["case_id"], {}, ANALYST_HEADERS))
        rows = fx.discrepancies_by_detected_category(api, ctx["case_id"])
        assert set(rows) == {"WITHHOLDING"}, rows
        validate_success(
            api.categorize_discrepancy(
                rows["WITHHOLDING"]["id"],
                f.categorize_payload("WITHHOLDING", "RATE_TABLE_STALE"),
                ANALYST_HEADERS,
            )
        )
        amendment = fx.open_amendment(api, ctx["case_id"])

        prepared = validate_success(
            api.prepare_amended_return(amendment["id"], {}, PREPARER_HEADERS)
        )

        assert_amendment_money(
            prepared,
            interest_variant="STATUTORY_DAILY",
            tax_delta_cents=50000,
            wage_delta_cents=0,
            deposit_shortfall_cents=0,
            days_late=365,
            interest_cents=4000,
            penalty_cents=9375,
            voluntary_reduction_applied=True,
        )
        assert_case_rollups(fx.read_case(api, ctx["case_id"]), total_exposure_cents=63375)


class TestDepositWeightedInterest:
    def test_deposit_weighted_accrues_each_tranche_from_its_own_deposit_due_date(self, api):
        """Splitting the 250000-cent delta across obligations of 150000 due 19
        February and 100000 due 19 March yields 34833 cents, not 30000.

        PRD: "The two variants genuinely differ: for a tax delta of 250000 cents, an annual rate of 1200 basis points, an accrual-through date of 30 April 2026 and two cleared obligations of 150000 cents due 19 February 2025 and 100000 cents due 19 March 2025, `DEPOSIT_WEIGHTED` yields 34833 cents while `STATUTORY_DAILY` on identical inputs yields 30000 cents."

        Design: Difficulty/dual_variant_calc/interest_deposit_weighted_variant_diverges_on_state_amendment
        """
        ctx = _state_scenario(api, "DEPOSIT_WEIGHTED")

        prepared = validate_success(
            api.prepare_amended_return(ctx["amended_return_id"], {}, PREPARER_HEADERS)
        )

        assert_amendment_money(
            prepared,
            interest_variant="DEPOSIT_WEIGHTED",
            tax_delta_cents=250000,
            deposit_shortfall_cents=0,
            days_late=365,
            interest_cents=34833,
            penalty_cents=23438,
        )
        assert prepared["interest_cents"] != 30000
        assert_case_rollups(fx.read_case(api, ctx["case_id"]), total_exposure_cents=308271)

    def test_statutory_daily_on_the_identical_state_inputs_yields_thirty_thousand(self, api):
        """Holding every other input byte-identical and changing only the agency's
        interest method drops the charge to the single-accrual figure.

        PRD: "The amendment's `interest_variant` is copied from the case agency's `interest_method` and recorded on the row, so a reader can always tell which formula produced the number."

        Design: Difficulty/dual_variant_calc/interest_deposit_weighted_variant_diverges_on_state_amendment
        """
        ctx = _state_scenario(api, "STATUTORY_DAILY")

        prepared = validate_success(
            api.prepare_amended_return(ctx["amended_return_id"], {}, PREPARER_HEADERS)
        )

        assert_amendment_money(
            prepared,
            interest_variant="STATUTORY_DAILY",
            tax_delta_cents=250000,
            deposit_shortfall_cents=0,
            days_late=365,
            interest_cents=30000,
            penalty_cents=23438,
        )
        assert prepared["interest_cents"] != 34833
        assert_case_rollups(fx.read_case(api, ctx["case_id"]), total_exposure_cents=303438)


def _apportionment_scenario(api):
    """Three identical register lines of 100001 cents, each half-worked outside the
    agency's own jurisdiction, against a filed return that reports their exact sum."""
    fx.set_clock(api, "2026-04-30T00:00:00Z")
    employer = fx.make_employer(api, deposit_schedule="MONTHLY")
    agency = validate_success(
        api.create_tax_agency(
            f.federal_agency_payload(
                agency_code="PHL-LST",
                level="LOCAL",
                jurisdiction_code="PHL",
                interest_rate_bps_annual=600,
                interest_method="STATUTORY_DAILY",
                penalty_multiplier_bps=10000,
                min_days_between_amendments=15,
                amendment_window_days=730,
                requires_registration=False,
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    employees = [
        fx.make_employee(
            api,
            employer["id"],
            full_name=name,
            national_id_last4=last4,
            mailing_state_code="PA",
        )
        for name, last4 in (("Dana Reed", "4821"), ("Lee Park", "7130"), ("Ana Ruiz", "9052"))
    ]
    lines = [
        fx.make_register_line(
            api,
            employer["id"],
            employee["id"],
            agency["id"],
            taxable_wage_cents=100001,
            withheld_cents=0,
            work_jurisdiction_code="PA",
            workday_ratio_bps=5000,
        )
        for employee in employees
    ]
    fx.make_filed_return(
        api,
        employer["id"],
        agency["id"],
        form_code="PHL-LSTX",
        reported_taxable_wage_cents=300003,
        reported_withheld_cents=0,
    )
    case = fx.make_correction_case(api, employer["id"], agency["id"])
    validate_success(api.reconcile_case(case["id"], {}, ANALYST_HEADERS))
    return {
        "case_id": case["id"],
        "employees": employees,
        "register_lines": lines,
        "rows": fx.case_discrepancies(api, case["id"]),
    }


class TestJurisdictionApportionmentRounding:
    def test_apportioned_removal_is_rounded_once_per_register_line_at_emission(self, api):
        """Half of 100001 cents is 50000.5, which rounds up to 50001 on each of the
        three lines, and each discrepancy names its own employee and line.

        PRD: "For each line individually, multiply that line's `taxable_wage_cents` by that line's `workday_ratio_bps`, divide by ten thousand, and round the result to the nearest whole cent with ties rounded upward."
        PRD: "Next, the run walks the register lines once more, in the same pinned `created_at` ascending order, and for every line whose `work_jurisdiction_code` differs from the agency's `jurisdiction_code` it emits a discrepancy with `detected_category` `JURISDICTION_ASSIGNMENT` whose `amount_cents` is that line's apportioned removal, whose `employee_id` is the line's employee and whose `register_line_id` is the line itself — this is the only category that is employee-scoped, and every other category leaves both of those references null."

        Design: Difficulty/combinatorial_formula/apportionment_rounds_per_line_before_summation
        """
        ctx = _apportionment_scenario(api)
        rows = ctx["rows"]

        assert len(rows) == 3, rows
        for index, (row, employee, line) in enumerate(
            zip(rows, ctx["employees"], ctx["register_lines"])
        ):
            assert row["detected_category"] == "JURISDICTION_ASSIGNMENT"
            assert row["amount_cents"] == 50001
            assert row["emission_index"] == index
            assert row["employee_id"] == employee["id"]
            assert row["register_line_id"] == line["id"]
        assert sum(row["amount_cents"] for row in rows) == 150003

    def test_wage_delta_sums_the_already_rounded_line_amounts_not_the_aggregate(self, api):
        """The rollup adds the three rounded 50001-cent removals, so the wage delta is
        -150003 cents; rounding the aggregate instead would report -150002.

        PRD: "To make the difference concrete: three lines of 100001 cents each at a workday share of 5000 basis points round to 50001 cents per line and sum to 150003 cents, whereas rounding the aggregate would give 150002 cents."
        PRD: "The jurisdiction removal is the sum, over the rows whose `category` is `JURISDICTION_ASSIGNMENT`, of the per-line apportioned amount of the register line each such row names — computed with the per-line rounding of §3.2, meaning each line's amount is rounded to a whole cent before the addition."

        Design: Difficulty/combinatorial_formula/apportionment_rounds_per_line_before_summation
        """
        ctx = _apportionment_scenario(api)
        for row in ctx["rows"]:
            validate_success(
                api.categorize_discrepancy(
                    row["id"],
                    f.categorize_payload("JURISDICTION_ASSIGNMENT", "JURISDICTION_MAPPING_ERROR"),
                    ANALYST_HEADERS,
                )
            )
        amendment = fx.open_amendment(api, ctx["case_id"], form_code="PHL-LSTX")

        prepared = validate_success(
            api.prepare_amended_return(amendment["id"], {}, PREPARER_HEADERS)
        )

        assert_amendment_money(
            prepared,
            wage_delta_cents=-150003,
            tax_delta_cents=0,
            deposit_shortfall_cents=0,
            interest_cents=0,
            penalty_cents=0,
            interest_variant="STATUTORY_DAILY",
        )
        assert prepared["wage_delta_cents"] != -150002


class TestStatutoryPenaltyFloor:
    def test_floor_is_applied_before_the_multiplier_and_before_the_voluntary_reduction(
        self, api
    ):
        """A gross of 280 cents is raised to the 5000-cent minimum first, then scaled
        and reduced, giving 3750 cents — not 5000, and not 280.

        PRD: "**Step three** adds the two charges into a gross penalty and then, if and only if that gross is greater than zero, raises it to the statutory minimum of 5000 cents — that is, the gross becomes the larger of itself and 5000 cents."
        PRD: "Applying the statutory floor after the multiplier, or after the voluntary reduction, is forbidden."

        Design: Difficulty/combinatorial_formula/penalty_floor_applied_before_multiplier_and_voluntary_reduction
        """
        ctx = fx.federal_scenario(
            api,
            clock="2025-05-03T00:00:00Z",
            employer_overrides={"deposit_schedule": "MONTHLY"},
            register_totals=((100000, 4000),),
            filed_return_overrides={
                "reported_taxable_wage_cents": 100000,
                "reported_withheld_cents": 0,
            },
            deposit_overrides={"amount_cents": 0, "obligation_amount_cents": 4000},
        )
        validate_success(api.reconcile_case(ctx["case_id"], {}, ANALYST_HEADERS))
        rows = fx.discrepancies_by_detected_category(api, ctx["case_id"])
        assert set(rows) == {"WITHHOLDING", "DEPOSIT_SHORTFALL"}, rows
        validate_success(
            api.categorize_discrepancy(
                rows["WITHHOLDING"]["id"],
                f.categorize_payload("WITHHOLDING", "MANUAL_ENTRY_ERROR"),
                ANALYST_HEADERS,
            )
        )
        validate_success(
            api.categorize_discrepancy(
                rows["DEPOSIT_SHORTFALL"]["id"],
                f.categorize_payload("DEPOSIT_SHORTFALL", "DEPOSIT_SCHEDULING_ERROR"),
                ANALYST_HEADERS,
            )
        )
        amendment = fx.open_amendment(
            api, ctx["case_id"], accrual_through_date="2025-05-03"
        )

        prepared = validate_success(
            api.prepare_amended_return(amendment["id"], {}, PREPARER_HEADERS)
        )

        assert_amendment_money(
            prepared,
            days_late=3,
            tax_delta_cents=4000,
            deposit_shortfall_cents=4000,
            interest_cents=3,
            penalty_cents=3750,
            voluntary_reduction_applied=True,
        )
        assert prepared["penalty_cents"] not in (5000, 280)
        assert_case_rollups(fx.read_case(api, ctx["case_id"]), total_exposure_cents=7753)

    def test_a_gross_of_exactly_zero_stays_zero_and_the_floor_does_not_fire(self, api):
        """Accruing only to the statutory due date leaves both charges at zero, and the
        5000-cent minimum is not imposed on a zero gross.

        PRD: "A gross of exactly zero stays zero and the floor does not fire."
        PRD: "**Step two** computes the failure-to-file charge at 500 basis points for each whole or partial thirty-day month of lateness, capped at five such months: when `days_late` is greater than zero, the month count is `days_late` divided by 30 and rounded *up* to the next whole number, then limited to at most 5; when `days_late` is zero the month count is zero."

        Design: Difficulty/combinatorial_formula/penalty_floor_applied_before_multiplier_and_voluntary_reduction
        """
        ctx = fx.federal_scenario(
            api,
            clock="2025-05-03T00:00:00Z",
            with_deposit=False,
            register_totals=((1000000, 200000),),
            filed_return_overrides={
                "reported_taxable_wage_cents": 1000000,
                "reported_withheld_cents": 150000,
            },
        )
        validate_success(api.reconcile_case(ctx["case_id"], {}, ANALYST_HEADERS))
        rows = fx.discrepancies_by_detected_category(api, ctx["case_id"])
        assert set(rows) == {"WITHHOLDING"}, rows
        validate_success(
            api.categorize_discrepancy(
                rows["WITHHOLDING"]["id"],
                f.categorize_payload("WITHHOLDING", "RATE_TABLE_STALE"),
                ANALYST_HEADERS,
            )
        )
        amendment = fx.open_amendment(
            api, ctx["case_id"], accrual_through_date="2025-04-30"
        )

        prepared = validate_success(
            api.prepare_amended_return(amendment["id"], {}, PREPARER_HEADERS)
        )

        assert_amendment_money(
            prepared,
            days_late=0,
            tax_delta_cents=50000,
            deposit_shortfall_cents=0,
            interest_cents=0,
            penalty_cents=0,
        )
        assert prepared["penalty_cents"] != 5000
        assert_case_rollups(fx.read_case(api, ctx["case_id"]), total_exposure_cents=50000)


def _ftd_scenario(api):
    """A 200000-cent withholding shortfall that is also a 200000-cent deposit
    shortfall, measurable one day either side of the five-day ladder step."""
    ctx = fx.federal_scenario(
        api,
        clock="2025-05-06T00:00:00Z",
        employer_overrides={"deposit_schedule": "MONTHLY"},
        register_totals=((1000000, 350000),),
        filed_return_overrides={
            "reported_taxable_wage_cents": 1000000,
            "reported_withheld_cents": 150000,
        },
        deposit_overrides={"amount_cents": 150000, "obligation_amount_cents": 350000},
    )
    validate_success(api.reconcile_case(ctx["case_id"], {}, ANALYST_HEADERS))
    rows = fx.discrepancies_by_detected_category(api, ctx["case_id"])
    assert set(rows) == {"WITHHOLDING", "DEPOSIT_SHORTFALL"}, rows
    validate_success(
        api.categorize_discrepancy(
            rows["WITHHOLDING"]["id"],
            f.categorize_payload("WITHHOLDING", "RATE_TABLE_STALE"),
            ANALYST_HEADERS,
        )
    )
    validate_success(
        api.categorize_discrepancy(
            rows["DEPOSIT_SHORTFALL"]["id"],
            f.categorize_payload("DEPOSIT_SHORTFALL", "DEPOSIT_SCHEDULING_ERROR"),
            ANALYST_HEADERS,
        )
    )
    return ctx


class TestFailureToDepositLadder:
    def test_five_days_late_takes_the_lowest_failure_to_deposit_rate(self, api):
        """At exactly five days late the ladder is still on its first rung, so the
        deposit charge is 200 basis points of the 200000-cent shortfall.

        PRD: "**Step one** selects a failure-to-deposit rate from a days-late ladder: when `days_late` is 5 or fewer the rate is 200 basis points; when it is 6 through 15 the rate is 500 basis points; when it is 16 or more the rate is 1000 basis points."
        PRD: "The failure-to-deposit charge is `deposit_shortfall_cents` multiplied by that rate, divided by ten thousand, rounded half up to a whole cent."

        Design: Difficulty/boundary_precision_check/ftd_tier_flips_between_five_and_six_days_late
        """
        ctx = _ftd_scenario(api)
        amendment = fx.open_amendment(api, ctx["case_id"], accrual_through_date="2025-05-05")

        prepared = validate_success(
            api.prepare_amended_return(amendment["id"], {}, PREPARER_HEADERS)
        )

        assert_amendment_money(
            prepared,
            days_late=5,
            tax_delta_cents=200000,
            deposit_shortfall_cents=200000,
            wage_delta_cents=0,
            interest_cents=219,
            penalty_cents=10500,
            voluntary_reduction_applied=True,
        )
        assert_case_rollups(fx.read_case(api, ctx["case_id"]), total_exposure_cents=210719)

    def test_six_days_late_steps_the_ladder_up_and_costs_4500_cents_more(self, api):
        """Voiding the five-day measurement and re-measuring one day later moves the
        rate to 500 basis points, raising the penalty from 10500 to 15000 cents.

        PRD: "Voiding a `PREPARED` amendment transitions `PREPARED → VOID`, records the `void_reason`, transitions every discrepancy whose `resolved_amended_return_id` names this amendment back `RESOLVED → CATEGORIZED` (clearing both `resolved_amended_return_id` and `resolved_amount_cents` to null, recomputing the case's `open_discrepancy_count`, and incrementing each such discrepancy's `version` by 1), recomputes the case's `total_exposure_cents` now that this amendment has left the summed set, recomputes the employer's `open_exposure_cents`, returns the case's `filing_status` `FILING_IN_PROGRESS → FILING_PENDING` provided no other amendment for the case sits in `PREPARED`, `SIGNED`, `SUBMITTED` or `ACCEPTED`, and increments the amendment's `version` by 1."
        PRD: "**Step one** selects a failure-to-deposit rate from a days-late ladder: when `days_late` is 5 or fewer the rate is 200 basis points; when it is 6 through 15 the rate is 500 basis points; when it is 16 or more the rate is 1000 basis points."

        Design: Difficulty/boundary_precision_check/ftd_tier_flips_between_five_and_six_days_late
        """
        ctx = _ftd_scenario(api)
        first = fx.open_amendment(api, ctx["case_id"], accrual_through_date="2025-05-05")
        first_prepared = validate_success(
            api.prepare_amended_return(first["id"], {}, PREPARER_HEADERS)
        )
        assert first_prepared["penalty_cents"] == 10500

        voided = validate_success(
            api.void_amended_return(
                first["id"],
                f.void_payload(void_reason="Re-measuring the accrual one day later."),
                OFFICER_HEADERS,
            )
        )
        assert voided["status"] == "VOID"

        second = fx.open_amendment(
            api,
            ctx["case_id"],
            accrual_through_date="2025-05-06",
            supersedes_amended_return_id=first["id"],
        )
        second_prepared = validate_success(
            api.prepare_amended_return(second["id"], {}, PREPARER_HEADERS)
        )

        assert_amendment_money(
            second_prepared,
            days_late=6,
            tax_delta_cents=200000,
            deposit_shortfall_cents=200000,
            interest_cents=263,
            penalty_cents=15000,
            voluntary_reduction_applied=True,
        )
        assert second_prepared["penalty_cents"] - first_prepared["penalty_cents"] == 4500
        assert validate_success(api.get_amended_return(first["id"], PREPARER_HEADERS))[
            "status"
        ] == "VOID"
        assert second_prepared["status"] == "PREPARED"
        assert_case_rollups(fx.read_case(api, ctx["case_id"]), total_exposure_cents=215263)


class TestVoluntaryReductionSuppression:
    def test_an_existing_agency_notice_suppresses_the_voluntary_reduction(self, api):
        """With a notice already on the same employer, agency, tax year and quarter the
        scaled penalty stands unreduced at 87500 cents instead of 65625.

        PRD: "The reduction applies when no agency notice exists whose employer, agency, tax year and quarter match the case's four-part key; existence alone suppresses it, in *any* `response_status` and *any* `abatement_status`."
        PRD: "When the reduction applies, `penalty_cents` is the scaled amount multiplied by 7500 (that is, ten thousand less the 2500-basis-point reduction), divided by ten thousand, rounded half up, and `voluntary_reduction_applied` is recorded as true; when a matching notice exists, `penalty_cents` is the scaled amount unchanged and `voluntary_reduction_applied` is recorded as false."

        Design: Corner/calculations/an_existing_agency_notice_suppresses_the_voluntary_reduction_constant
        """
        ctx = fx.federal_categorized(api)
        notice = fx.notice_scenario(
            api,
            employer_id=ctx["employer_id"],
            agency_id=ctx["agency_id"],
            correction_case_id=ctx["case_id"],
            tax_year=2025,
            quarter=1,
        )["notice"]
        assert notice["response_status"] == "RECEIVED"
        assert notice["abatement_status"] == "NONE"

        amendment = fx.open_amendment(api, ctx["case_id"])
        prepared = validate_success(
            api.prepare_amended_return(amendment["id"], {}, PREPARER_HEADERS)
        )

        assert_amendment_money(
            prepared,
            tax_delta_cents=250000,
            deposit_shortfall_cents=250000,
            days_late=365,
            interest_cents=20000,
            penalty_cents=87500,
            voluntary_reduction_applied=False,
        )
        assert prepared["penalty_cents"] != 65625
        assert_case_rollups(fx.read_case(api, ctx["case_id"]), total_exposure_cents=357500)
