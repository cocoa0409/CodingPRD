"""
Single-entity builders.

Every builder drives the public API — nothing is inserted behind the API's back
— and returns the created row's `data` object. Each one starts from a canonical
payload in `constants` and accepts keyword overrides, so a test that cares about
one field names only that field.

The runner restarts the service with an empty database before every test, so
builders are always called from scratch inside the test that needs them.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_success

from . import constants as C
from .api_client import ApiClient
from .test_users import (
    ADMIN,
    OFFICER,
    RECORDKEEPER,
    make_employer_headers,
    make_participant_headers,
)
from .types import Headers, JsonDict


def _merge(base: JsonDict, overrides: Dict[str, Any]) -> JsonDict:
    payload = dict(base)
    payload.update({k: v for k, v in overrides.items() if v is not None})
    return payload


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def set_clock(api: ApiClient, current_utc: str, headers: Headers = ADMIN) -> JsonDict:
    """Move the logical clock to `current_utc`."""
    return validate_success(api.set_current_utc({"current_utc": current_utc}, headers))


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
def create_program_year(api: ApiClient, base: Optional[JsonDict] = None,
                        headers: Headers = ADMIN, **overrides: Any) -> JsonDict:
    """Configure a program year. Defaults to 2026 at a 700000-cent ceiling."""
    payload = _merge(base or C.PROGRAM_YEAR_2026, overrides)
    return get_success_data(api.create_program_year(payload, headers))


def create_investment_option(api: ApiClient, base: Optional[JsonDict] = None,
                             headers: Headers = ADMIN, **overrides: Any) -> JsonDict:
    """Add one fund to the menu. Defaults to the 2045 target-date option."""
    payload = _merge(base or C.FUND_TDF2045, overrides)
    return get_success_data(api.create_investment_option(payload, headers))


def create_fund_menu(api: ApiClient, funds: Optional[List[JsonDict]] = None,
                     headers: Headers = ADMIN) -> List[JsonDict]:
    """Add several funds in order, returning the created rows in that order."""
    return [create_investment_option(api, fund, headers=headers)
            for fund in (funds if funds is not None else C.DEFAULT_FUND_MENU)]


# ---------------------------------------------------------------------------
# Employers
# ---------------------------------------------------------------------------
def create_employer(api: ApiClient, base: Optional[JsonDict] = None,
                    headers: Headers = ADMIN, **overrides: Any) -> JsonDict:
    """Enrol an employer in the register. Defaults to the 60-employee shop."""
    payload = _merge(base or C.EMPLOYER_DELTA, overrides)
    return get_success_data(api.create_employer(payload, headers))


def register_employer(api: ApiClient, employer_id: str,
                      base: Optional[JsonDict] = None,
                      headers: Optional[Headers] = None,
                      **overrides: Any) -> JsonDict:
    """
    Complete the employer's own registration. The employer acts under its own
    row identifier unless the caller names different headers.
    """
    payload = _merge(base or C.REGISTRATION_GENERIC, overrides)
    return validate_success(api.register_employer(
        employer_id, payload, headers or make_employer_headers(employer_id)))


def create_registered_employer(api: ApiClient, base: Optional[JsonDict] = None,
                               **overrides: Any) -> JsonDict:
    """Create an employer and immediately complete its registration."""
    employer = create_employer(api, base, **overrides)
    register_employer(api, employer["id"])
    return employer


def recount_employees(api: ApiClient, employer_id: str, employee_count: int,
                      effective_date: str, expected_employer_version: int,
                      headers: Optional[Headers] = None) -> JsonDict:
    """Restate an employer's headcount under optimistic concurrency control."""
    payload = {
        "employee_count": employee_count,
        "effective_date": effective_date,
        "expected_employer_version": expected_employer_version,
    }
    return validate_success(api.recount_employees(
        employer_id, payload, headers or make_employer_headers(employer_id)))


