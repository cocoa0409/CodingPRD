"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema the PRD declares for the
request body. Tests pass overrides for the values they want to control.
Only PRD-declared input fields are produced; computed fields are
intentionally omitted so the implementation cannot accidentally accept
them.

PRD §2.4 timestamps are ISO 8601 UTC with three fractional digits
(e.g. "2025-05-24T10:30:00.123Z"). PRD §2.8 monetary fields are
integer cents.
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Timestamp helpers — PRD §2.4 format with three fractional digits.
# ---------------------------------------------------------------------------
def iso_utc(dt: datetime) -> str:
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def iso_now() -> str:
    return iso_utc(utcnow())


def iso_offset(*, days: int = 0, hours: int = 0, minutes: int = 0,
               seconds: int = 0,
               base: Optional[datetime] = None) -> str:
    base = base or utcnow()
    return iso_utc(base + timedelta(
        days=days, hours=hours, minutes=minutes, seconds=seconds,
    ))


# ---------------------------------------------------------------------------
# Random suffix for uniqueness (project codes, SKU codes, room codes).
# ---------------------------------------------------------------------------
_ALPHANUM = string.ascii_uppercase + string.digits


def random_suffix(n: int = 8) -> str:
    return "".join(random.choices(_ALPHANUM, k=n))


# ---------------------------------------------------------------------------
# Date-of-birth helpers (PRD §3.3 enforces customer age >= 18)
# ---------------------------------------------------------------------------
def dob_for_age(age_years: int) -> str:
    """Return an ISO 8601 date (YYYY-MM-DD) representing today minus
    age_years and one extra day for safety.
    """
    today = date.today()
    dob = today.replace(year=today.year - age_years)
    # Subtract one day so the birthday has already passed in the
    # current year — guarantees age >= age_years.
    dob = dob - timedelta(days=1)
    return dob.isoformat()


