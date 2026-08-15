"""Payload factories — one per creatable resource, input fields only.

Only fields the PRD names as caller-supplied inputs appear here; system and
computed fields are never sent.
"""
from typing import Any, Dict, List, Optional


def create_jurisdiction_payload(
    code: str = "FL-DADE",
    name: str = "Miami-Dade",
    state_code: str = "FL",
    rush_daily_capacity: Optional[int] = None,
    **overrides,
) -> dict:
    payload: Dict[str, Any] = {"code": code, "name": name, "state_code": state_code}
    if rush_daily_capacity is not None:
        payload["rush_daily_capacity"] = rush_daily_capacity
    payload.update(overrides)
    return payload


def create_statute_payload(
    jurisdiction_id: str,
    effective_from: str = "2026-01-01",
    effective_to: Optional[str] = None,
    estoppel_response_days: int = 10,
    estoppel_fee_cap_cents: int = 12000,
    estoppel_validity_days: int = 30,
    **overrides,
) -> dict:
    payload: Dict[str, Any] = {
        "jurisdiction_id": jurisdiction_id,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "estoppel_response_days": estoppel_response_days,
        "estoppel_fee_cap_cents": estoppel_fee_cap_cents,
        "estoppel_validity_days": estoppel_validity_days,
    }
    payload.update(overrides)
    return payload


def create_department_payload(
    jurisdiction_id: str,
    dept_type: str = "UTILITY",
    name: str = "Water & Sewer",
    research_fee_cents: int = 5000,
    rush_surcharge_cents: Optional[int] = None,
    supports_rush: Optional[bool] = None,
    **overrides,
) -> dict:
    payload: Dict[str, Any] = {
        "jurisdiction_id": jurisdiction_id,
        "dept_type": dept_type,
        "name": name,
        "research_fee_cents": research_fee_cents,
    }
    if rush_surcharge_cents is not None:
        payload["rush_surcharge_cents"] = rush_surcharge_cents
    if supports_rush is not None:
        payload["supports_rush"] = supports_rush
    payload.update(overrides)
    return payload


def create_association_payload(
    jurisdiction_id: str,
    name: str = "Sunset HOA",
    management_company: str = "Sunset Mgmt",
    estoppel_fee_cents: int = 10000,
    estoppel_validity_days: int = 30,
    **overrides,
) -> dict:
    payload: Dict[str, Any] = {
        "jurisdiction_id": jurisdiction_id,
        "name": name,
        "management_company": management_company,
        "estoppel_fee_cents": estoppel_fee_cents,
        "estoppel_validity_days": estoppel_validity_days,
    }
    payload.update(overrides)
    return payload


def create_search_order_payload(
    parcel_number: str,
    property_address: str = "1 Test St",
    closing_date: str = "2026-08-20",
    order_class: str = "STANDARD",
    association_id: Optional[str] = None,
    service_date: Optional[str] = None,
    jurisdiction_id: Optional[str] = None,
    extended_coverage: Optional[bool] = None,
    **overrides,
) -> dict:
    payload: Dict[str, Any] = {
        "property_address": property_address,
        "parcel_number": parcel_number,
        "closing_date": closing_date,
        "order_class": order_class,
    }
    if association_id is not None:
        payload["association_id"] = association_id
    if service_date is not None:
        payload["service_date"] = service_date
    if jurisdiction_id is not None:
        payload["jurisdiction_id"] = jurisdiction_id
    if extended_coverage is not None:
        payload["extended_coverage"] = extended_coverage
    payload.update(overrides)
    return payload


def finding_unpaid_utility(amount_cents: int, **overrides) -> dict:
    finding = {"finding_kind": "UNPAID_UTILITY", "amount_cents": amount_cents}
    finding.update(overrides)
    return finding


def finding_code_violation(
    amount_cents: int,
    daily_accrual_cents: Optional[float] = None,
    days_outstanding: Optional[int] = None,
    **overrides,
) -> dict:
    finding: Dict[str, Any] = {"finding_kind": "CODE_VIOLATION", "amount_cents": amount_cents}
    if daily_accrual_cents is not None:
        finding["daily_accrual_cents"] = daily_accrual_cents
    if days_outstanding is not None:
        finding["days_outstanding"] = days_outstanding
    finding.update(overrides)
    return finding


def record_findings_payload(
    expected_research_task_version: int, findings: List[dict]
) -> dict:
    return {
        "expected_research_task_version": expected_research_task_version,
        "findings": findings,
    }


def patch_order_payload(
    expected_search_order_version: int,
    closing_date: Optional[str] = None,
    association_id: Optional[str] = None,
    **overrides,
) -> dict:
    payload: Dict[str, Any] = {
        "expected_search_order_version": expected_search_order_version
    }
    if closing_date is not None:
        payload["closing_date"] = closing_date
    if association_id is not None:
        payload["association_id"] = association_id
    payload.update(overrides)
    return payload


def create_discrepancy_payload(
    search_order_id: str,
    subject_type: str,
    subject_id: str,
    discrepancy_type: str,
    claimed_amount_cents: int,
    description: str = "test discrepancy",
    **overrides,
) -> dict:
    payload: Dict[str, Any] = {
        "search_order_id": search_order_id,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "discrepancy_type": discrepancy_type,
        "claimed_amount_cents": claimed_amount_cents,
        "description": description,
    }
    payload.update(overrides)
    return payload


def resolve_discrepancy_payload(
    resolution_outcome: str, confirmed_amount_cents: Optional[int] = None
) -> dict:
    payload: Dict[str, Any] = {"resolution_outcome": resolution_outcome}
    if confirmed_amount_cents is not None:
        payload["confirmed_amount_cents"] = confirmed_amount_cents
    return payload
