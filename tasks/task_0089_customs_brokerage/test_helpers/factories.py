"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact schema the PRD declares for the request
body (PRD §3.1–§3.11). Tests pass overrides for the values they want
to control.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# ISO 8601 UTC timestamp helper (PRD §2.4 — three fractional digits).
# ---------------------------------------------------------------------------
def iso_utc(dt: datetime) -> str:
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def random_tax_id(prefix: str = "TAX") -> str:
    """Return a unique tax_id within PRD §3.1's 1..40 char constraint."""
    return f"{prefix}-{_uuid.uuid4().hex[:8].upper()}"


def random_legal_name(prefix: str = "Acme Trading Co.") -> str:
    return f"{prefix} {_uuid.uuid4().hex[:6].upper()}"


def random_shipment_reference(prefix: str = "MBL") -> str:
    """Carrier reference, 1..60 chars (PRD §3.3)."""
    return f"{prefix}-{_uuid.uuid4().hex[:10].upper()}"


# ---------------------------------------------------------------------------
# ClientCompany (PRD §3.1)
# ---------------------------------------------------------------------------
def create_client_payload(
    legal_name: Optional[str] = None,
    tax_id: Optional[str] = None,
    country_code: str = "CN",
    contact_email: str = "ops@example.com",
    default_settlement_currency: str = "CNY",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": legal_name or random_legal_name(),
        "tax_id": tax_id or random_tax_id(),
        "country_code": country_code,
        "contact_email": contact_email,
        "default_settlement_currency": default_settlement_currency,
    }
    payload.update(overrides)
    return payload


def update_client_payload(version: int, **overrides: Any) -> Dict[str, Any]:
    """PATCH /customs/clients/{id} — input: legal_name?, contact_email?,
    default_settlement_currency?, status?, version (PRD §3.1)."""
    payload: Dict[str, Any] = {"version": version}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# CommissionAgreement (PRD §3.1, §3.2)