# ---------------------------------------------------------------------------
# Project (PRD §3.1)
# ---------------------------------------------------------------------------
def create_project_payload(
    *,
    sku_id: Optional[str] = None,
    sku_id_secondary: Optional[str] = None,
    qualified_doctor_ids: Optional[List[str]] = None,
    pricing_tiers: Optional[List[Dict[str, Any]]] = None,
    bom: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Build a POST /aesthetics/projects payload.

    PRD §3.1 required input fields:
    code, name, category, technique, duration_minutes, recovery_days,
    risk_level, bom, qualified_doctor_ids, pricing_tiers.

    bom defaults to a 1-entry list referencing `sku_id`; supply the
    real ConsumableSku.id via `sku_id=...` before submitting.
    """
    suffix = random_suffix(6)
    if bom is None:
        if sku_id is None:
            raise ValueError(
                "create_project_payload requires sku_id (or an explicit bom)"
            )
        bom = [{"sku_id": sku_id, "quantity": 1}]
        if sku_id_secondary is not None:
            bom.append({"sku_id": sku_id_secondary, "quantity": 1})
    if pricing_tiers is None:
        pricing_tiers = [
            {"tier_code": "T0", "base_price_cents": 100000, "min_quantity": 1},
        ]
    if qualified_doctor_ids is None:
        qualified_doctor_ids = ["doctor-attending-001"]

    payload: Dict[str, Any] = {
        "code": f"P-{suffix}",
        "name": f"Test Project {suffix}",
        "category": "NON_SURGICAL",
        "technique": "Standard non-surgical technique narrative.",
        "duration_minutes": 30,
        "recovery_days": 7,
        "risk_level": "LOW",
        "bom": bom,
        "qualified_doctor_ids": list(qualified_doctor_ids),
        "pricing_tiers": list(pricing_tiers),
    }
    payload.update(overrides)
    return payload


def patch_project_payload(**overrides: Any) -> Dict[str, Any]:
    """PATCH /aesthetics/projects/{id} — all fields optional per PRD §3.1."""
    return dict(overrides)


# ---------------------------------------------------------------------------
# ContraindicationRule (PRD §3.1)
# ---------------------------------------------------------------------------
def create_contraindication_rule_payload(
    *,
    severity: str = "ABSOLUTE",
    predicate: Optional[Dict[str, Any]] = None,
    reason: str = "Test contraindication",
    **overrides: Any,
) -> Dict[str, Any]:
    """Build a POST /aesthetics/projects/{id}/contraindication-rules
    payload per PRD §3.1: { severity, predicate, reason }.
    """
    if predicate is None:
        predicate = {
            "field": "health_declaration.is_pregnant",
            "op": "EQ",
            "value": True,
        }
    payload = {
        "severity": severity,
        "predicate": predicate,
        "reason": reason,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ConsumableSku (PRD §3.1)
# ---------------------------------------------------------------------------
def create_consumable_sku_payload(
    *,
    sku_code: Optional[str] = None,
    name: Optional[str] = None,
    kind: str = "CONSUMABLE",
    requires_lot_tracking: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: sku_code regex /^[A-Z0-9-]{3,32}$/."""
    suffix = random_suffix(6)
    payload = {
        "sku_code": sku_code or f"SKU-{suffix}",
        "name": name or f"Test SKU {suffix}",
        "kind": kind,
        "requires_lot_tracking": requires_lot_tracking,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Room (PRD §3.1)
# ---------------------------------------------------------------------------
def create_room_payload(
    *,
    code: Optional[str] = None,
    room_kind: str = "PROCEDURE",
    is_active: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    suffix = random_suffix(6)
    payload = {
        "code": code or f"R-{suffix}",
        "room_kind": room_kind,
        "is_active": is_active,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Customer (PRD §3.2)
# ---------------------------------------------------------------------------
def create_customer_payload(
    *,
    full_name: str = "Test Customer",
    date_of_birth: Optional[str] = None,
    age_years: int = 30,
    contact_phone: str = "+15555550100",
    medical_history: Optional[List[str]] = None,
    allergies: Optional[List[str]] = None,
    medication_history: Optional[List[str]] = None,
    health_declaration: Optional[Dict[str, Any]] = None,
    photo_archive_ids: Optional[List[str]] = None,
    scan3d_archive_ids: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /aesthetics/customers payload per PRD §3.2."""
    if date_of_birth is None:
        date_of_birth = dob_for_age(age_years)
    if health_declaration is None:
        health_declaration = {
            "is_pregnant": False,
            "has_uncontrolled_hypertension": False,
            "has_active_infection": False,
            "has_bleeding_disorder": False,
        }
    payload: Dict[str, Any] = {
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "contact_phone": contact_phone,
        "medical_history": list(medical_history or []),
        "allergies": list(allergies or []),
        "medication_history": list(medication_history or []),
        "health_declaration": dict(health_declaration),
        "photo_archive_ids": list(photo_archive_ids or []),
        "scan3d_archive_ids": list(scan3d_archive_ids or []),
    }
    payload.update(overrides)
    return payload


def patch_customer_payload(**overrides: Any) -> Dict[str, Any]:
    """PATCH /aesthetics/customers/{id} — all fields optional per PRD §3.2."""
    return dict(overrides)


def submit_kyc_payload(
    *,
    kyc_status: str = "VERIFIED",
    credit_score: int = 750,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /aesthetics/customers/{id}/kyc per PRD §3.2/§3.7."""
    payload = {"kyc_status": kyc_status, "credit_score": credit_score}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# TreatmentPlan (PRD §3.3)
# ---------------------------------------------------------------------------
def create_plan_payload(
    *,
    customer_id: str,
    items: List[Dict[str, Any]],
    expected_outcome: str = "Standard expected outcome narrative.",
    risk_disclosure: str = "Standard risk disclosure document text.",
    attending_physician_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /aesthetics/plans per PRD §3.3."""
    payload: Dict[str, Any] = {
        "customer_id": customer_id,
        "items": list(items),
        "expected_outcome": expected_outcome,
        "risk_disclosure": risk_disclosure,
    }
    if attending_physician_id is not None:
        payload["attending_physician_id"] = attending_physician_id
    payload.update(overrides)
    return payload


def plan_item(project_id: str, tier_code: str = "T0",
              quantity: int = 1) -> Dict[str, Any]:
    """Convenience for a plan items[] entry per PRD §3.3."""
    return {"project_id": project_id, "tier_code": tier_code,
            "quantity": int(quantity)}


def patch_plan_payload(**overrides: Any) -> Dict[str, Any]:
    """PATCH /aesthetics/plans/{id} — all fields optional per PRD §3.3."""
    return dict(overrides)


# ---------------------------------------------------------------------------
# Appointment (PRD §3.4)
# ---------------------------------------------------------------------------
def create_appointment_payload(
    *,
    plan_id: str,
    project_id: str,
    scheduled_start: str,
    doctor_id: str,
    nurse_id: str,
    room_id: str,
    equipment_ids: Optional[List[str]] = None,
    anesthesia_resource_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /aesthetics/appointments per PRD §3.4."""
    payload: Dict[str, Any] = {
        "plan_id": plan_id,
        "project_id": project_id,
        "scheduled_start": scheduled_start,
        "doctor_id": doctor_id,
        "nurse_id": nurse_id,
        "room_id": room_id,
        "equipment_ids": list(equipment_ids or ["eq-001"]),
    }
    if anesthesia_resource_id is not None:
        payload["anesthesia_resource_id"] = anesthesia_resource_id
    payload.update(overrides)
    return payload


def reschedule_appointment_payload(
    *,
    scheduled_start: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /aesthetics/appointments/{id}/reschedule per PRD §3.4."""
    payload: Dict[str, Any] = {"scheduled_start": scheduled_start}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# OperativeRecord sub-actions (PRD §3.5)
# ---------------------------------------------------------------------------
def op_record_key_step_payload(*, note: str = "Key step recorded",
                               **overrides: Any) -> Dict[str, Any]:
    payload = {"note": note}
    payload.update(overrides)
    return payload


def op_record_consumables_payload(
    *,
    sku_id: str,
    quantity: int = 1,
    lot_number: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.5: SKUs with requires_lot_tracking=true must carry a
    non-empty lot_number."""
    payload: Dict[str, Any] = {"sku_id": sku_id, "quantity": int(quantity)}
    if lot_number is not None:
        payload["lot_number"] = lot_number
    payload.update(overrides)
    return payload


def op_record_vitals_payload(*, asset_id: str = "asset-vitals-001",
                             **overrides: Any) -> Dict[str, Any]:
    payload = {"asset_id": asset_id}
    payload.update(overrides)
    return payload


def op_record_incident_payload(*, severity: str = "MINOR",
                               note: str = "Incident note",
                               **overrides: Any) -> Dict[str, Any]:
    payload = {"severity": severity, "note": note}
    payload.update(overrides)
    return payload


def op_record_end_payload(*, post_photo_ids: Optional[List[str]] = None,
                          **overrides: Any) -> Dict[str, Any]:
    """PRD §3.5: post_photo_ids is optional on the end action."""
    payload: Dict[str, Any] = {}
    if post_photo_ids is not None:
        payload["post_photo_ids"] = list(post_photo_ids)
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# FollowUp feedback (PRD §3.6)
# ---------------------------------------------------------------------------
def followup_feedback_payload(
    *,
    satisfaction: int = 5,
    symptoms: Optional[List[str]] = None,
    notes: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /aesthetics/followups/{id}/feedback per PRD §3.6."""
    payload: Dict[str, Any] = {"satisfaction": int(satisfaction)}
    if symptoms is not None:
        payload["symptoms"] = list(symptoms)
    if notes is not None:
        payload["notes"] = notes
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# AdverseEvent (PRD §3.6)
# ---------------------------------------------------------------------------
def file_adverse_event_payload(
    *,
    appointment_id: str,
    severity: str = "MINOR",
    description: str = "Test adverse event",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /aesthetics/adverse-events per PRD §3.6."""
    payload = {
        "appointment_id": appointment_id,
        "severity": severity,
        "description": description,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# InstallmentPlan (PRD §3.7)
# ---------------------------------------------------------------------------
def create_installment_payload(
    *,
    treatment_plan_id: str,
    downpayment_cents: int = 0,
    term_months: int = 6,
    finance_partner_id: str = "FP1",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /aesthetics/installments per PRD §3.7."""
    payload = {
        "treatment_plan_id": treatment_plan_id,
        "downpayment_cents": int(downpayment_cents),
        "term_months": int(term_months),
        "finance_partner_id": finance_partner_id,
    }
    payload.update(overrides)
    return payload


def installment_payment_payload(
    *,
    amount_cents: int,
    external_ref: str = "ref-001",
    prepay: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /aesthetics/installments/{id}/payments per PRD §3.7."""
    payload: Dict[str, Any] = {
        "amount_cents": int(amount_cents),
        "external_ref": external_ref,
    }
    if prepay is not None:
        payload["prepay"] = bool(prepay)
    payload.update(overrides)
    return payload


def refund_medical_event_payload(
    *,
    adverse_event_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {"adverse_event_id": adverse_event_id}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Test clock (PRD §2.10)
# ---------------------------------------------------------------------------
def clock_advance_payload(*, seconds: int, **overrides: Any) -> Dict[str, Any]:
    """POST /_clock/advance per PRD §2.10."""
    payload = {"seconds": int(seconds)}
    payload.update(overrides)
    return payload


__all__ = [
    "iso_utc",
    "utcnow",
    "iso_now",
    "iso_offset",
    "random_suffix",
    "dob_for_age",
    "create_project_payload",
    "patch_project_payload",
    "create_contraindication_rule_payload",
    "create_consumable_sku_payload",
    "create_room_payload",
    "create_customer_payload",
    "patch_customer_payload",
    "submit_kyc_payload",
    "create_plan_payload",
    "plan_item",
    "patch_plan_payload",
    "create_appointment_payload",
    "reschedule_appointment_payload",
    "op_record_key_step_payload",
    "op_record_consumables_payload",
    "op_record_vitals_payload",
    "op_record_incident_payload",
    "op_record_end_payload",
    "followup_feedback_payload",
    "file_adverse_event_payload",
    "create_installment_payload",
    "installment_payment_payload",
    "refund_medical_event_payload",
    "clock_advance_payload",
]
