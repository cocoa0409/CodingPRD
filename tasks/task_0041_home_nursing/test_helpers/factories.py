"""Payload factories -- one per entity, input fields only.

Field names match PRD §3 verbatim. Each factory accepts **overrides so
individual tests can pin specific values for boundary or precondition
behavior.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Unique-id helpers
# ---------------------------------------------------------------------------
def unique_id(prefix: str = "u") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def unique_user_id(prefix: str = "user") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def unique_license_number(prefix: str = "LIC") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def unique_service_item_code(prefix: str = "SI") -> str:
    return f"{prefix}{uuid.uuid4().hex[:8].upper()}"


def unique_idempotency_key() -> str:
    return f"idem-{uuid.uuid4().hex[:16]}"


# ---------------------------------------------------------------------------
# Nurse (PRD §3.1)
# ---------------------------------------------------------------------------
def create_nurse_payload(
    *,
    full_name: Optional[str] = None,
    gender: str = "F",
    languages: Optional[List[str]] = None,
    license_number: Optional[str] = None,
    specialty_tags: Optional[List[str]] = None,
    home_lat: float = 31.30,
    home_lng: float = 121.40,
    max_daily_orders: Optional[int] = None,
    revenue_share_bps: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": full_name or f"Nurse-{uuid.uuid4().hex[:6]}",
        "gender": gender,
        "languages": languages if languages is not None else ["en"],
        "license_number": license_number or unique_license_number(),
        "specialty_tags": (
            specialty_tags if specialty_tags is not None
            else ["IV_INFUSION"]
        ),
        "home_lat": home_lat,
        "home_lng": home_lng,
    }
    if max_daily_orders is not None:
        payload["max_daily_orders"] = max_daily_orders
    if revenue_share_bps is not None:
        payload["revenue_share_bps"] = revenue_share_bps
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# CertificationRecord (PRD §3.1)
# ---------------------------------------------------------------------------
def create_certification_record_payload(
    *,
    kind: str,
    outcome: str,
    effective_at: str,
    training_hours: Optional[float] = None,
    notes: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "kind": kind,
        "outcome": outcome,
        "effective_at": effective_at,
    }
    if training_hours is not None:
        payload["training_hours"] = training_hours
    if notes is not None:
        payload["notes"] = notes
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ServiceItem (PRD §3.2)
# ---------------------------------------------------------------------------
def create_service_item_payload(
    *,
    code: Optional[str] = None,
    name: Optional[str] = None,
    description: str = "Test service description",
    contraindications: str = "None recorded",
    required_skill: str = "IV_INFUSION",
    requires_medical_doc: Optional[bool] = None,
    requires_eligibility_review: Optional[bool] = None,
    base_price_cents: int = 20000,
    duration_minutes: int = 30,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": code or unique_service_item_code(),
        "name": name or f"Service-{uuid.uuid4().hex[:6]}",
        "description": description,
        "contraindications": contraindications,
        "required_skill": required_skill,
        "base_price_cents": base_price_cents,
        "duration_minutes": duration_minutes,
    }
    if requires_medical_doc is not None:
        payload["requires_medical_doc"] = requires_medical_doc
    if requires_eligibility_review is not None:
        payload["requires_eligibility_review"] = requires_eligibility_review
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Order (PRD §3.2)
# ---------------------------------------------------------------------------
def create_order_payload(
    *,
    service_item_code: str,
    service_address: str = "Test Address 1",
    service_lat: float = 31.20,
    service_lng: float = 121.40,
    scheduled_start: str,
    preferred_gender: Optional[str] = None,
    preferred_language: Optional[str] = None,
    medical_doc_url: Optional[str] = None,
    package_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "service_item_code": service_item_code,
        "service_address": service_address,
        "service_lat": service_lat,
        "service_lng": service_lng,
        "scheduled_start": scheduled_start,
    }
    if preferred_gender is not None:
        payload["preferred_gender"] = preferred_gender
    if preferred_language is not None:
        payload["preferred_language"] = preferred_language
    if medical_doc_url is not None:
        payload["medical_doc_url"] = medical_doc_url
    if package_id is not None:
        payload["package_id"] = package_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Eligibility review (PRD §3.2)
# ---------------------------------------------------------------------------
def review_order_payload(
    *,
    decision: str,
    notes: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if notes is not None:
        payload["notes"] = notes
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ServiceRecord (PRD §3.4)
# ---------------------------------------------------------------------------
def checklist_item(step: str, done: bool = True,
                   note: str = "") -> Dict[str, Any]:
    return {"step": step, "done": done, "note": note}


def vital_entry(ts: str, type_: str = "BP",
                value: str = "120/80", unit: str = "mmHg") -> Dict[str, Any]:
    return {"ts": ts, "type": type_, "value": value, "unit": unit}


def medication_entry(name: str, dose: str, route: str,
                     ts: str) -> Dict[str, Any]:
    return {"name": name, "dose": dose, "route": route, "ts": ts}


def abnormal_event(ts: str, severity: str = "LOW",
                   description: str = "") -> Dict[str, Any]:
    return {"ts": ts, "severity": severity, "description": description}


def create_service_record_payload(
    *,
    checkin_at: str,
    checkin_lat: float,
    checkin_lng: float,
    face_verification_passed: bool = True,
    checklist_items: Optional[List[Dict[str, Any]]] = None,
    vitals: Optional[List[Dict[str, Any]]] = None,
    medications_administered: Optional[List[Dict[str, Any]]] = None,
    evidence_urls: Optional[List[str]] = None,
    abnormal_events: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "checkin_at": checkin_at,
        "checkin_lat": checkin_lat,
        "checkin_lng": checkin_lng,
        "face_verification_passed": face_verification_passed,
    }
    if checklist_items is not None:
        payload["checklist_items"] = checklist_items
    if vitals is not None:
        payload["vitals"] = vitals
    if medications_administered is not None:
        payload["medications_administered"] = medications_administered
    if evidence_urls is not None:
        payload["evidence_urls"] = evidence_urls
    if abnormal_events is not None:
        payload["abnormal_events"] = abnormal_events
    payload.update(overrides)
    return payload


def patch_service_record_payload(
    *,
    checklist_items: Optional[List[Dict[str, Any]]] = None,
    vitals: Optional[List[Dict[str, Any]]] = None,
    medications_administered: Optional[List[Dict[str, Any]]] = None,
    evidence_urls: Optional[List[str]] = None,
    abnormal_events: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if checklist_items is not None:
        payload["checklist_items"] = checklist_items
    if vitals is not None:
        payload["vitals"] = vitals
    if medications_administered is not None:
        payload["medications_administered"] = medications_administered
    if evidence_urls is not None:
        payload["evidence_urls"] = evidence_urls
    if abnormal_events is not None:
        payload["abnormal_events"] = abnormal_events
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# WasteEntry (PRD §3.4)
# ---------------------------------------------------------------------------
def create_waste_entry_payload(
    *,
    category: str = "SHARPS",
    quantity: float = 1.0,
    unit: str = "PCS",
    sealed: Optional[bool] = None,
    disposal_unit_id: Optional[str] = None,
    handover_at: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "category": category,
        "quantity": quantity,
        "unit": unit,
    }
    if sealed is not None:
        payload["sealed"] = sealed
    if disposal_unit_id is not None:
        payload["disposal_unit_id"] = disposal_unit_id
    if handover_at is not None:
        payload["handover_at"] = handover_at
    payload.update(overrides)
    return payload


def patch_waste_entry_payload(
    *,
    sealed: Optional[bool] = None,
    disposal_unit_id: Optional[str] = None,
    handover_at: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if sealed is not None:
        payload["sealed"] = sealed
    if disposal_unit_id is not None:
        payload["disposal_unit_id"] = disposal_unit_id
    if handover_at is not None:
        payload["handover_at"] = handover_at
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Package (PRD §3.2)
# ---------------------------------------------------------------------------
def create_package_payload(
    *,
    patient_id: str,
    service_item_code: str,
    total_credits: int = 3,
    expires_at: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "patient_id": patient_id,
        "service_item_code": service_item_code,
        "total_credits": total_credits,
        "expires_at": expires_at,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Complaint (PRD §3.5)
# ---------------------------------------------------------------------------
def create_complaint_payload(
    *,
    order_id: str,
    category: str = "SERVICE_QUALITY",
    description: str = "Service did not match expectations.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "order_id": order_id,
        "category": category,
        "description": description,
    }
    payload.update(overrides)
    return payload


def resolve_complaint_payload(
    *,
    decision: str,
    compensation_cents: Optional[int] = None,
    rating_impact: Optional[float] = None,
    resolution_notes: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if compensation_cents is not None:
        payload["compensation_cents"] = compensation_cents
    if rating_impact is not None:
        payload["rating_impact"] = rating_impact
    if resolution_notes is not None:
        payload["resolution_notes"] = resolution_notes
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Payout batches (PRD §3.5)
# ---------------------------------------------------------------------------
def create_payout_batch_payload(
    *,
    cutoff_at: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"cutoff_at": cutoff_at}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Test-hook event payloads (PRD §3.6)
# ---------------------------------------------------------------------------
def emit_event_payload(
    *,
    system: str,
    event_type: str,
    payload: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "system": system,
        "event_type": event_type,
        "payload": payload if payload is not None else {},
    }
    body.update(overrides)
    return body


__all__ = [
    "unique_id",
    "unique_user_id",
    "unique_license_number",
    "unique_service_item_code",
    "unique_idempotency_key",
    "create_nurse_payload",
    "create_certification_record_payload",
    "create_service_item_payload",
    "create_order_payload",
    "review_order_payload",
    "checklist_item",
    "vital_entry",
    "medication_entry",
    "abnormal_event",
    "create_service_record_payload",
    "patch_service_record_payload",
    "create_waste_entry_payload",
    "patch_waste_entry_payload",
    "create_package_payload",
    "create_complaint_payload",
    "resolve_complaint_payload",
    "create_payout_batch_payload",
    "emit_event_payload",
]