# ---------------------------------------------------------------------------
# Exemption certifications
# ---------------------------------------------------------------------------
def file_exemption(api: ApiClient, employer_id: str,
                   base: Optional[JsonDict] = None,
                   headers: Optional[Headers] = None, **overrides: Any) -> JsonDict:
    """File a qualified-plan exemption certification for the employer."""
    payload = _merge(base or C.EXEMPTION_401K, overrides)
    return get_success_data(api.create_exemption_certification(
        employer_id, payload, headers or make_employer_headers(employer_id)))


def decide_exemption(api: ApiClient, exemption_id: str, decision: str,
                     decision_note: Optional[str] = None,
                     headers: Headers = ADMIN) -> JsonDict:
    """Approve or reject a submitted certification."""
    payload: JsonDict = {"decision": decision}
    if decision_note is not None:
        payload["decision_note"] = decision_note
    return validate_success(
        api.decide_exemption_certification(exemption_id, payload, headers))


def revoke_exemption(api: ApiClient, exemption_id: str, revocation_reason: str,
                     headers: Headers = OFFICER) -> JsonDict:
    """Revoke an approved certification, triggering the enforcement cascade."""
    return validate_success(api.revoke_exemption_certification(
        exemption_id, {"revocation_reason": revocation_reason}, headers))


def create_approved_exemption(api: ApiClient, employer_id: str,
                              base: Optional[JsonDict] = None,
                              **overrides: Any) -> JsonDict:
    """File a certification and approve it, so the employer is exempt-certified."""
    exemption = file_exemption(api, employer_id, base, **overrides)
    return decide_exemption(api, exemption["id"], "APPROVE")


# ---------------------------------------------------------------------------
# Participants and enrollments
# ---------------------------------------------------------------------------
def create_participant(api: ApiClient, base: Optional[JsonDict] = None,
                       headers: Headers = ADMIN, **overrides: Any) -> JsonDict:
    """Register a saver. Defaults to Rosa Lim, born 1980."""
    payload = _merge(base or C.PARTICIPANT_ROSA, overrides)
    return get_success_data(api.create_participant(payload, headers))


def create_enrollment(api: ApiClient, employer_id: str, participant_id: str,
                      hire_date: str = "2026-01-05",
                      annual_compensation_cents: int = 9600000,
                      headers: Optional[Headers] = None) -> JsonDict:
    """Enrol one saver at one employer."""
    payload = {
        "participant_id": participant_id,
        "hire_date": hire_date,
        "annual_compensation_cents": annual_compensation_cents,
    }
    return get_success_data(api.create_enrollment(
        employer_id, payload, headers or make_employer_headers(employer_id)))


def opt_out(api: ApiClient, enrollment_id: str, participant_id: str,
            opt_out_reason_code: str = "NOT_INTERESTED",
            request_permissible_withdrawal: Optional[bool] = None,
            headers: Optional[Headers] = None) -> JsonDict:
    """Record the saver's opt-out on their own enrolment."""
    payload: JsonDict = {"opt_out_reason_code": opt_out_reason_code}
    if request_permissible_withdrawal is not None:
        payload["request_permissible_withdrawal"] = request_permissible_withdrawal
    return validate_success(api.opt_out_enrollment(
        enrollment_id, payload, headers or make_participant_headers(participant_id)))


def reenroll(api: ApiClient, enrollment_id: str, participant_id: str,
             reenroll_note: Optional[str] = None,
             headers: Optional[Headers] = None) -> JsonDict:
    """Bring an opted-out enrolment back to active."""
    payload: JsonDict = {}
    if reenroll_note is not None:
        payload["reenroll_note"] = reenroll_note
    return validate_success(api.reenroll(
        enrollment_id, headers or make_participant_headers(participant_id), payload))


