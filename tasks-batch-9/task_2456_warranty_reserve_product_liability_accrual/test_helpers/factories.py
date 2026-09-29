"""Payload builders for every creatable resource.

Each builder returns a valid minimal payload that satisfies the PRD's field
constraints, with unique code fields so uniqueness scopes are never tripped
accidentally. Callers override any field by keyword.
"""

import itertools
from typing import Any, Dict, Optional

from .constants import DEFAULT_CLOCK_ISO  # noqa: F401  (re-exported for convenience)

_counter = itertools.count(1)


def unique_suffix() -> str:
    """A short monotonically increasing suffix for code fields."""
    return f"{next(_counter):05d}"


# ---------------------------------------------------------------------------
# Accrual periods
# ---------------------------------------------------------------------------
def period_payload(
    period_code: str = "2026-Q3",
    period_start_date: str = "2026-07-01",
    period_end_date: str = "2026-09-30",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "period_code": period_code,
        "period_start_date": period_start_date,
        "period_end_date": period_end_date,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Product families
# ---------------------------------------------------------------------------
def family_payload(
    family_code: Optional[str] = None,
    name: str = "Cordless Drill Platform",
    launch_date: str = "2024-01-01",
    base_warranty_months: int = 24,
    standard_cost_per_claim_cents: int = 20000,
    reserve_cap_cents: int = 100000000,
    engineering_estimate_rate_ppm: Optional[int] = None,
    analog_family_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "family_code": family_code or f"FAM-{unique_suffix()}",
        "name": name,
        "launch_date": launch_date,
        "base_warranty_months": base_warranty_months,
        "standard_cost_per_claim_cents": standard_cost_per_claim_cents,
        "reserve_cap_cents": reserve_cap_cents,
    }
    if engineering_estimate_rate_ppm is not None:
        payload["engineering_estimate_rate_ppm"] = engineering_estimate_rate_ppm
    if analog_family_id is not None:
        payload["analog_family_id"] = analog_family_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Product vintages
# ---------------------------------------------------------------------------
def vintage_payload(
    family_id: str,
    vintage_code: Optional[str] = None,
    units_shipped: int = 10000,
    ship_period_code: str = "2026-Q3",
    warranty_expiry_date: str = "2027-12-31",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "family_id": family_id,
        "vintage_code": vintage_code or f"MY-{unique_suffix()}",
        "units_shipped": units_shipped,
        "ship_period_code": ship_period_code,
        "warranty_expiry_date": warranty_expiry_date,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------
def failure_mode_payload(
    family_id: str,
    mode_code: Optional[str] = None,
    description: str = "Motor brush wear",
    severity: str = "FUNCTIONAL",
    cost_per_claim_cents: int = 15000,
    supplier_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "family_id": family_id,
        "mode_code": mode_code or f"FM-{unique_suffix()}",
        "description": description,
        "severity": severity,
        "cost_per_claim_cents": cost_per_claim_cents,
    }
    if supplier_id is not None:
        payload["supplier_id"] = supplier_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Claim observations
# ---------------------------------------------------------------------------
def claim_observation_payload(
    vintage_id: str,
    failure_mode_id: str,
    observation_period_code: str = "2026-Q3",
    months_in_service_from: int = 0,
    months_in_service_to: int = 12,
    claim_count: int = 100,
    paid_cost_cents: int = 1000000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "vintage_id": vintage_id,
        "failure_mode_id": failure_mode_id,
        "observation_period_code": observation_period_code,
        "months_in_service_from": months_in_service_from,
        "months_in_service_to": months_in_service_to,
        "claim_count": claim_count,
        "paid_cost_cents": paid_cost_cents,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Warranty accruals
# ---------------------------------------------------------------------------
def accrual_payload(
    period_id: str,
    vintage_id: str,
    expected_period_version: int,
    method: str = "HISTORICAL_RATE",
    elapsed_exposure_bps: int = 5000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "period_id": period_id,
        "vintage_id": vintage_id,
        "method": method,
        "elapsed_exposure_bps": elapsed_exposure_bps,
        "expected_period_version": expected_period_version,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Adequacy reviews
# ---------------------------------------------------------------------------
def adequacy_review_payload(period_id: str, family_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {"period_id": period_id, "family_id": family_id}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Field actions
# ---------------------------------------------------------------------------
def field_action_payload(
    family_id: str,
    action_code: Optional[str] = None,
    action_type: str = "SERVICE_CAMPAIGN",
    affected_build_start_date: str = "2025-01-01",
    affected_build_end_date: str = "2025-03-31",
    affected_unit_count: int = 12000,
    regulatory_notice_filed: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "family_id": family_id,
        "action_code": action_code or f"FA-{unique_suffix()}",
        "action_type": action_type,
        "affected_build_start_date": affected_build_start_date,
        "affected_build_end_date": affected_build_end_date,
        "affected_unit_count": affected_unit_count,
    }
    if regulatory_notice_filed is not None:
        payload["regulatory_notice_filed"] = regulatory_notice_filed
    payload.update(overrides)
    return payload


def remedy_option_payload(
    option_code: Optional[str] = None,
    remedy_class: str = "PERMANENT_REPAIR",
    parts_cost_cents: int = 4200,
    labor_hours_centi: int = 150,
    admin_cost_cents: int = 800,
    expected_take_rate_bps: int = 6500,
    is_engineering_approved: Optional[bool] = True,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "option_code": option_code or f"RO-{unique_suffix()}",
        "remedy_class": remedy_class,
        "parts_cost_cents": parts_cost_cents,
        "labor_hours_centi": labor_hours_centi,
        "admin_cost_cents": admin_cost_cents,
        "expected_take_rate_bps": expected_take_rate_bps,
    }
    if is_engineering_approved is not None:
        payload["is_engineering_approved"] = is_engineering_approved
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Service contracts
# ---------------------------------------------------------------------------
def service_contract_payload(
    family_id: str,
    contract_number: Optional[str] = None,
    sold_date: str = "2026-02-01",
    term_months: int = 24,
    total_contract_price_cents: int = 480000,
    recognition_method: str = "STRAIGHT_LINE",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "family_id": family_id,
        "contract_number": contract_number or f"ESC-{unique_suffix()}",
        "sold_date": sold_date,
        "term_months": term_months,
        "total_contract_price_cents": total_contract_price_cents,
        "recognition_method": recognition_method,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Suppliers and recoveries
# ---------------------------------------------------------------------------
def supplier_payload(
    supplier_code: Optional[str] = None,
    name: str = "Precision Components GmbH",
    credit_rating: str = "AAA",
    annual_purchase_volume_cents: int = 500000000,
    contractual_recovery_cap_bps: int = 10000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "supplier_code": supplier_code or f"SUP-{unique_suffix()}",
        "name": name,
        "credit_rating": credit_rating,
        "annual_purchase_volume_cents": annual_purchase_volume_cents,
        "contractual_recovery_cap_bps": contractual_recovery_cap_bps,
    }
    payload.update(overrides)
    return payload


def supplier_recovery_payload(
    supplier_id: str,
    failure_mode_id: str,
    asserted_amount_cents: int = 4000000,
    field_action_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "supplier_id": supplier_id,
        "failure_mode_id": failure_mode_id,
        "asserted_amount_cents": asserted_amount_cents,
    }
    if field_action_id is not None:
        payload["field_action_id"] = field_action_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Liability reserves
# ---------------------------------------------------------------------------
def liability_reserve_payload(
    period_id: str,
    family_id: str,
    reported_claim_count: int = 40,
    asserted_case_reserve_cents: int = 4000000,
    reporting_lag_months: int = 3,
    severity_trend_bps: int = 500,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "period_id": period_id,
        "family_id": family_id,
        "reported_claim_count": reported_claim_count,
        "asserted_case_reserve_cents": asserted_case_reserve_cents,
        "reporting_lag_months": reporting_lag_months,
        "severity_trend_bps": severity_trend_bps,
    }
    payload.update(overrides)
    return payload
