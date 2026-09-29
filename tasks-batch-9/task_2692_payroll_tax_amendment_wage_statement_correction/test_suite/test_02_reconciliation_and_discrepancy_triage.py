"""The three-way reconciliation, the deposit waterfall and discrepancy triage.

Reconciliation is the only origin of discrepancies, so this file exercises the
variance boundary between a clean run and a one-cent run, the chronological
deposit waterfall, the exclusion of dismissed rows from the delta rollup, the
filed-return prerequisite, and the empty-case guard on amendment creation.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ALREADY_TERMINAL,
    ERR_CASE_HAS_NO_DISCREPANCIES,
    ERR_NO_FILED_RETURN_FOR_PERIOD,
)
from test_helpers.assertions import (
    assert_amendment_money,
    assert_case_dimensions,
    assert_case_rollups,
    assert_pagination,
)
from test_helpers.constants import CANON_CLOCK, DEFAULT_LIMIT
from test_helpers.test_users import ANALYST_HEADERS, PREPARER_HEADERS


EARLY_DEPOSIT = {
    "deposit_due_date": "2025-02-19",
    "deposit_date": "2025-02-19",
    "amount_cents": 40000,
    "obligation_amount_cents": 150000,
}
LATE_DEPOSIT = {
    "deposit_due_date": "2025-03-19",
    "deposit_date": "2025-03-19",
    "amount_cents": 150000,
    "obligation_amount_cents": 100000,
}


class TestVarianceBoundary:
    def test_reconcile_at_zero_variance_is_terminal_and_emits_nothing(self, api):
        """A register total that matches the filed figures exactly emits no
        discrepancy, and the clean answer is final.

        PRD: "When the run emits no discrepancy at all, the case transitions `NOT_RUN → NO_VARIANCE`: `filing_status` stays at `FILING_NOT_REQUIRED`, `statement_status` stays at `STMT_NOT_REQUIRED`, `open_discrepancy_count` is recomputed to 0, and the case's `version` is incremented by 1."
        PRD: "`NO_VARIANCE` is terminal for the reconciliation dimension — a case that reconciled cleanly can never be reconciled again, and an attempt to do so is refused with `ERR_ALREADY_TERMINAL`."

        Design: Difficulty/boundary_precision_check/reconcile_at_zero_variance_versus_one_cent_variance
        """
        ctx = fx.federal_scenario(
            api,
            with_deposit=False,
            register_totals=((1000000, 150000),),
            filed_return_overrides={
                "reported_taxable_wage_cents": 1000000,
                "reported_withheld_cents": 150000,
            },
        )
        opening_version = ctx["case"]["version"]

        case = validate_success(api.reconcile_case(ctx["case_id"], {}, ANALYST_HEADERS))

        assert_case_dimensions(
            case,
            status="OPEN",
            detection_status="NO_VARIANCE",
            filing_status="FILING_NOT_REQUIRED",
            statement_status="STMT_NOT_REQUIRED",
        )
        assert_case_rollups(case, open_discrepancy_count=0)
        assert case["version"] == opening_version + 1
        assert fx.case_discrepancies(api, ctx["case_id"]) == []

        validate_error(
            api.reconcile_case(ctx["case_id"], {}, ANALYST_HEADERS), ERR_ALREADY_TERMINAL, 409
        )

    def test_reconcile_at_one_cent_variance_emits_a_single_wage_discrepancy(self, api):
        """One cent of difference is a difference: the wage discrepancy is emitted
        with an amount of exactly one cent and both optional references null.

        PRD: "If the register wage total differs from `reported_taxable_wage_cents`, a discrepancy with `detected_category` `TAXABLE_WAGE` is emitted whose `amount_cents` is the register wage total minus the reported taxable wage, with `employee_id` and `register_line_id` both left null."
        PRD: "Two further dimensions may move in the same request, and they move on different triggers: `filing_status` is set to `FILING_PENDING` when any emitted discrepancy carries a `detected_category` of `TAXABLE_WAGE`, `WITHHOLDING` or `DEPOSIT_SHORTFALL`, and `statement_status` is set to `STMT_PENDING` when any emitted discrepancy carries a `detected_category` of `JURISDICTION_ASSIGNMENT`."

        Design: Difficulty/boundary_precision_check/reconcile_at_zero_variance_versus_one_cent_variance
        """
        ctx = fx.federal_scenario(
            api,
            with_deposit=False,
            register_totals=((1000000, 150000),),
            filed_return_overrides={
                "reported_taxable_wage_cents": 999999,
                "reported_withheld_cents": 150000,
            },
        )

        case = validate_success(api.reconcile_case(ctx["case_id"], {}, ANALYST_HEADERS))

        assert_case_dimensions(
            case,
            status="OPEN",
            detection_status="VARIANCE_FOUND",
            filing_status="FILING_PENDING",
            statement_status="STMT_NOT_REQUIRED",
        )
        assert_case_rollups(case, open_discrepancy_count=1)

        rows = fx.case_discrepancies(api, ctx["case_id"])
        assert len(rows) == 1
        only = rows[0]
        assert only["detected_category"] == "TAXABLE_WAGE"
        assert only["amount_cents"] == 1
        assert only["emission_index"] == 0
        assert only["status"] == "OPEN"
        assert only["employee_id"] is None
        assert only["register_line_id"] is None


class TestDepositWaterfall:
    def test_deposit_waterfall_is_insensitive_to_deposit_creation_order(self, api):
        """The waterfall reads the obligations and the cash in their own pinned
        orders, so posting the later deposit first changes nothing.

        PRD: "Those cleared deposits are read twice, in two different orders: in **obligation fill order**, sorted by `deposit_due_date` ascending and then by `created_at` ascending, and in **chronological cash order**, sorted by `deposit_date` ascending and then by `created_at` ascending."
        PRD: "Finally, if the applied-cash total is strictly less than the total obligation, a discrepancy with `detected_category` `DEPOSIT_SHORTFALL` is emitted whose `amount_cents` is the total obligation minus the applied-cash total."

        Design: Corner/calculations/deposit_waterfall_is_insensitive_to_deposit_creation_order
        """
        fx.set_clock(api, CANON_CLOCK)
        agency = fx.make_federal_agency(api)

        def build(fein, deposits):
            employer = fx.make_employer(api, fein=fein)
            employee = fx.make_employee(api, employer["id"])
            fx.make_register_line(
                api,
                employer["id"],
                employee["id"],
                agency["id"],
                taxable_wage_cents=1000000,
                withheld_cents=150000,
            )
            fx.make_filed_return(
                api,
                employer["id"],
                agency["id"],
                reported_taxable_wage_cents=1000000,
                reported_withheld_cents=150000,
            )
            for deposit in deposits:
                fx.make_deposit_record(api, employer["id"], agency["id"], **deposit)
            case = fx.make_correction_case(api, employer["id"], agency["id"])
            reconciled = validate_success(api.reconcile_case(case["id"], {}, ANALYST_HEADERS))
            return reconciled, fx.case_discrepancies(api, case["id"])

        chronological, chrono_rows = build("11-1111111", [EARLY_DEPOSIT, LATE_DEPOSIT])
        reversed_order, reversed_rows = build("22-2222222", [LATE_DEPOSIT, EARLY_DEPOSIT])

        for case, rows in ((chronological, chrono_rows), (reversed_order, reversed_rows)):
            assert_case_dimensions(
                case,
                detection_status="VARIANCE_FOUND",
                filing_status="FILING_PENDING",
                statement_status="STMT_NOT_REQUIRED",
            )
            assert len(rows) == 1, rows
            shortfall = rows[0]
            assert shortfall["detected_category"] == "DEPOSIT_SHORTFALL"
            assert shortfall["amount_cents"] == 60000
            assert shortfall["emission_index"] == 0
            assert shortfall["employee_id"] is None
            assert shortfall["register_line_id"] is None


class TestTriageAndTheDeltaRollup:
    def test_dismissed_discrepancy_is_excluded_from_the_delta_rollup(self, api):
        """A dismissed withholding row leaves the tax delta at zero, which zeroes
        interest while the deposit-shortfall penalty still stands.

        PRD: "Rows in `DISMISSED`, `SUPERSEDED` and `RESOLVED` are excluded, and the analyst-confirmed `category` is what selects rows — `detected_category` never participates."
        PRD: "On success the discrepancy transitions `CATEGORIZED → DISMISSED`, the case's `open_discrepancy_count` and `dominant_root_cause_code` are both recomputed, and the discrepancy's `version` is incremented by 1."

        Design: Corner/calculations/dismissed_discrepancy_is_excluded_from_the_delta_rollup
        """
        ctx = fx.federal_categorized(api)
        withholding = ctx["discrepancies"]["WITHHOLDING"]

        dismissed = validate_success(
            api.dismiss_discrepancy(withholding["id"], f.dismiss_payload(), ANALYST_HEADERS)
        )
        assert dismissed["status"] == "DISMISSED"

        case = fx.read_case(api, ctx["case_id"])
        assert_case_rollups(case, open_discrepancy_count=2)

        amendment = fx.open_amendment(api, ctx["case_id"])
        prepared = validate_success(
            api.prepare_amended_return(amendment["id"], {}, PREPARER_HEADERS)
        )

        assert_amendment_money(
            prepared,
            wage_delta_cents=250000,
            tax_delta_cents=0,
            deposit_shortfall_cents=250000,
            days_late=365,
            interest_cents=0,
            penalty_cents=18750,
            interest_variant="STATUTORY_DAILY",
            voluntary_reduction_applied=True,
        )
        assert_case_rollups(fx.read_case(api, ctx["case_id"]), total_exposure_cents=18750)

    def test_reconcile_without_a_filed_return_stops_before_detection_runs(self, api):
        """The filed-return prerequisite is checked before any comparison, so the
        detection dimension does not move and the case version does not change.

        PRD: "Before it may run, the case must be in `status` `OPEN`, and exactly one filed return whose `status` is `FILED` or `AMENDED` must exist on the case's scope."
        PRD: "If no such return exists, the run is refused with `ERR_NO_FILED_RETURN_FOR_PERIOD`."

        Design: Corner/validations/reconcile_without_a_filed_return_stops_before_detection_runs
        """
        fx.set_clock(api, CANON_CLOCK)
        employer = fx.make_employer(api)
        agency = fx.make_federal_agency(api)
        employee = fx.make_employee(api, employer["id"])
        fx.make_register_line(api, employer["id"], employee["id"], agency["id"])
        case = fx.make_correction_case(api, employer["id"], agency["id"])
        assert case["version"] == 1

        validate_error(
            api.reconcile_case(case["id"], {}, ANALYST_HEADERS),
            ERR_NO_FILED_RETURN_FOR_PERIOD,
            422,
        )

        unchanged = fx.read_case(api, case["id"])
        assert_case_dimensions(
            unchanged,
            status="OPEN",
            detection_status="NOT_RUN",
            filing_status="FILING_NOT_REQUIRED",
            statement_status="STMT_NOT_REQUIRED",
        )
        assert unchanged["version"] == 1
        assert fx.case_discrepancies(api, case["id"]) == []

    def test_amendment_create_on_a_case_with_no_discrepancies_is_refused(self, api):
        """Both of the two states that mean "no discrepancy rows at all" — detection
        never run and detection run clean — refuse amendment creation.

        PRD: "First, an amendment may not be opened on a case that reconciliation has found nothing to correct: if the case has no discrepancy rows at all — which is exactly the situation when `detection_status` is `NOT_RUN` or `NO_VARIANCE` — the creation is refused with `ERR_CASE_HAS_NO_DISCREPANCIES`."

        Design: Corner/errors/amendment_create_on_a_case_with_no_discrepancies_returns_case_has_no_discrepancies
        """
        ctx = fx.federal_scenario(
            api,
            with_deposit=False,
            register_totals=((1000000, 150000),),
            filed_return_overrides={
                "reported_taxable_wage_cents": 1000000,
                "reported_withheld_cents": 150000,
            },
        )

        not_run = fx.read_case(api, ctx["case_id"])
        assert_case_dimensions(not_run, detection_status="NOT_RUN")
        validate_error(
            api.create_amended_return(
                f.amended_return_payload(ctx["case_id"], not_run["version"]), PREPARER_HEADERS
            ),
            ERR_CASE_HAS_NO_DISCREPANCIES,
            409,
        )

        clean = validate_success(api.reconcile_case(ctx["case_id"], {}, ANALYST_HEADERS))
        assert_case_dimensions(
            clean, detection_status="NO_VARIANCE", filing_status="FILING_NOT_REQUIRED"
        )
        validate_error(
            api.create_amended_return(
                f.amended_return_payload(ctx["case_id"], clean["version"]), PREPARER_HEADERS
            ),
            ERR_CASE_HAS_NO_DISCREPANCIES,
            409,
        )

    def test_list_endpoints_apply_the_default_limit_together_with_a_filter(self, api):
        """With `limit` omitted the window is ten rows wide, and `total_count`
        reports the filtered match count rather than the window size.

        PRD: "`limit` defaults to 10 when omitted, may not be smaller than 1, and may not be larger than 100."
        PRD: "`offset` defaults to 0 and may not be negative."

        Design: Corner/endpoints/list_endpoints_apply_the_default_limit_together_with_a_filter
        """
        fx.set_clock(api, CANON_CLOCK)
        busy = fx.make_employer(api, fein="11-1111111")
        quiet = fx.make_employer(api, fein="22-2222222")
        for index in range(12):
            fx.make_employee(api, busy["id"], national_id_last4=f"{1000 + index}")
        for index in range(3):
            fx.make_employee(api, quiet["id"], national_id_last4=f"{2000 + index}")

        rows, meta = validate_paginated(
            api.list_employees({"employer_id": busy["id"]}, ANALYST_HEADERS)
        )
        assert len(rows) == DEFAULT_LIMIT
        assert_pagination(meta, limit=DEFAULT_LIMIT, offset=0, total_count=12, has_more=True)
        assert all(row["employer_id"] == busy["id"] for row in rows)

        quiet_rows, quiet_meta = validate_paginated(
            api.list_employees({"employer_id": quiet["id"]}, ANALYST_HEADERS)
        )
        assert len(quiet_rows) == 3
        assert_pagination(quiet_meta, limit=DEFAULT_LIMIT, offset=0, total_count=3, has_more=False)
