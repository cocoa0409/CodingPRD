"""
Request-payload builders.

Each builder returns a valid, minimal body for one endpoint and accepts
`**overrides` so a test can perturb exactly the field under examination. No
builder performs HTTP work — composition of multi-step state lives in
`fixtures.py`.
"""

from typing import Any, Dict, Optional

from .constants import (
    CERT_DEADLINE_2026,
    CERT_WINDOW_2026_OPEN,
    DEFAULT_CLOCK_UTC,
    FULLY_VESTED_SERVICE_MONTHS,
    NHCE_PRIOR_COMPENSATION_CENTS,
    PLAN_YEAR_2026,
    PLAN_YEAR_2026_END,
    PLAN_YEAR_2026_START,
    STANDARD_CERTIFIED_PAYMENT_CENTS,
    STANDARD_PERIOD_COMPENSATION_CENTS,
    STANDARD_PERIOD_DEFERRAL_CENTS,
    payroll_period_window,
)

Payload = Dict[str, Any]


def _merge(base: Payload, overrides: Payload) -> Payload:
    """Apply overrides; the `OMIT` sentinel removes a key from the body entirely."""
    body = dict(base)
    body.update(overrides)
    return {key: value for key, value in body.items() if not isinstance(value, _Omit)}


class _Omit:
    """Sentinel: drop a key from a payload entirely (for missing-field tests)."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "OMIT"


_OMIT = _Omit()
OMIT = _OMIT


# ---------------------------------------------------------------------------
# Plan years and amendments
# ---------------------------------------------------------------------------


def plan_year_payload(**overrides: Any) -> Payload:
    """Body for creating a plan year; declared defaults are left unspecified."""
    return _merge(
        {
            "year": PLAN_YEAR_2026,
            "period_start": PLAN_YEAR_2026_START,
            "period_end": PLAN_YEAR_2026_END,
            "certification_window_open": CERT_WINDOW_2026_OPEN,
            "certification_deadline": CERT_DEADLINE_2026,
        },
        overrides,
    )


def plan_year_status_payload(to_status: str, **overrides: Any) -> Payload:
    """Body for a plan-year status transition."""
    return _merge({"to_status": to_status}, overrides)


def plan_amendment_payload(plan_year_id: str, **overrides: Any) -> Payload:
    """Body for creating a plan amendment."""
    return _merge(
        {
            "plan_year_id": plan_year_id,
            "document_ref": "AMD-2026-001",
            "effective_date": PLAN_YEAR_2026_START,
        },
        overrides,
    )


def amendment_status_payload(to_status: str, **overrides: Any) -> Payload:
    """Body for an amendment status transition; NOTICE_SENT needs a channel."""
    base: Payload = {"to_status": to_status}
    if to_status == "NOTICE_SENT":
        base["notice_channel"] = "EMAIL"
    if to_status == "RESCINDED":
        base["rescinded_reason"] = "superseded by later amendment"
    return _merge(base, overrides)


# ---------------------------------------------------------------------------
# Employees, employment events, leave
# ---------------------------------------------------------------------------


def employee_payload(**overrides: Any) -> Payload:
    """Body for creating an employee; defaults describe a fully vested NHCE."""
    return _merge(
        {
            "external_id": "E-1001",
            "hire_date": "2019-01-01T00:00:00Z",
            "prior_year_compensation_cents": NHCE_PRIOR_COMPENSATION_CENTS,
            "vesting_service_months": FULLY_VESTED_SERVICE_MONTHS,
        },
        overrides,
    )


def employment_event_payload(event_type: str, effective_date: str, **overrides: Any) -> Payload:
    """Body for a TERMINATE or REHIRE employment event."""
    return _merge({"event_type": event_type, "effective_date": effective_date}, overrides)


def leave_event_payload(
    employee_id: str, start_date: str, end_date: str, **overrides: Any
) -> Payload:
    """Body for filing a leave interval; both endpoints are inclusive."""
    return _merge(
        {
            "employee_id": employee_id,
            "leave_type": "UNPAID",
            "start_date": start_date,
            "end_date": end_date,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Payroll periods and contribution records
# ---------------------------------------------------------------------------


def payroll_period_payload(plan_year_id: str, period_number: int = 3, **overrides: Any) -> Payload:
    """Body for creating one monthly payroll period of a plan year."""
    window = payroll_period_window(period_number)
    return _merge(
        {
            "plan_year_id": plan_year_id,
            "period_number": period_number,
            "start_date": window["start_date"],
            "end_date": window["end_date"],
            "pay_date": window["pay_date"],
        },
        overrides,
    )


def payroll_period_status_payload(to_status: str, **overrides: Any) -> Payload:
    """Body for a payroll-period status transition."""
    return _merge({"to_status": to_status}, overrides)


def contribution_record_payload(
    employee_id: str,
    payroll_period_id: str,
    eligible_compensation_cents: int = STANDARD_PERIOD_COMPENSATION_CENTS,
    elective_deferral_cents: int = STANDARD_PERIOD_DEFERRAL_CENTS,
    **overrides: Any,
) -> Payload:
    """Body for posting one payroll line."""
    return _merge(
        {
            "employee_id": employee_id,
            "payroll_period_id": payroll_period_id,
            "eligible_compensation_cents": eligible_compensation_cents,
            "elective_deferral_cents": elective_deferral_cents,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Loan accounts
# ---------------------------------------------------------------------------


def loan_account_payload(employee_id: str, **overrides: Any) -> Payload:
    """Body for registering a student loan account."""
    return _merge(
        {
            "employee_id": employee_id,
            "servicer_name": "Nelnet",
            "account_last4": "4321",
            "original_principal_cents": 2_500_000,
        },
        overrides,
    )


def loan_verification_payload(to_status: str = "VERIFIED", **overrides: Any) -> Payload:
    """Body for moving a loan account out of UNVERIFIED."""
    base: Payload = {"to_status": to_status}
    if to_status == "VERIFIED":
        base["evidence_ref"] = "STMT-2026-03"
    return _merge(base, overrides)


# ---------------------------------------------------------------------------
# Loan certifications, lines and decisions
# ---------------------------------------------------------------------------


def loan_certification_payload(
    employee_id: str,
    plan_year_id: str,
    expected_employee_version: int,
    **overrides: Any,
) -> Payload:
    """Body for opening an annual certification claim."""
    return _merge(
        {
            "employee_id": employee_id,
            "plan_year_id": plan_year_id,
            "certification_method": "SERVICER_STATEMENT",
            "expected_employee_version": expected_employee_version,
        },
        overrides,
    )


def certification_line_payload(
    loan_account_id: str,
    payment_date: str = "2026-03-15T00:00:00Z",
    amount_cents: int = STANDARD_CERTIFIED_PAYMENT_CENTS,
    covered_period_start: str = "2026-03-01T00:00:00Z",
    covered_period_end: str = "2026-04-01T00:00:00Z",
    **overrides: Any,
) -> Payload:
    """Body for one certified payment line; the covered window is half-open."""
    return _merge(
        {
            "loan_account_id": loan_account_id,
            "payment_date": payment_date,
            "amount_cents": amount_cents,
            "covered_period_start": covered_period_start,
            "covered_period_end": covered_period_end,
        },
        overrides,
    )


def decision_payload(decision: str, reason: Optional[str] = None, **overrides: Any) -> Payload:
    """Body for the accept/return decision on a submitted claim."""
    base: Payload = {"decision": decision}
    if decision == "RETURN":
        base["reason"] = reason or "servicer statement illegible"
    elif reason is not None:
        base["reason"] = reason
    return _merge(base, overrides)


def audit_hold_payload(reason: str = "certification documentation sampling", **overrides: Any) -> Payload:
    """Body for placing an accepted claim on audit hold."""
    return _merge({"reason": reason}, overrides)


def audit_release_payload(
    resolution: str, note: Optional[str] = None, **overrides: Any
) -> Payload:
    """Body for releasing an audit hold, either clearing or voiding the claim."""
    base: Payload = {"resolution": resolution}
    if note is not None:
        base["note"] = note
    elif resolution == "VOID":
        base["note"] = "no supporting statement"
    return _merge(base, overrides)


# ---------------------------------------------------------------------------
# Funding batches
# ---------------------------------------------------------------------------


def funding_batch_payload(plan_year_id: str, payroll_period_id: str, **overrides: Any) -> Payload:
    """Body for opening a pending funding batch for one payroll period."""
    return _merge(
        {"plan_year_id": plan_year_id, "payroll_period_id": payroll_period_id}, overrides
    )


def settlement_payload(
    outcome: str = "SETTLED", rejection_code: Optional[str] = None, **overrides: Any
) -> Payload:
    """Body for the recordkeeper's settlement answer on a transmitted batch."""
    base: Payload = {"outcome": outcome}
    if outcome == "REJECTED":
        base["rejection_code"] = rejection_code or "RK-101"
    elif rejection_code is not None:
        base["rejection_code"] = rejection_code
    return _merge(base, overrides)