def elect_rate(api: ApiClient, enrollment_id: str, participant_id: str,
               contribution_rate_bp: int,
               escalation_opt_out: Optional[bool] = None,
               headers: Optional[Headers] = None) -> JsonDict:
    """Record the saver's own deferral-rate election."""
    payload: JsonDict = {"contribution_rate_bp": contribution_rate_bp}
    if escalation_opt_out is not None:
        payload["escalation_opt_out"] = escalation_opt_out
    return validate_success(api.elect_contribution_rate(
        enrollment_id, payload, headers or make_participant_headers(participant_id)))


def end_employment(api: ApiClient, enrollment_id: str, employer_id: str,
                   employment_end_date: str,
                   headers: Optional[Headers] = None) -> JsonDict:
    """Report a separation date, which terminates the enrolment."""
    return validate_success(api.update_employment(
        enrollment_id, {"employment_end_date": employment_end_date},
        headers or make_employer_headers(employer_id)))


# ---------------------------------------------------------------------------
# Scheduled batches
# ---------------------------------------------------------------------------
def run_auto_enrollment(api: ApiClient, as_of_date: Optional[str] = None,
                        headers: Headers = ADMIN) -> JsonDict:
    """Run the auto-enrolment batch, optionally overriding the effective date."""
    payload: JsonDict = {}
    if as_of_date is not None:
        payload["as_of_date"] = as_of_date
    return validate_success(api.run_auto_enrollment(headers, payload))


def run_annual_escalation(api: ApiClient, effective_date: Optional[str] = None,
                          headers: Headers = ADMIN) -> JsonDict:
    """Run the annual escalation batch."""
    payload: JsonDict = {}
    if effective_date is not None:
        payload["effective_date"] = effective_date
    return validate_success(api.run_annual_escalation(headers, payload))


def run_compliance_sweep(api: ApiClient, as_of_date: Optional[str] = None,
                         headers: Headers = OFFICER) -> JsonDict:
    """Run the compliance sweep."""
    payload: JsonDict = {}
    if as_of_date is not None:
        payload["as_of_date"] = as_of_date
    return validate_success(api.run_compliance_sweep(headers, payload))


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------
def account_for_participant(api: ApiClient, participant_id: str,
                            headers: Headers = ADMIN) -> JsonDict:
    """Return the single account the batch opened for this saver."""
    rows = validate_success(
        api.list_participant_accounts(headers, {"participant_id": participant_id}))
    assert len(rows) == 1, (
        f"Expected exactly one account for participant {participant_id}, "
        f"found {len(rows)}"
    )
    return rows[0]


def elect_allocations(api: ApiClient, account_id: str, participant_id: str,
                      allocations: List[JsonDict], expected_account_version: int,
                      headers: Optional[Headers] = None) -> JsonDict:
    """Replace the account's fund allocation under concurrency control."""
    payload = {
        "allocations": allocations,
        "expected_account_version": expected_account_version,
    }
    return get_success_data(api.create_investment_election(
        account_id, payload, headers or make_participant_headers(participant_id)))


def post_earnings(api: ApiClient, account_id: str, earnings_cents: int,
                  posting_date: str, headers: Headers = RECORDKEEPER) -> JsonDict:
    """Credit investment earnings to an account."""
    return validate_success(api.post_earnings(
        account_id,
        {"earnings_cents": earnings_cents, "posting_date": posting_date},
        headers))


def request_closure(api: ApiClient, account_id: str, participant_id: str,
                    closure_reason: str = "PARTICIPANT_REQUEST",
                    residual_disposition: str = "CASH_DISTRIBUTION",
                    headers: Optional[Headers] = None) -> JsonDict:
    """Ask for the account to be closed."""
    payload = {
        "closure_reason": closure_reason,
        "residual_disposition": residual_disposition,
    }
    return validate_success(api.request_account_closure(
        account_id, payload, headers or make_participant_headers(participant_id)))


def complete_closure(api: ApiClient, account_id: str,
                     completion_note: Optional[str] = None,
                     headers: Headers = RECORDKEEPER) -> JsonDict:
    """Finish a pending closure."""
    payload: JsonDict = {}
    if completion_note is not None:
        payload["completion_note"] = completion_note
    return validate_success(api.complete_account_closure(account_id, headers, payload))


