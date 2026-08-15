"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints, and validates setup steps with get_success_data() so failures
surface as clear "Setup failed" errors rather than confusing assertions.

Identity threading: HouseholdClient calls always carry the owning employer's
id and Worker calls always carry the owning worker's id — the entity-backed
ownership checks compare these ids against the resource's parent.
"""
from typing import Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    DEFAULTS,
    classification_answers_contractor,
    classification_answers_employee,
    create_agreement_payload,
    create_deposit_payload,
    create_employer_payload,
    create_leave_request_payload,
    create_pay_run_payload,
    create_quarterly_filing_payload,
    create_state_rule_pack_payload,
    create_timesheet_payload,
    create_worker_payload,
    create_workers_comp_policy_payload,
    create_year_end_package_payload,
)
from .test_users import (
    make_compliance_officer_headers,
    make_household_client_headers,
    make_payroll_admin_headers,
    make_worker_headers,
)

ALL_AGENCIES = ("NEW_HIRE_DIRECTORY", "SIT_WITHHOLDING", "SUTA")

_ACCOUNT_SEQUENCE = {"n": 0}


def _next_account_number(agency: str) -> str:
    _ACCOUNT_SEQUENCE["n"] += 1
    return f"{agency[:3]}-{_ACCOUNT_SEQUENCE['n']:04d}"


# ---------------------------------------------------------------------------
# Configuration + employer onboarding
# ---------------------------------------------------------------------------

def create_rule_pack(state_code: str = "AA", **overrides) -> dict:
    """Create a state rule pack as PayrollAdmin. Returns the pack."""
    payload = create_state_rule_pack_payload(state_code, **overrides)
    resp = api_client.create_state_rule_pack(payload, make_payroll_admin_headers())
    return get_success_data(resp)


def create_employer(primary_state_code: str = "AA", **overrides) -> dict:
    """Onboard a household employer as PayrollAdmin. Returns the employer (ONBOARDING)."""
    payload = create_employer_payload(primary_state_code=primary_state_code, **overrides)
    resp = api_client.create_employer(payload, make_payroll_admin_headers())
    return get_success_data(resp)


def get_employer(employer_id: str) -> dict:
    resp = api_client.get_employer(employer_id, make_payroll_admin_headers())
    return get_success_data(resp)


def suspend_employer(employer_id: str, officer_id: str = "officer-1") -> dict:
    resp = api_client.suspend_employer(employer_id, make_compliance_officer_headers(officer_id))
    return get_success_data(resp)


def reinstate_employer(employer_id: str, officer_id: str = "officer-1") -> dict:
    resp = api_client.reinstate_employer(employer_id, make_compliance_officer_headers(officer_id))
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Registrations (OCC on the employer version)
# ---------------------------------------------------------------------------

def create_registration(employer_id: str, state_code: str, agency: str,
                        expected_employer_version: Optional[int] = None) -> dict:
    """Open a DRAFT registration; reads the fresh employer version when not given."""
    if expected_employer_version is None:
        expected_employer_version = get_employer(employer_id)["version"]
    payload = {
        "state_code": state_code,
        "agency": agency,
        "expected_employer_version": expected_employer_version,
    }
    resp = api_client.create_registration(employer_id, payload, make_payroll_admin_headers())
    return get_success_data(resp)


def submit_registration(registration_id: str) -> dict:
    resp = api_client.submit_registration(registration_id, make_payroll_admin_headers())
    return get_success_data(resp)


def activate_registration(registration_id: str, agency: str = "REG") -> dict:
    payload = {"agency_account_number": _next_account_number(agency)}
    resp = api_client.activate_registration(registration_id, payload, make_payroll_admin_headers())
    return get_success_data(resp)


def _ensure_rule_pack(state_code: str) -> None:
    """Seed the state's rule pack unless the test already created one.

    PRD §3.2 requires the employer's primary state to have a rule pack before
    onboarding; tests that need a custom pack create it first, so a duplicate
    conflict here means "already seeded" and is tolerated.
    """
    resp = api_client.create_state_rule_pack(
        create_state_rule_pack_payload(state_code), make_payroll_admin_headers()
    )
    if resp.status_code == 409 and \
            resp.json().get("data", {}).get("error_id") == "ERR_DUPLICATE_RULE_PACK":
        return
    get_success_data(resp)


def setup_registered_employer(state_code: str = "AA",
                              agencies: Tuple[str, ...] = ALL_AGENCIES,
                              **employer_overrides) -> dict:
    """Employer with the given registrations all ACTIVE (employer flips to ACTIVE
    on the first activation). Returns the employer as of the last read."""
    _ensure_rule_pack(state_code)
    employer = create_employer(primary_state_code=state_code, **employer_overrides)
    for agency in agencies:
        reg = create_registration(employer["id"], state_code, agency)
        submit_registration(reg["id"])
        activate_registration(reg["id"], agency)
    return get_employer(employer["id"])


# ---------------------------------------------------------------------------
# Workers, classification, agreements, activation
# ---------------------------------------------------------------------------

def create_worker(employer_id: str, **overrides) -> dict:
    """Add a worker as the owning HouseholdClient."""
    payload = create_worker_payload(**overrides)
    resp = api_client.create_worker(
        employer_id, payload, make_household_client_headers(employer_id)
    )
    return get_success_data(resp)


def get_worker(worker_id: str) -> dict:
    resp = api_client.get_worker(worker_id, make_payroll_admin_headers())
    return get_success_data(resp)


def classify_worker(employer_id: str, worker_id: str, classification: str = "EMPLOYEE") -> dict:
    answers = (
        classification_answers_employee()
        if classification == "EMPLOYEE"
        else classification_answers_contractor()
    )
    resp = api_client.classify_worker(
        worker_id,
        {"classification_answers": answers},
        make_household_client_headers(employer_id),
    )
    return get_success_data(resp)


def create_agreement(employer_id: str, worker_id: str,
                     expected_worker_version: Optional[int] = None, **overrides) -> dict:
    """Create an agreement (supersedes the worker's prior ACTIVE agreement).

    Reads the worker's fresh version when expected_worker_version is not given.
    """
    if expected_worker_version is None:
        expected_worker_version = get_worker(worker_id)["version"]
    payload = create_agreement_payload(expected_worker_version, **overrides)
    resp = api_client.create_agreement(
        worker_id, payload, make_household_client_headers(employer_id)
    )
    return get_success_data(resp)


def activate_worker(employer_id: str, worker_id: str,
                    new_hire_report_date: str = DEFAULTS["NEW_HIRE_REPORT_DATE"]) -> dict:
    resp = api_client.activate_worker(
        worker_id,
        {"new_hire_report_date": new_hire_report_date},
        make_household_client_headers(employer_id),
    )
    return get_success_data(resp)


def terminate_worker(employer_id: str, worker_id: str) -> dict:
    resp = api_client.terminate_worker(worker_id, make_household_client_headers(employer_id))
    return get_success_data(resp)


def setup_classified_worker(state_code: str = "AA",
                            worker_overrides: Optional[dict] = None,
                            agreement_overrides: Optional[dict] = None,
                            employer_overrides: Optional[dict] = None,
                            agencies: Tuple[str, ...] = ("NEW_HIRE_DIRECTORY",),
                            ) -> Tuple[dict, dict, dict]:
    """Employer (registered for the given agencies) + CLASSIFIED EMPLOYEE worker
    with an ACTIVE agreement. Returns (employer, worker, agreement)."""
    employer = setup_registered_employer(
        state_code, agencies=agencies, **(employer_overrides or {})
    )
    worker = create_worker(
        employer["id"], work_state_code=state_code, **(worker_overrides or {})
    )
    classify_worker(employer["id"], worker["id"], "EMPLOYEE")
    agreement = create_agreement(employer["id"], worker["id"], **(agreement_overrides or {}))
    return employer, get_worker(worker["id"]), agreement


def setup_active_worker(state_code: str = "AA",
                        worker_overrides: Optional[dict] = None,
                        agreement_overrides: Optional[dict] = None,
                        employer_overrides: Optional[dict] = None,
                        agencies: Tuple[str, ...] = ("NEW_HIRE_DIRECTORY",),
                        new_hire_report_date: str = DEFAULTS["NEW_HIRE_REPORT_DATE"],
                        ) -> Tuple[dict, dict, dict]:
    """Employer + ACTIVE EMPLOYEE worker with an ACTIVE agreement.
    Returns (employer, worker, agreement)."""
    employer, worker, agreement = setup_classified_worker(
        state_code,
        worker_overrides=worker_overrides,
        agreement_overrides=agreement_overrides,
        employer_overrides=employer_overrides,
        agencies=agencies,
    )
    activate_worker(employer["id"], worker["id"], new_hire_report_date)
    return employer, get_worker(worker["id"]), agreement


# ---------------------------------------------------------------------------
# Timesheets
# ---------------------------------------------------------------------------

def create_timesheet(worker_id: str, period_start: str, period_end: str,
                     entries: List[dict]) -> dict:
    payload = create_timesheet_payload(period_start, period_end, entries)
    resp = api_client.create_timesheet(worker_id, payload, make_worker_headers(worker_id))
    return get_success_data(resp)


def submit_timesheet(worker_id: str, timesheet_id: str) -> dict:
    resp = api_client.submit_timesheet(timesheet_id, make_worker_headers(worker_id))
    return get_success_data(resp)


def approve_timesheet(employer_id: str, timesheet_id: str) -> dict:
    resp = api_client.approve_timesheet(
        timesheet_id, make_household_client_headers(employer_id)
    )
    return get_success_data(resp)


def reject_timesheet(employer_id: str, timesheet_id: str) -> dict:
    resp = api_client.reject_timesheet(
        timesheet_id, make_household_client_headers(employer_id)
    )
    return get_success_data(resp)


def get_timesheet(timesheet_id: str) -> dict:
    resp = api_client.get_timesheet(timesheet_id, make_payroll_admin_headers())
    return get_success_data(resp)


def create_approved_timesheet(employer_id: str, worker_id: str,
                              period_start: str, period_end: str,
                              entries: List[dict]) -> dict:
    """Create -> submit -> approve. Returns the APPROVED timesheet."""
    ts = create_timesheet(worker_id, period_start, period_end, entries)
    submit_timesheet(worker_id, ts["id"])
    return approve_timesheet(employer_id, ts["id"])


# ---------------------------------------------------------------------------
# Pay runs and paychecks
# ---------------------------------------------------------------------------

def create_pay_run(employer_id: str, period_start: str, period_end: str,
                   pay_date: str) -> dict:
    payload = create_pay_run_payload(period_start, period_end, pay_date)
    resp = api_client.create_pay_run(employer_id, payload, make_payroll_admin_headers())
    return get_success_data(resp)


def get_pay_run(pay_run_id: str) -> dict:
    resp = api_client.get_pay_run(pay_run_id, make_payroll_admin_headers())
    return get_success_data(resp)


def calculate_pay_run(pay_run_id: str) -> dict:
    resp = api_client.calculate_pay_run(pay_run_id, make_payroll_admin_headers())
    return get_success_data(resp)


def finalize_pay_run(pay_run_id: str) -> dict:
    resp = api_client.finalize_pay_run(pay_run_id, make_payroll_admin_headers())
    return get_success_data(resp)


def list_pay_run_paychecks(pay_run_id: str) -> List[dict]:
    resp = api_client.list_pay_run_paychecks(pay_run_id, make_payroll_admin_headers())
    data, _meta = validate_paginated(resp)
    return data


def list_worker_paychecks(worker_id: str) -> List[dict]:
    resp = api_client.list_worker_paychecks(worker_id, make_payroll_admin_headers())
    data, _meta = validate_paginated(resp)
    return data


def void_paycheck(paycheck_id: str) -> dict:
    resp = api_client.void_paycheck(paycheck_id, make_payroll_admin_headers())
    return get_success_data(resp)


def setup_calculated_pay_run(employer_id: str,
                             period_start: str = "2026-01-05",
                             period_end: str = "2026-01-12",
                             pay_date: str = "2026-01-12") -> dict:
    """Create an OPEN pay run and calculate it. Returns the CALCULATED pay run."""
    run = create_pay_run(employer_id, period_start, period_end, pay_date)
    return calculate_pay_run(run["id"])


def setup_finalized_pay_run(employer_id: str,
                            period_start: str = "2026-01-05",
                            period_end: str = "2026-01-12",
                            pay_date: str = "2026-01-12") -> dict:
    """Create -> calculate -> finalize. Returns the FINALIZED pay run."""
    run = setup_calculated_pay_run(employer_id, period_start, period_end, pay_date)
    return finalize_pay_run(run["id"])


# ---------------------------------------------------------------------------
# Leave
# ---------------------------------------------------------------------------

def create_leave_request(worker_id: str, start_date: str, end_date: str,
                         requested_minutes: int) -> dict:
    payload = create_leave_request_payload(start_date, end_date, requested_minutes)
    resp = api_client.create_leave_request(worker_id, payload, make_worker_headers(worker_id))
    return get_success_data(resp)


def approve_leave_request(employer_id: str, leave_id: str) -> dict:
    resp = api_client.approve_leave_request(
        leave_id, make_household_client_headers(employer_id)
    )
    return get_success_data(resp)


def deny_leave_request(employer_id: str, leave_id: str) -> dict:
    resp = api_client.deny_leave_request(leave_id, make_household_client_headers(employer_id))
    return get_success_data(resp)


def cancel_leave_request(worker_id: str, leave_id: str) -> dict:
    resp = api_client.cancel_leave_request(leave_id, make_worker_headers(worker_id))
    return get_success_data(resp)


def setup_worker_with_accrued_leave(approved_minutes_per_timesheet: Tuple[int, ...] = (2700,),
                                    state_code: str = "AA",
                                    ) -> Tuple[dict, dict]:
    """Employer + ACTIVE worker with approved timesheets accruing leave.

    Each tuple element creates one weekly timesheet (Mon..N entries of 540 min
    by default; a bare int N means a single N-minute entry on the Monday).
    Periods are consecutive weeks starting 2026-01-05.
    Returns (employer, worker).
    """
    employer, worker, _agreement = setup_active_worker(state_code=state_code)
    periods = [("2026-01-05", "2026-01-12"), ("2026-01-12", "2026-01-19"),
               ("2026-01-19", "2026-01-26"), ("2026-01-26", "2026-02-02")]
    for (start, end), minutes in zip(periods, approved_minutes_per_timesheet):
        if minutes == 2700:
            from .factories import make_work_entries
            entries = make_work_entries(start, [540, 540, 540, 540, 540])
        else:
            from .factories import make_work_entries
            entries = make_work_entries(start, [minutes])
        create_approved_timesheet(employer["id"], worker["id"], start, end, entries)
    return employer, get_worker(worker["id"])


# ---------------------------------------------------------------------------
# Tax accounts and deposits
# ---------------------------------------------------------------------------

def get_tax_accounts_by_type(employer_id: str, tax_year: Optional[int] = None) -> Dict[str, dict]:
    """List tax liability accounts keyed by tax_type (one per type per year)."""
    params = {"tax_year": tax_year} if tax_year is not None else None
    resp = api_client.list_tax_accounts(employer_id, make_payroll_admin_headers(), params=params)
    data, _meta = validate_paginated(resp)
    return {row["tax_type"]: row for row in data}


def create_deposit(employer_id: str, tax_year: int, quarter: int,
                   amount_cents: int, remitted_on: str) -> dict:
    payload = create_deposit_payload(tax_year, quarter, amount_cents, remitted_on)
    resp = api_client.create_deposit(employer_id, payload, make_payroll_admin_headers())
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Quarterly filings (segregation of duties: prepare as admin, submit as officer)
# ---------------------------------------------------------------------------

def create_filing(employer_id: str, tax_year: int, quarter: int) -> dict:
    payload = create_quarterly_filing_payload(tax_year, quarter)
    resp = api_client.create_quarterly_filing(employer_id, payload, make_payroll_admin_headers())
    return get_success_data(resp)


def get_filing(filing_id: str, employer_id: str) -> dict:
    resp = api_client.list_quarterly_filings(
        employer_id, make_payroll_admin_headers(), params={}
    )
    data, _meta = validate_paginated(resp)
    for row in data:
        if row["id"] == filing_id:
            return row
    raise AssertionError(f"Filing {filing_id} not found in employer {employer_id} list")


def prepare_filing(filing_id: str, preparer_id: str = "admin-1") -> dict:
    resp = api_client.prepare_quarterly_filing(
        filing_id, make_payroll_admin_headers(preparer_id)
    )
    return get_success_data(resp)


def submit_filing(filing_id: str, submitter_id: str = "officer-1") -> dict:
    resp = api_client.submit_quarterly_filing(
        filing_id, make_compliance_officer_headers(submitter_id)
    )
    return get_success_data(resp)


def accept_filing(filing_id: str, officer_id: str = "officer-1") -> dict:
    resp = api_client.accept_quarterly_filing(
        filing_id, make_compliance_officer_headers(officer_id)
    )
    return get_success_data(resp)


def reject_filing(filing_id: str, officer_id: str = "officer-1") -> dict:
    resp = api_client.reject_quarterly_filing(
        filing_id, make_compliance_officer_headers(officer_id)
    )
    return get_success_data(resp)


def setup_accepted_filing(employer_id: str, tax_year: int, quarter: int,
                          preparer_id: str = "admin-1",
                          submitter_id: str = "officer-1") -> dict:
    """Create -> prepare -> submit -> accept. Returns the ACCEPTED filing."""
    filing = create_filing(employer_id, tax_year, quarter)
    prepare_filing(filing["id"], preparer_id)
    submit_filing(filing["id"], submitter_id)
    return accept_filing(filing["id"], submitter_id)


# ---------------------------------------------------------------------------
# Workers' compensation policies
# ---------------------------------------------------------------------------

def create_policy(employer_id: str, state_code: str, coverage_start: str,
                  coverage_end: str, policy_number: str = "WC-1") -> dict:
    payload = create_workers_comp_policy_payload(
        state_code, coverage_start, coverage_end, policy_number
    )
    resp = api_client.create_workers_comp_policy(
        employer_id, payload, make_payroll_admin_headers()
    )
    return get_success_data(resp)


def bind_policy(policy_id: str) -> dict:
    resp = api_client.bind_workers_comp_policy(policy_id, make_payroll_admin_headers())
    return get_success_data(resp)


def lapse_policy(policy_id: str) -> dict:
    resp = api_client.lapse_workers_comp_policy(policy_id, make_payroll_admin_headers())
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Year-end packages
# ---------------------------------------------------------------------------

def create_year_end_package(employer_id: str, tax_year: int) -> dict:
    payload = create_year_end_package_payload(tax_year)
    resp = api_client.create_year_end_package(employer_id, payload, make_payroll_admin_headers())
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, make_payroll_admin_headers())
    return get_success_data(resp)