# ---------------------------------------------------------------------------
# Corrections
# ---------------------------------------------------------------------------


def allocation_correction_payload(
    expected_plan_year_version: int,
    reason_code: str = "ERRONEOUS_MATCH",
    note: Optional[str] = "reversing an erroneous match allocation",
    **overrides: Any,
) -> Payload:
    """Body for reversing one funded match allocation."""
    base: Payload = {
        "reason_code": reason_code,
        "expected_plan_year_version": expected_plan_year_version,
    }
    if note is not None:
        base["note"] = note
    return _merge(base, overrides)


# ---------------------------------------------------------------------------
# Nondiscrimination testing
# ---------------------------------------------------------------------------


def nondiscrimination_test_payload(
    plan_year_id: str,
    test_method: str = "CURRENT_YEAR",
    include_qslp_match: bool = True,
    **overrides: Any,
) -> Payload:
    """Body for opening an ACP test over a plan year."""
    return _merge(
        {
            "plan_year_id": plan_year_id,
            "test_method": test_method,
            "include_qslp_match": include_qslp_match,
        },
        overrides,
    )


def test_correction_payload(
    correction_method: str = "CORRECTIVE_FORFEITURE", **overrides: Any
) -> Payload:
    """Body for correcting a failed ACP test."""
    return _merge({"correction_method": correction_method}, overrides)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


def clock_payload(to_iso8601: str = DEFAULT_CLOCK_UTC, **overrides: Any) -> Payload:
    """Body for moving the logical clock to a chosen instant."""
    return _merge({"to_iso8601": to_iso8601}, overrides)