# ---------------------------------------------------------------------------
def create_agreement_payload(
    client_id: str,
    scope_of_service: Optional[List[str]] = None,
    fee_schedule: Optional[Dict[str, float]] = None,
    agreement_currency: str = "USD",
    valid_from: str = "2026-01-01T00:00:00.000Z",
    valid_until: str = "2027-01-01T00:00:00.000Z",
    late_interest_daily_rate_bps: int = 100,
    renewed_from_agreement_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    if scope_of_service is None:
        scope_of_service = ["DECLARATION", "INSPECTION", "TARIFF_ADVANCE",
                            "AMENDMENT", "RETURN_SHIP"]
    if fee_schedule is None:
        fee_schedule = {
            "DECLARATION": 100,
            "INSPECTION": 50,
            "TARIFF_ADVANCE": 80,
            "AMENDMENT": 30,
            "RETURN_SHIP": 200,
        }
    payload: Dict[str, Any] = {
        "client_id": client_id,
        "scope_of_service": list(scope_of_service),
        "fee_schedule": dict(fee_schedule),
        "agreement_currency": agreement_currency,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "late_interest_daily_rate_bps": late_interest_daily_rate_bps,
    }
    if renewed_from_agreement_id is not None:
        payload["renewed_from_agreement_id"] = renewed_from_agreement_id
    payload.update(overrides)
    return payload


def request_signature_payload(version: Optional[int] = None,
                              **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


def sign_agreement_payload(signature_token: str,
                           version: Optional[int] = None,
                           **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"signature_token": signature_token}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


def terminate_agreement_payload(terminated_reason: str = "CLIENT_REQUEST",
                                version: Optional[int] = None,
                                **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"terminated_reason": terminated_reason}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Declaration (PRD §3.3 / §3.5 / §3.6 / §3.11)
# ---------------------------------------------------------------------------
def create_declaration_payload(
    agreement_id: str,
    jurisdiction_code: str = "CN",
    shipment_reference: Optional[str] = None,
    hs_code: str = "85171200",
    country_of_origin: str = "JP",
    trade_agreement_code: Optional[str] = "NONE",
    declared_value_amount: float = 1000.00,
    declared_currency: str = "USD",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "agreement_id": agreement_id,
        "jurisdiction_code": jurisdiction_code,
        "shipment_reference": shipment_reference or random_shipment_reference(),
        "hs_code": hs_code,
        "country_of_origin": country_of_origin,
        "declared_value_amount": declared_value_amount,
        "declared_currency": declared_currency,
    }
    if trade_agreement_code is not None:
        payload["trade_agreement_code"] = trade_agreement_code
    payload.update(overrides)
    return payload


def update_declaration_payload(version: int, **overrides: Any) -> Dict[str, Any]:
    """PATCH — mutable: declared_value_amount?, hs_code?,
    country_of_origin?, trade_agreement_code? (PRD §3.3)."""
    payload: Dict[str, Any] = {"version": version}
    payload.update(overrides)
    return payload


def action_with_version_payload(version: Optional[int] = None,
                                **overrides: Any) -> Dict[str, Any]:
    """Generic body for action endpoints that accept only an optional
    version (request-documents, file, amend, withdraw, screen,
    pre-validate)."""
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


def respond_query_payload(response_note: str = "Clarification provided.",
                          version: Optional[int] = None,
                          **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"response_note": response_note}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ShipmentDocument (PRD §3.4)
# ---------------------------------------------------------------------------
def attach_document_payload(
    doc_type: str = "COMMERCIAL_INVOICE",
    storage_uri: str = "s3://docs/invoice-001.pdf",
    declared_total_value: Optional[float] = None,
    declared_total_currency: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "doc_type": doc_type,
        "storage_uri": storage_uri,
    }
    if declared_total_value is not None:
        payload["declared_total_value"] = declared_total_value
    if declared_total_currency is not None:
        payload["declared_total_currency"] = declared_total_currency
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# InspectionCase (PRD §3.7)
# ---------------------------------------------------------------------------
def create_inspection_case_payload(
    filing_id: str,
    warehouse_code: str = "BOND-001",
    scheduled_at: str = "2026-01-15T08:00:00.000Z",
    sample_required: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "filing_id": filing_id,
        "warehouse_code": warehouse_code,
        "scheduled_at": scheduled_at,
    }
    if sample_required is not None:
        payload["sample_required"] = sample_required
    payload.update(overrides)
    return payload


def record_outcome_payload(
    outcome: str,
    post_inspection_doc_uri: str = "s3://inspections/report-001.pdf",
    penalty_amount: Optional[float] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "outcome": outcome,
        "post_inspection_doc_uri": post_inspection_doc_uri,
    }
    if penalty_amount is not None:
        payload["penalty_amount"] = penalty_amount
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# External-event payloads (PRD §2.12, §3.6, §3.10)
# ---------------------------------------------------------------------------
def emit_customs_response_payload(
    filing_id: str,
    response_type: str,  # RELEASE | QUERY | INSPECT | REJECT
    reason_code: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    inner: Dict[str, Any] = {"response_type": response_type}
    if reason_code is not None:
        inner["reason_code"] = reason_code
    payload: Dict[str, Any] = {
        "source_system": "SINGLE_WINDOW",
        "event_type": "CUSTOMS_RESPONSE",
        "target_entity_type": "FILING",
        "target_entity_id": filing_id,
        "payload": inner,
    }
    payload.update(overrides)
    return payload


def emit_manifest_dropped_payload(
    filing_id: str,
    shipment_reference: str,
    hs_code: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "source_system": "LOGISTICS",
        "event_type": "MANIFEST_DROPPED",
        "target_entity_type": "FILING",
        "target_entity_id": filing_id,
        "payload": {
            "shipment_reference": shipment_reference,
            "hs_code": hs_code,
        },
    }
    payload.update(overrides)
    return payload


def emit_bank_debit_payload(
    settlement_id: str,
    amount: float,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "source_system": "BANK",
        "event_type": "BANK_DEBIT_CONFIRMED",
        "target_entity_type": "SETTLEMENT",
        "target_entity_id": settlement_id,
        "payload": {"amount": amount},
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clock advance (PRD §2.12)
# ---------------------------------------------------------------------------
def clock_advance_payload(to_timestamp: str) -> Dict[str, Any]:
    return {"to_timestamp": to_timestamp}


# ---------------------------------------------------------------------------
# Settlement (PRD §3.10)
# ---------------------------------------------------------------------------
def advance_settlement_payload(version: Optional[int] = None,
                               **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


__all__ = [
    "iso_utc",
    "random_tax_id",
    "random_legal_name",
    "random_shipment_reference",
    "create_client_payload",
    "update_client_payload",
    "create_agreement_payload",
    "request_signature_payload",
    "sign_agreement_payload",
    "terminate_agreement_payload",
    "create_declaration_payload",
    "update_declaration_payload",
    "action_with_version_payload",
    "respond_query_payload",
    "attach_document_payload",
    "create_inspection_case_payload",
    "record_outcome_payload",
    "emit_customs_response_payload",
    "emit_manifest_dropped_payload",
    "emit_bank_debit_payload",
    "clock_advance_payload",
    "advance_settlement_payload",
]
