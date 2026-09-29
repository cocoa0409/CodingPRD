"""Request payload factories.

Every factory returns a valid, minimally-complete payload for one write
endpoint.  Keyword overrides are merged last, so a test can point a single
field at the value it cares about without restating the rest.  Passing
``None`` for an optional key removes it from the payload entirely, which is
how tests exercise declared field defaults.
"""

import itertools
from typing import Any, Dict, List, Optional

from .constants import COLD_START_UTC  # noqa: F401  (re-exported for convenience)

_counter = itertools.count(1)


def unique_suffix() -> str:
    """A short suffix that is unique within one test process."""
    return f"{next(_counter):04d}"


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    for key, value in overrides.items():
        if value is None and key in payload:
            payload.pop(key)
        else:
            payload[key] = value
    return payload


# --------------------------------------------------------------------------
# Employer
# --------------------------------------------------------------------------
def employer_payload(**overrides: Any) -> Dict[str, Any]:
    suffix = unique_suffix()
    return _merge(
        {
            "name": f"Northwind Manufacturing {suffix}",
            "industry_code": "MANUFACTURING",
        },
        overrides,
    )


def employer_patch_payload(**overrides: Any) -> Dict[str, Any]:
    return dict(overrides)


# --------------------------------------------------------------------------
# BenefitPlan
# --------------------------------------------------------------------------
def benefit_plan_payload(
    employer_id: str, expected_employer_version: int, **overrides: Any
) -> Dict[str, Any]:
    suffix = unique_suffix()
    return _merge(
        {
            "employer_id": employer_id,
            "expected_employer_version": expected_employer_version,
            "plan_code": f"PLAN-{suffix}",
            "annual_use_limit_days": 10,
            "copay_center_cents_per_day": 1500,
            "copay_in_home_cents_per_hour": 400,
            "eligible_dependent_types": ["CHILD"],
            "overage_rate_center_cents_per_day": 20000,
            "overage_rate_in_home_cents_per_hour": 5000,
            "no_show_charge_cents": 12000,
            "effective_from": "2026-01-01",
        },
        overrides,
    )


def benefit_plan_patch_payload(**overrides: Any) -> Dict[str, Any]:
    return dict(overrides)


# --------------------------------------------------------------------------
# Employee
# --------------------------------------------------------------------------
def employee_payload(
    employer_id: str, benefit_plan_id: str, user_id: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    suffix = unique_suffix()
    resolved_user_id = user_id or f"u_ee_{suffix}"
    return _merge(
        {
            "employer_id": employer_id,
            "benefit_plan_id": benefit_plan_id,
            "employee_external_id": f"EMP-{suffix}",
            "user_id": resolved_user_id,
            "email": f"{resolved_user_id}@northwind.example",
            "full_name": f"Dana Employee {suffix}",
        },
        overrides,
    )


def employee_patch_payload(**overrides: Any) -> Dict[str, Any]:
    return dict(overrides)


# --------------------------------------------------------------------------
# Dependent
# --------------------------------------------------------------------------
def dependent_payload(**overrides: Any) -> Dict[str, Any]:
    suffix = unique_suffix()
    return _merge(
        {
            "full_name": f"Robin Dependent {suffix}",
            "dependent_type": "CHILD",
            "date_of_birth": "2019-04-15",
            "relationship": "CHILD",
        },
        overrides,
    )


def dependent_patch_payload(**overrides: Any) -> Dict[str, Any]:
    return dict(overrides)


# --------------------------------------------------------------------------
# Provider
# --------------------------------------------------------------------------
def provider_payload(
    owner_user_id: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    suffix = unique_suffix()
    return _merge(
        {
            "provider_name": f"Bright Days Center {suffix}",
            "owner_user_id": owner_user_id or f"u_pm_{suffix}",
            "care_mode": "CENTER_BASED",
            "market_code": "MKT-SEA",
            "postal_code": "98101",
            "daily_capacity_slots": 4,
        },
        overrides,
    )


def provider_patch_payload(**overrides: Any) -> Dict[str, Any]:
    return dict(overrides)


# --------------------------------------------------------------------------
# Credential
# --------------------------------------------------------------------------
def credential_payload(credential_type: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "credential_type": credential_type,
            "issued_on": "2025-01-01",
            "expires_on": "2027-12-31",
            "verified_by": "u_na_1",
        },
        overrides,
    )


def revoke_credential_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"revoked_reason_code": "ISSUER_WITHDRAWN"}, overrides)


def credential_review_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"reason_code": "INITIAL_REVIEW"}, overrides)


def network_status_payload(target_status: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"target_status": target_status, "reason_code": "MANUAL_ACTION"}, overrides)


# --------------------------------------------------------------------------
# CapacityBlock
# --------------------------------------------------------------------------
def capacity_block_payload(
    start_time_utc: str, end_time_utc: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "start_time_utc": start_time_utc,
            "end_time_utc": end_time_utc,
            "total_slots": 4,
        },
        overrides,
    )


# --------------------------------------------------------------------------
# Reservation
# --------------------------------------------------------------------------
def reservation_payload(
    employee_id: str,
    dependent_ids: List[str],
    care_start_utc: str,
    care_end_utc: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "employee_id": employee_id,
            "dependent_ids": list(dependent_ids),
            "requested_care_mode": "CENTER_BASED",
            "market_code": "MKT-SEA",
            "care_start_utc": care_start_utc,
            "care_end_utc": care_end_utc,
        },
        overrides,
    )


def confirm_payload(
    capacity_block_id: str, expected_capacity_block_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "capacity_block_id": capacity_block_id,
            "expected_capacity_block_version": expected_capacity_block_version,
        },
        overrides,
    )


def reject_offer_payload(match_offer_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"match_offer_id": match_offer_id, "reason_code": "FAMILY_DECLINED_LOCATION"}, overrides
    )


def cancel_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"cancel_reason_code": "NO_LONGER_NEEDED"}, overrides)


def complete_payload(actual_start_utc: str, actual_end_utc: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"actual_start_utc": actual_start_utc, "actual_end_utc": actual_end_utc}, overrides
    )


def no_show_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"reason_code": "FAMILY_NEVER_ARRIVED"}, overrides)


# --------------------------------------------------------------------------
# EmployerInvoice
# --------------------------------------------------------------------------
def invoice_payload(period_start: str, period_end: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"period_start": period_start, "period_end": period_end}, overrides)


def payment_payload(paid_amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    return _merge({"paid_amount_cents": paid_amount_cents}, overrides)


def void_invoice_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"void_reason_code": "CREATED_IN_ERROR"}, overrides)


# --------------------------------------------------------------------------
# IncidentReport
# --------------------------------------------------------------------------
def incident_report_payload(
    provider_id: str, severity: str = "MODERATE", **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "provider_id": provider_id,
            "severity": severity,
            "category": "SUPERVISION",
            "narrative": "Staffing ratio appeared to slip during the afternoon nap window.",
        },
        overrides,
    )


def substantiate_payload(qa_action: str = "NONE", **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"qa_action": qa_action, "resolution_reason_code": "CONFIRMED_FINDING"}, overrides
    )


def dismiss_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"resolution_reason_code": "UNSUBSTANTIATED_AFTER_INTERVIEW"}, overrides)


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
def clock_payload(current_utc: str) -> Dict[str, Any]:
    return {"current_utc": current_utc}
