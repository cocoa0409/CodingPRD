"""Quarterly filings, segregation of duties, and year-end package gates."""
import pytest

from test_helpers import (
    ApiErrorId,
    accept_filing,
    create_employer,
    create_filing,
    create_rule_pack,
    create_year_end_package,
    get_filing,
    make_compliance_officer_headers,
    make_payroll_admin_headers,
    prepare_filing,
    reject_filing,
    set_clock,
    setup_accepted_filing,
    setup_active_worker,
    setup_finalized_pay_run,
    setup_registered_employer,
    submit_filing,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestFilingRejectReprepareCycle:
    def test_full_cycle_status_sequence(self, api):
        """PRD §3.10: "Submission is a `ComplianceOfficer` action moving `PREPARED → SUBMITTED`, gated by segregation of duties: the calling `X-User-ID` must differ from `prepared_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). A `ComplianceOfficer` then either accepts the filing (`SUBMITTED → ACCEPTED`, terminal) or rejects it (`SUBMITTED → REJECTED`)."
        PRD §3.10: "The `REJECTED` status loops back: preparation may be re-run from `REJECTED`, restoring the filing to `PREPARED` with fresh figures and a fresh `prepared_by_user_id`."

        Design: Difficulty/non_linear_state_machine/quarterly_filing_reject_reprepare_cycle
        """
        employer = setup_registered_employer("AA", agencies=())
        filing = create_filing(employer["id"], 2026, 1)

        assert prepare_filing(filing["id"], "admin-1")["status"] == "PREPARED"
        assert submit_filing(filing["id"], "officer-1")["status"] == "SUBMITTED"
        assert reject_filing(filing["id"], "officer-1")["status"] == "REJECTED"
        assert prepare_filing(filing["id"], "admin-2")["status"] == "PREPARED"
        assert submit_filing(filing["id"], "officer-1")["status"] == "SUBMITTED"
        assert accept_filing(filing["id"], "officer-1")["status"] == "ACCEPTED"

    def test_reprepare_recomputes_figures_and_restamps_preparer(self, api):
        """PRD §3.10: "The `prepared_by_user_id` is stamped with the calling `X-User-ID` and `prepared_at` with the logical clock's current instant; re-preparation after a rejection overwrites both."
        PRD §3.10: "Preparation works from either `OPEN` or `REJECTED` status (any other from-state yields `ERR_INVALID_STATE`) and recomputes the filing's figures from the current ledger: `total_cash_wages_cents` (household cash wages with `pay_date` inside the quarter over `ISSUED` paychecks), `futa_applies` (whether `total_cash_wages_cents` reaches the 100000-cent FUTA quarterly trigger — the boundary is exact), `futa_due_cents` and `suta_due_cents` (quarterly accruals over per-worker remaining wage bases), and `estimated_federal_payment_cents` (the safe-harbor quarterly figure)."

        Design: Difficulty/non_linear_state_machine/quarterly_filing_reject_reprepare_cycle
        """
        employer = setup_registered_employer("AA", agencies=())
        filing = create_filing(employer["id"], 2026, 1)

        first = prepare_filing(filing["id"], "admin-1")
        assert first["prepared_by_user_id"] == "admin-1"
        submit_filing(filing["id"], "officer-1")
        reject_filing(filing["id"], "officer-1")

        second = prepare_filing(filing["id"], "admin-2")
        assert second["prepared_by_user_id"] == "admin-2"
        # The ledger never changed: deterministic recompute of zero-wage figures.
        assert second["total_cash_wages_cents"] == 0
        assert second["futa_applies"] is False
        assert second["futa_due_cents"] == 0
        assert first["futa_due_cents"] == second["futa_due_cents"]


class TestFilingGuards:
    def test_accept_from_open_returns_invalid_state(self, api):
        """PRD §3.10: "A `ComplianceOfficer` then either accepts the filing (`SUBMITTED → ACCEPTED`, terminal) or rejects it (`SUBMITTED → REJECTED`)."
        PRD §2.8: "**State-machine preconditions** — the target transition's `from`-state and any parent-status gates; failure yields `ERR_INVALID_STATE`, with the pay-run-finalize staleness gate surfacing as `ERR_PAYRUN_STALE`."

        Design: Corner/state_machines/filing_accept_from_open_returns_invalid_state
        """
        employer = setup_registered_employer("AA", agencies=())
        filing = create_filing(employer["id"], 2026, 1)
        assert filing["status"] == "OPEN"
        resp = api.accept_quarterly_filing(
            filing["id"], make_compliance_officer_headers()
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_prepare_before_quarter_close_returns_422(self, api):
        """PRD §3.10: "Preparation is a `PayrollAdmin` action that requires the logical-clock current date to be strictly after the last day of the filing quarter — preparing on or before quarter close is rejected with `ERR_QUARTER_NOT_CLOSED` (HTTP 422)."
        PRD §2.5: "The logical clock's default value, before any client has set it, is exactly **2026-08-01T00:00:00Z** — it never silently falls back to wall-clock time."

        Design: Corner/validations/filing_prepare_before_quarter_close_returns_422
        """
        employer = setup_registered_employer("AA", agencies=())
        filing = create_filing(employer["id"], 2026, 3)
        # Default clock 2026-08-01 falls inside Q3 (ends 2026-09-30).
        resp = api.prepare_quarterly_filing(filing["id"], make_payroll_admin_headers())
        validate_error(resp, ApiErrorId.ERR_QUARTER_NOT_CLOSED)

    def test_duplicate_filing_returns_409(self, api):
        """PRD §3.10: "A `PayrollAdmin` opens a `QuarterlyFiling` for an employer by supplying `tax_year` and `quarter` (1–4); a duplicate filing for the same (employer, `tax_year`, `quarter`) is rejected with `ERR_DUPLICATE_FILING` (HTTP 409)."

        Design: Corner/validations/duplicate_filing_returns_409
        """
        employer = setup_registered_employer("AA", agencies=())
        create_filing(employer["id"], 2026, 1)
        resp = api.create_quarterly_filing(
            employer["id"], {"tax_year": 2026, "quarter": 1}, make_payroll_admin_headers()
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_FILING)


class TestYearEndFilingsGate:
    def test_finalize_without_any_filings_returns_filings_incomplete(self, api):
        """PRD §3.12: "Finalization is a `ComplianceOfficer` action with three preconditions: the package must be in `DRAFT` (else `ERR_INVALID_STATE`); all four `QuarterlyFiling` records for the (employer, `tax_year`) must exist and be `ACCEPTED` (else `ERR_FILINGS_INCOMPLETE`, HTTP 422); and every worker with an `ISSUED` paycheck in `tax_year` must have a non-null `ssn` (else `ERR_MISSING_SSN`, HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/year_end_finalize_requires_accepted_filings
        """
        employer = setup_registered_employer("AA", agencies=())
        package = create_year_end_package(employer["id"], 2026)
        resp = api.finalize_year_end_package(
            package["id"], make_compliance_officer_headers()
        )
        validate_error(resp, ApiErrorId.ERR_FILINGS_INCOMPLETE)

    def test_finalize_with_only_three_accepted_filings_still_incomplete(self, api):
        """PRD §3.12: "Finalization is a `ComplianceOfficer` action with three preconditions: the package must be in `DRAFT` (else `ERR_INVALID_STATE`); all four `QuarterlyFiling` records for the (employer, `tax_year`) must exist and be `ACCEPTED` (else `ERR_FILINGS_INCOMPLETE`, HTTP 422); and every worker with an `ISSUED` paycheck in `tax_year` must have a non-null `ssn` (else `ERR_MISSING_SSN`, HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/year_end_finalize_requires_accepted_filings
        """
        employer = setup_registered_employer("AA", agencies=())
        set_clock("2027-01-16T00:00:00Z")
        for quarter in (1, 2, 3):
            setup_accepted_filing(employer["id"], 2026, quarter)
        package = create_year_end_package(employer["id"], 2026)
        resp = api.finalize_year_end_package(
            package["id"], make_compliance_officer_headers()
        )
        validate_error(resp, ApiErrorId.ERR_FILINGS_INCOMPLETE)
        rows, _meta = validate_paginated(
            api.list_year_end_packages(employer["id"], make_payroll_admin_headers())
        )
        assert rows[0]["status"] == "DRAFT"


class TestYearEndDuplicatesAndSsn:
    def test_duplicate_year_end_package_returns_409(self, api):
        """PRD §3.12: "A `PayrollAdmin` opens a `YearEndPackage` for an employer by supplying `tax_year`; a duplicate package for the same (employer, `tax_year`) is rejected with `ERR_DUPLICATE_YEAR_END_PACKAGE` (HTTP 409)."

        Design: Corner/validations/duplicate_year_end_package_returns_409
        """
        employer = setup_registered_employer("AA", agencies=())
        create_year_end_package(employer["id"], 2026)
        resp = api.create_year_end_package(
            employer["id"], {"tax_year": 2026}, make_payroll_admin_headers()
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_YEAR_END_PACKAGE)

    def test_finalize_with_wage_earner_missing_ssn_returns_422(self, api):
        """PRD §3.4: "The `ssn` may be deferred — it is not required at create time — but every worker who has an `ISSUED` paycheck in the reporting year must have a non-null `ssn` before the year-end package can be finalized."
        PRD §3.12: "Finalization is a `ComplianceOfficer` action with three preconditions: the package must be in `DRAFT` (else `ERR_INVALID_STATE`); all four `QuarterlyFiling` records for the (employer, `tax_year`) must exist and be `ACCEPTED` (else `ERR_FILINGS_INCOMPLETE`, HTTP 422); and every worker with an `ISSUED` paycheck in `tax_year` must have a non-null `ssn` (else `ERR_MISSING_SSN`, HTTP 422)."

        Design: Corner/validations/year_end_finalize_missing_ssn_returns_422
        """
        employer, worker, _a = setup_active_worker(
            "AA",
            agreement_overrides={"guaranteed_minutes_per_week": 2400},
            agencies=("NEW_HIRE_DIRECTORY", "SIT_WITHHOLDING", "SUTA"),
        )
        setup_finalized_pay_run(employer["id"])

        set_clock("2027-01-16T00:00:00Z")
        for quarter in (1, 2, 3, 4):
            setup_accepted_filing(employer["id"], 2026, quarter)

        package = create_year_end_package(employer["id"], 2026)
        resp = api.finalize_year_end_package(
            package["id"], make_compliance_officer_headers()
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_SSN)

        rows, _meta = validate_paginated(
            api.list_year_end_packages(employer["id"], make_payroll_admin_headers())
        )
        assert rows[0]["status"] == "DRAFT"
