"""Payload factories — one factory per entity, input fields only.

Field names match PRD §3 / §4 verbatim. Every factory accepts **overrides
so individual tests can pin specific values for boundary or precondition
behavior.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Helpers for unique inputs
# ---------------------------------------------------------------------------
def unique_legal_name(prefix: str = "Enterprise") -> str:
    return f"{prefix} {uuid.uuid4().hex[:8].upper()}"


def unique_email(prefix: str = "ops") -> str:
    return f"{prefix}+{uuid.uuid4().hex[:8]}@example.com"


def unique_agency_id(prefix: str = "agency") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# Many cycle_year fields must be unique (PRD §3.1: "cycle_year (which must
# be unique across all cycles)"). The generator's cap (sane integers) avoids
# the need for a separate registry.
_CYCLE_YEAR_COUNTER = [3000]  # well outside any reasonable test reality


def unique_cycle_year() -> int:
    _CYCLE_YEAR_COUNTER[0] += 1
    return _CYCLE_YEAR_COUNTER[0]


# ---------------------------------------------------------------------------
# Enterprise (PRD §3.1)
# ---------------------------------------------------------------------------
def create_enterprise_payload(
    *,
    legal_name: Optional[str] = None,
    jurisdiction_code: str = "JD_ALPHA",
    industry_code: str = "POWER",
    contact_email: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": legal_name or unique_legal_name(),
        "jurisdiction_code": jurisdiction_code,
        "industry_code": industry_code,
        "contact_email": contact_email or unique_email(),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# AllocationCycle (PRD §3.1)
# ---------------------------------------------------------------------------
def create_allocation_cycle_payload(
    *,
    cycle_year: Optional[int] = None,
    free_paid_ratio: float = 0.80,
    ccer_cap_pct: float = 0.05,
    objection_deadline: str = "2030-06-01T00:00:00.000Z",
    compliance_deadline: str = "2030-12-31T23:59:59.000Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "cycle_year": cycle_year if cycle_year is not None else unique_cycle_year(),
        "free_paid_ratio": free_paid_ratio,
        "ccer_cap_pct": ccer_cap_pct,
        "objection_deadline": objection_deadline,
        "compliance_deadline": compliance_deadline,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Allocation (PRD §3.2)
# ---------------------------------------------------------------------------
def create_allocation_payload(
    *,
    enterprise_id: str,
    method: str,
    activity_volume: Optional[float] = None,
    benchmark_factor: Optional[float] = None,
    historical_baseline: Optional[float] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "enterprise_id": enterprise_id,
        "method": method,
    }
    if activity_volume is not None:
        payload["activity_volume"] = activity_volume
    if benchmark_factor is not None:
        payload["benchmark_factor"] = benchmark_factor
    if historical_baseline is not None:
        payload["historical_baseline"] = historical_baseline
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Objection (PRD §3.2)
# ---------------------------------------------------------------------------
def file_objection_payload(
    *,
    filer_enterprise_id: str,
    ground: str = "We dispute the calculation basis.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "filer_enterprise_id": filer_enterprise_id,
        "ground": ground,
    }
    payload.update(overrides)
    return payload


def uphold_objection_payload(
    *,
    revised_total_quota: float,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "revised_total_quota": revised_total_quota,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# EmissionReport (PRD §3.3)
# ---------------------------------------------------------------------------
def create_emission_report_payload(
    *,
    cycle_year: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"cycle_year": cycle_year}
    payload.update(overrides)
    return payload


def add_emission_line_payload(
    *,
    source_category: str,
    activity_data: float,
    emission_factor: float,
    supporting_document_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "source_category": source_category,
        "activity_data": activity_data,
        "emission_factor": emission_factor,
    }
    # PRD §3.3: required for FUEL/PROCESS, omitted for ELECTRICITY/FUGITIVE.
    if supporting_document_id is not None:
        payload["supporting_document_id"] = supporting_document_id
    payload.update(overrides)
    return payload


def upload_supporting_document_payload(
    *,
    document_type: str = "FUEL_INVOICE",
    file_uri: str = "s3://bucket/doc.pdf",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "document_type": document_type,
        "file_uri": file_uri,
    }
    payload.update(overrides)
    return payload


def reject_emission_report_payload(
    *,
    reason: str = "Template violation: missing FUEL document",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


def dispute_emission_report_payload(
    *,
    ground: str = "Verifier adjustment is incorrect",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"ground": ground}
    payload.update(overrides)
    return payload


def resolve_dispute_payload(
    *,
    adjusted_total_verified_emissions: Optional[float] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if adjusted_total_verified_emissions is not None:
        payload["adjusted_total_verified_emissions"] = (
            adjusted_total_verified_emissions
        )
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# VerificationAssignment (PRD §3.4)
# ---------------------------------------------------------------------------
def assign_verifier_payload(
    *,
    agency_id: str,
    scheduled_visit_at: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "agency_id": agency_id,
        "scheduled_visit_at": scheduled_visit_at,
    }
    payload.update(overrides)
    return payload


def complete_onsite_payload(
    *,
    line_adjustments: List[Dict[str, Any]],
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "line_adjustments": line_adjustments,
    }
    payload.update(overrides)
    return payload


def line_adjustment(*, line_id: str, verified_amount: float) -> Dict[str, Any]:
    return {"line_id": line_id, "verified_amount": verified_amount}


# ---------------------------------------------------------------------------
# TradingOrder (PRD §3.5)
# ---------------------------------------------------------------------------
def create_trading_order_payload(
    *,
    enterprise_id: str,
    side: str,
    instrument: str,
    order_type: str,
    quantity: float,
    channel: str,
    limit_price: Optional[float] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "enterprise_id": enterprise_id,
        "side": side,
        "instrument": instrument,
        "order_type": order_type,
        "quantity": quantity,
        "channel": channel,
    }
    # PRD §3.5: limit_price required for LIMIT, must be null for MARKET.
    if limit_price is not None:
        payload["limit_price"] = limit_price
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ComplianceDeclaration (PRD §3.6)
# ---------------------------------------------------------------------------
def create_compliance_declaration_payload(
    *,
    cycle_year: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"cycle_year": cycle_year}
    payload.update(overrides)
    return payload


def submit_compliance_declaration_payload(
    *,
    declared_offset_quota: float,
    declared_offset_ccer: float,
    declared_borrow_amount: Optional[float] = None,
    declared_bank_amount: Optional[float] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "declared_offset_quota": declared_offset_quota,
        "declared_offset_ccer": declared_offset_ccer,
    }
    if declared_borrow_amount is not None:
        payload["declared_borrow_amount"] = declared_borrow_amount
    if declared_bank_amount is not None:
        payload["declared_bank_amount"] = declared_bank_amount
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Test-driver event payload (PRD §2.10)
# ---------------------------------------------------------------------------
def emit_event_payload(
    *,
    external_system: str,
    event_type: str,
    payload: Dict[str, Any],
    **overrides: Any,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "external_system": external_system,
        "event_type": event_type,
        "payload": payload,
    }
    body.update(overrides)
    return body


__all__ = [
    "unique_legal_name",
    "unique_email",
    "unique_agency_id",
    "unique_cycle_year",
    "create_enterprise_payload",
    "create_allocation_cycle_payload",
    "create_allocation_payload",
    "file_objection_payload",
    "uphold_objection_payload",
    "create_emission_report_payload",
    "add_emission_line_payload",
    "upload_supporting_document_payload",
    "reject_emission_report_payload",
    "dispute_emission_report_payload",
    "resolve_dispute_payload",
    "assign_verifier_payload",
    "complete_onsite_payload",
    "line_adjustment",
    "create_trading_order_payload",
    "create_compliance_declaration_payload",
    "submit_compliance_declaration_payload",
    "emit_event_payload",
]