# ---------------------------------------------------------------------------
# Remittances
# ---------------------------------------------------------------------------
def create_remittance(api: ApiClient, employer_id: str, pay_period_start: str,
                      pay_period_end: str, pay_date: str,
                      total_deducted_cents: int,
                      headers: Optional[Headers] = None) -> JsonDict:
    """Open a draft payroll remittance batch."""
    payload = {
        "pay_period_start": pay_period_start,
        "pay_period_end": pay_period_end,
        "pay_date": pay_date,
        "total_deducted_cents": total_deducted_cents,
    }
    return get_success_data(api.create_payroll_remittance(
        employer_id, payload, headers or make_employer_headers(employer_id)))


def add_remittance_line(api: ApiClient, remittance_id: str, employer_id: str,
                        enrollment_id: str, gross_wages_cents: int,
                        deducted_cents: int,
                        headers: Optional[Headers] = None) -> JsonDict:
    """Add one per-saver line to a draft batch."""
    payload = {
        "enrollment_id": enrollment_id,
        "gross_wages_cents": gross_wages_cents,
        "deducted_cents": deducted_cents,
    }
    return get_success_data(api.create_remittance_line(
        remittance_id, payload, headers or make_employer_headers(employer_id)))


def submit_remittance(api: ApiClient, remittance_id: str, employer_id: str,
                      submission_note: Optional[str] = None,
                      headers: Optional[Headers] = None) -> JsonDict:
    """Submit a batch for reconciliation."""
    payload: JsonDict = {}
    if submission_note is not None:
        payload["submission_note"] = submission_note
    return validate_success(api.submit_remittance(
        remittance_id, headers or make_employer_headers(employer_id), payload))


def post_remittance(api: ApiClient, remittance_id: str, posting_reference: str,
                    headers: Headers = RECORDKEEPER) -> JsonDict:
    """Post a submitted batch, allocating each line to its account."""
    return validate_success(api.post_remittance(
        remittance_id, {"posting_reference": posting_reference}, headers))


def reject_remittance(api: ApiClient, remittance_id: str, rejection_reason: str,
                      headers: Headers = RECORDKEEPER) -> JsonDict:
    """Reject a submitted batch back to the employer."""
    return validate_success(api.reject_remittance(
        remittance_id, {"rejection_reason": rejection_reason}, headers))


def reverse_remittance(api: ApiClient, remittance_id: str, reversal_reason: str,
                       headers: Headers = RECORDKEEPER) -> JsonDict:
    """Reverse a posted batch, unwinding every allocation it made."""
    return validate_success(api.reverse_remittance(
        remittance_id, {"reversal_reason": reversal_reason}, headers))


def post_full_remittance(api: ApiClient, employer_id: str, enrollment_id: str,
                         pay_period_start: str, pay_period_end: str, pay_date: str,
                         gross_wages_cents: int, deducted_cents: int,
                         posting_reference: str = "PR-0001") -> JsonDict:
    """
    Drive one single-line batch all the way from draft to posted, returning the
    posted batch row.
    """
    remittance = create_remittance(api, employer_id, pay_period_start,
                                   pay_period_end, pay_date, deducted_cents)
    add_remittance_line(api, remittance["id"], employer_id, enrollment_id,
                        gross_wages_cents, deducted_cents)
    submit_remittance(api, remittance["id"], employer_id)
    return post_remittance(api, remittance["id"], posting_reference)


# ---------------------------------------------------------------------------
# Excess contribution cases
# ---------------------------------------------------------------------------
def excess_cases_for_account(api: ApiClient, account_id: str,
                             headers: Headers = ADMIN) -> list:
    """List the excess cases opened against one account."""
    return validate_success(api.list_account_excess_cases(account_id, headers))


