"""Request payload builders.

Money fields are integer counts of cents and rates are integer counts of basis
points, so every such value is emitted as a JSON number. Each builder accepts
``**overrides`` so a test can vary exactly the field under examination and drops
keys whose value is the sentinel ``OMIT`` so optional-field-omitted cases can be
expressed without hand-building dictionaries.
"""

from typing import Any, Dict

OMIT = object()


def _payload(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    merged.update(overrides)
    return {k: v for k, v in merged.items() if v is not OMIT}


# ---------------------------------------------------------------------------
# Employer
# ---------------------------------------------------------------------------
def employer_payload(**overrides: Any) -> Dict[str, Any]:
    return _payload(
        {
            "legal_name": "Acme Manufacturing",
            "fein": "12-3456789",
            "deposit_schedule": "SEMIWEEKLY",
            "authorization_limit_cents": 5000000,
        },
        overrides,
    )


def employer_patch_payload(**overrides: Any) -> Dict[str, Any]:
    return _payload({}, overrides)


# ---------------------------------------------------------------------------
# TaxAgency
# ---------------------------------------------------------------------------
def federal_agency_payload(**overrides: Any) -> Dict[str, Any]:
    """Federal agency with the STATUTORY_DAILY interest method."""
    return _payload(
        {
            "agency_code": "FED-941",
            "level": "FEDERAL",
            "jurisdiction_code": "US",
            "interest_rate_bps_annual": 800,
            "interest_method": "STATUTORY_DAILY",
            "penalty_multiplier_bps": 10000,
            "min_days_between_amendments": 30,
            "amendment_window_days": 1095,
            "requires_registration": False,
        },
        overrides,
    )


def state_agency_payload(**overrides: Any) -> Dict[str, Any]:
    """State agency with the DEPOSIT_WEIGHTED interest method."""
    return _payload(
        {
            "agency_code": "NY-45",
            "level": "STATE",
            "jurisdiction_code": "NY",
            "interest_rate_bps_annual": 1200,
            "interest_method": "DEPOSIT_WEIGHTED",
            "penalty_multiplier_bps": 7500,
            "min_days_between_amendments": 45,
            "amendment_window_days": 1095,
            "requires_registration": True,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# AgencyAccount
# ---------------------------------------------------------------------------
def agency_account_payload(employer_id: str, agency_id: str, **overrides: Any) -> Dict[str, Any]:
    return _payload(
        {
            "employer_id": employer_id,
            "agency_id": agency_id,
            "effective_from_tax_year": 2025,
            "effective_from_quarter": 1,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Employee
# ---------------------------------------------------------------------------
def employee_payload(employer_id: str, **overrides: Any) -> Dict[str, Any]:
    return _payload(
        {
            "employer_id": employer_id,
            "full_name": "Dana Reed",
            "national_id_last4": "4821",
            "mailing_state_code": "NY",
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# PayrollRegisterLine
# ---------------------------------------------------------------------------
def register_line_payload(
    employer_id: str, employee_id: str, agency_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _payload(
        {
            "employer_id": employer_id,
            "employee_id": employee_id,
            "agency_id": agency_id,
            "tax_year": 2025,
            "quarter": 1,
            "taxable_wage_cents": 3000000,
            "withheld_cents": 450000,
            "work_jurisdiction_code": "US",
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# DepositRecord
# ---------------------------------------------------------------------------
def deposit_record_payload(employer_id: str, agency_id: str, **overrides: Any) -> Dict[str, Any]:
    return _payload(
        {
            "employer_id": employer_id,
            "agency_id": agency_id,
            "tax_year": 2025,
            "quarter": 1,
            "deposit_due_date": "2025-02-19",
            "deposit_date": "2025-02-19",
            "amount_cents": 500000,
            "obligation_amount_cents": 750000,
            "clearing_status": "CLEARED",
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# FiledReturn
# ---------------------------------------------------------------------------
def filed_return_payload(employer_id: str, agency_id: str, **overrides: Any) -> Dict[str, Any]:
    return _payload(
        {
            "employer_id": employer_id,
            "agency_id": agency_id,
            "tax_year": 2025,
            "quarter": 1,
            "form_code": "941X",
            "filed_at": "2025-04-30T00:00:00Z",
            "reported_taxable_wage_cents": 4750000,
            "reported_withheld_cents": 500000,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# CorrectionCase
# ---------------------------------------------------------------------------
def correction_case_payload(employer_id: str, agency_id: str, **overrides: Any) -> Dict[str, Any]:
    return _payload(
        {
            "employer_id": employer_id,
            "agency_id": agency_id,
            "tax_year": 2025,
            "quarter": 1,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Discrepancy triage
# ---------------------------------------------------------------------------
def categorize_payload(category: str, root_cause_code: str, **overrides: Any) -> Dict[str, Any]:
    return _payload({"category": category, "root_cause_code": root_cause_code}, overrides)


def dismiss_payload(**overrides: Any) -> Dict[str, Any]:
    return _payload({"dismissal_reason": "Immaterial rounding difference"}, overrides)


# ---------------------------------------------------------------------------
# AmendedReturn
# ---------------------------------------------------------------------------
def amended_return_payload(
    correction_case_id: str, expected_correction_case_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _payload(
        {
            "correction_case_id": correction_case_id,
            "form_code": "941X",
            "accrual_through_date": "2026-04-30",
            "expected_correction_case_version": expected_correction_case_version,
        },
        overrides,
    )


def prepare_payload(**overrides: Any) -> Dict[str, Any]:
    return _payload({}, overrides)


def agency_outcome_payload(outcome: str, **overrides: Any) -> Dict[str, Any]:
    return _payload({"outcome": outcome}, overrides)


def void_payload(**overrides: Any) -> Dict[str, Any]:
    return _payload({"void_reason": "Superseded by a corrected recomputation"}, overrides)


# ---------------------------------------------------------------------------
# CorrectedWageStatement
# ---------------------------------------------------------------------------
def statement_payload(
    correction_case_id: str, employee_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _payload(
        {
            "correction_case_id": correction_case_id,
            "employee_id": employee_id,
            "tax_year": 2025,
            "delivery_channel": "MAIL",
        },
        overrides,
    )


def issue_payload(**overrides: Any) -> Dict[str, Any]:
    """Issuance takes no request body."""
    return _payload({}, overrides)


def undeliverable_payload(**overrides: Any) -> Dict[str, Any]:
    return _payload({"undeliverable_reason": "Returned by carrier, addressee unknown"}, overrides)


def reissue_payload(expected_statement_version: int, **overrides: Any) -> Dict[str, Any]:
    return _payload({"expected_statement_version": expected_statement_version}, overrides)


# ---------------------------------------------------------------------------
# WageRepayment
# ---------------------------------------------------------------------------
def wage_repayment_payload(
    correction_case_id: str, employee_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _payload(
        {
            "correction_case_id": correction_case_id,
            "employee_id": employee_id,
            "overpaid_gross_cents": 400000,
            "overpaid_income_tax_withheld_cents": 60000,
            "overpaid_fica_withheld_cents": 30600,
            "overpayment_tax_year": 2025,
            "recovery_tax_year": 2025,
        },
        overrides,
    )


def agree_payload(installment_count: int = 4, **overrides: Any) -> Dict[str, Any]:
    return _payload({"installment_count": installment_count}, overrides)


def renegotiate_payload(**overrides: Any) -> Dict[str, Any]:
    return _payload({}, overrides)


def collect_payload(collected_cents: int, **overrides: Any) -> Dict[str, Any]:
    return _payload({"collected_cents": collected_cents}, overrides)


def write_off_payload(**overrides: Any) -> Dict[str, Any]:
    return _payload({"write_off_reason": "Balance uncollectible after separation"}, overrides)


# ---------------------------------------------------------------------------
# AgencyNotice
# ---------------------------------------------------------------------------
def agency_notice_payload(employer_id: str, agency_id: str, **overrides: Any) -> Dict[str, Any]:
    return _payload(
        {
            "employer_id": employer_id,
            "agency_id": agency_id,
            "tax_year": 2025,
            "quarter": 1,
            "notice_number": "CP2100-0001",
            "assessed_tax_cents": 1000000,
            "assessed_penalty_cents": 200000,
            "assessed_interest_cents": 50000,
            "response_due_date": "2026-06-30",
        },
        overrides,
    )


def draft_response_payload(**overrides: Any) -> Dict[str, Any]:
    return _payload(
        {"response_narrative": "Corrected register and amended return attached."}, overrides
    )


def request_info_payload(**overrides: Any) -> Dict[str, Any]:
    return _payload({"info_request_note": "Provide the reconciliation workpapers."}, overrides)


def notice_outcome_payload(outcome: str, **overrides: Any) -> Dict[str, Any]:
    return _payload({"outcome": outcome}, overrides)


# ---------------------------------------------------------------------------
# ControlRemediation
# ---------------------------------------------------------------------------
def control_remediation_payload(correction_case_id: str, **overrides: Any) -> Dict[str, Any]:
    return _payload(
        {
            "correction_case_id": correction_case_id,
            "root_cause_code": "RATE_TABLE_STALE",
            "control_gap_class": "PROCESS_CONTROL",
            "owner_user_id": "u_owner_cass",
            "target_date": "2026-07-31",
        },
        overrides,
    )


def assign_payload(owner_user_id: str, **overrides: Any) -> Dict[str, Any]:
    return _payload({"owner_user_id": owner_user_id}, overrides)


def submit_verification_payload(**overrides: Any) -> Dict[str, Any]:
    return _payload({"evidence_reference": "EV-2026-0417"}, overrides)


def verify_payload(passed: bool, **overrides: Any) -> Dict[str, Any]:
    return _payload({"passed": passed}, overrides)


# ---------------------------------------------------------------------------
# Case closure
# ---------------------------------------------------------------------------
def close_case_payload(**overrides: Any) -> Dict[str, Any]:
    return _payload({"closure_note": "All dimensions complete."}, overrides)