def elect_correction_method(api: ApiClient, case_id: str, participant_id: str,
                            correction_method: str,
                            headers: Optional[Headers] = None) -> JsonDict:
    """Record the saver's chosen correction route."""
    return validate_success(api.elect_correction_method(
        case_id, {"correction_method": correction_method},
        headers or make_participant_headers(participant_id)))


def complete_excess_case(api: ApiClient, case_id: str, settlement_reference: str,
                         headers: Headers = RECORDKEEPER) -> JsonDict:
    """Settle an excess case, applying the net-income-attributable arithmetic."""
    return validate_success(api.complete_excess_case(
        case_id, {"settlement_reference": settlement_reference}, headers))


# ---------------------------------------------------------------------------
# Penalties and referrals
# ---------------------------------------------------------------------------
def assess_penalty(api: ApiClient, employer_id: str, violation_type: str,
                   notice_date: str, cure_days: Optional[int] = None,
                   headers: Headers = OFFICER) -> JsonDict:
    """Assess a statutory penalty against an employer."""
    payload: JsonDict = {
        "violation_type": violation_type,
        "notice_date": notice_date,
    }
    if cure_days is not None:
        payload["cure_days"] = cure_days
    return get_success_data(
        api.create_penalty_assessment(employer_id, payload, headers))


def dispose_penalty(api: ApiClient, penalty_id: str, disposition: str,
                    disposition_note: Optional[str] = None,
                    headers: Headers = OFFICER) -> JsonDict:
    """Affirm or abate an assessment. The disposing officer must not be the assessor."""
    payload: JsonDict = {"disposition": disposition}
    if disposition_note is not None:
        payload["disposition_note"] = disposition_note
    return validate_success(
        api.dispose_penalty_assessment(penalty_id, payload, headers))


def refer_penalty(api: ApiClient, penalty_id: str, agency: str,
                  referral_basis: str, headers: Headers = OFFICER) -> JsonDict:
    """Escalate an affirmed assessment to an outside authority."""
    return get_success_data(api.create_enforcement_referral(
        penalty_id, {"agency": agency, "referral_basis": referral_basis}, headers))


# ---------------------------------------------------------------------------
# Portability
# ---------------------------------------------------------------------------
def request_transfer(api: ApiClient, participant_id: str, source_account_id: str,
                     amount_cents: int,
                     transfer_kind: str = "INDIRECT_60_DAY",
                     destination_type: str = "EXTERNAL_IRA",
                     external_institution_name: Optional[str] =
                     "Northline Trust Company",
                     destination_account_id: Optional[str] = None,
                     headers: Optional[Headers] = None) -> JsonDict:
    """Request a portability movement out of one of the saver's accounts."""
    payload: JsonDict = {
        "participant_id": participant_id,
        "source_account_id": source_account_id,
        "destination_type": destination_type,
        "transfer_kind": transfer_kind,
        "amount_cents": amount_cents,
    }
    if destination_type == "EXTERNAL_IRA" and external_institution_name is not None:
        payload["external_institution_name"] = external_institution_name
    if destination_account_id is not None:
        payload["destination_account_id"] = destination_account_id
    return get_success_data(api.create_portability_transfer(
        payload, headers or make_participant_headers(participant_id)))


def settle_transfer(api: ApiClient, transfer_id: str, settled_on: str,
                    settlement_reference: str,
                    headers: Headers = RECORDKEEPER) -> JsonDict:
    """Settle a requested transfer at the receiving institution."""
    return validate_success(api.settle_portability_transfer(
        transfer_id,
        {"settled_on": settled_on, "settlement_reference": settlement_reference},
        headers))


def return_transfer(api: ApiClient, transfer_id: str, return_reason: str,
                    headers: Headers = RECORDKEEPER) -> JsonDict:
    """Return a requested transfer, restoring the account to its pre-request state."""
    return validate_success(api.return_portability_transfer(
        transfer_id, {"return_reason": return_reason}, headers))
