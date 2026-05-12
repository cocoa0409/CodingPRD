"""Payload factories — one per entity, input fields only.

Field names are PRD-exact (PRD §2.4, §3). Every factory accepts
**overrides so individual tests can pin the exact values needed for a
boundary or precondition.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Unique helpers
# ---------------------------------------------------------------------------
def unique_phone_e164() -> str:
    """E.164: leading +, then between 7 and 15 digits, first non-zero (PRD §3.1)."""
    suffix = uuid.uuid4().int % (10 ** 10)
    return f"+1{suffix:010d}"


def unique_email(prefix: str = "test") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def unique_drug_code(prefix: str = "DRUG") -> str:
    """^[A-Z][A-Z0-9_]{1,31}$ per PRD §3.7."""
    suffix = uuid.uuid4().hex[:10].upper()
    return f"{prefix}_{suffix}"


def unique_vaccine_code(prefix: str = "VACX") -> str:
    """^[A-Z][A-Z0-9_]{1,31}$ per PRD §3.3."""
    suffix = uuid.uuid4().hex[:8].upper()
    return f"{prefix}_{suffix}"


def unique_cage_code(prefix: str = "C") -> str:
    """^[A-Z][A-Z0-9-]{1,15}$ per PRD §3.8."""
    suffix = uuid.uuid4().hex[:8].upper()
    return f"{prefix}-{suffix}"


def unique_batch_id(prefix: str = "BATCH") -> str:
    """^[A-Z0-9-]{4,32}$ per PRD §3.3."""
    suffix = uuid.uuid4().hex[:8].upper()
    return f"{prefix}-{suffix}"


def unique_external_lab_ref(prefix: str = "LAB") -> str:
    """^[A-Z0-9-]{6,40}$ per PRD §3.6."""
    suffix = uuid.uuid4().hex[:8].upper()
    return f"{prefix}-{suffix}"


def unique_event_id(prefix: str = "evt") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def unique_diagnosis_code(prefix: str = "K") -> str:
    """^[A-Z][A-Z0-9.]{1,15}$ per PRD §3.5."""
    suffix = uuid.uuid4().hex[:6].upper()
    return f"{prefix}{suffix}"


# ---------------------------------------------------------------------------
# Owner (PRD §3.1)
# ---------------------------------------------------------------------------
def create_owner_payload(
    *,
    full_name: str = "Test Owner",
    phone_e164: Optional[str] = None,
    email: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": full_name,
        "phone_e164": phone_e164 or unique_phone_e164(),
        "email": email or unique_email(),
    }
    payload.update(overrides)
    return payload


def deposit_payload(*, amount_cents: int = 100_000, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def verify_contact_payload(*, code: str = "DUMMY", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"code": code}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Pet (PRD §3.2)
# ---------------------------------------------------------------------------
def create_pet_payload(
    *,
    owner_id: str,
    name: str = "Buddy",
    species: str = "DOG",
    birth_date: str = "2024-01-01",
    weight_kg: float = 10.0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "owner_id": owner_id,
        "name": name,
        "species": species,
        "birth_date": birth_date,
        "weight_kg": weight_kg,
    }
    payload.update(overrides)
    return payload


def update_pet_payload(**fields: Any) -> Dict[str, Any]:
    """PATCH /pets/{id} accepts weight_kg?, name?, version? (PRD §3.2)."""
    payload: Dict[str, Any] = {}
    payload.update(fields)
    return payload


# ---------------------------------------------------------------------------
# Vaccine schedules + records (PRD §3.3)
# ---------------------------------------------------------------------------
def create_vaccine_schedule_payload(
    *,
    species: str = "DOG",
    vaccine_code: Optional[str] = None,
    age_min_days: int = 84,
    booster_interval_days: Optional[int] = 365,
    required: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "species": species,
        "vaccine_code": vaccine_code or unique_vaccine_code(),
        "age_min_days": age_min_days,
        "required": required,
    }
    if booster_interval_days is not None:
        payload["booster_interval_days"] = booster_interval_days
    payload.update(overrides)
    return payload


def record_vaccination_payload(
    *,
    vaccine_code: str,
    administered_at: str,
    batch_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "vaccine_code": vaccine_code,
        "administered_at": administered_at,
        "batch_id": batch_id or unique_batch_id(),
    }
    payload.update(overrides)
    return payload


def vaccine_recall_payload(
    *,
    batch_id: str,
    vaccine_code: str,
    event_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "batch_id": batch_id,
        "vaccine_code": vaccine_code,
        "event_id": event_id or unique_event_id("evt-recall"),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Visit (PRD §3.4)
# ---------------------------------------------------------------------------
def create_visit_payload(
    *,
    symptom_text: str = "vomiting and lethargy",
    severity_score: int = 5,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "symptom_text": symptom_text,
        "severity_score": severity_score,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Treatment Records (PRD §3.5)
# ---------------------------------------------------------------------------
def create_treatment_record_payload(
    *,
    visit_id: str,
    consultation_notes: str = "Standard exam findings.",
    diagnosis_code: str = "K30",
    treatment_plan: str = "Rest and hydration; recheck in one week.",
    consent_recorded: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "visit_id": visit_id,
        "consultation_notes": consultation_notes,
        "diagnosis_code": diagnosis_code,
        "treatment_plan": treatment_plan,
        "consent_recorded": consent_recorded,
    }
    payload.update(overrides)
    return payload


def amend_treatment_record_payload(*, version: int, **overrides: Any) -> Dict[str, Any]:
    """PATCH /treatment-records/{id}: version is required for OCC (PRD §3.5, §2.4)."""
    payload: Dict[str, Any] = {"version": version}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Lab Reports (PRD §3.6)
# ---------------------------------------------------------------------------
def create_lab_report_payload(
    *,
    visit_id: str,
    test_items: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    if test_items is None:
        test_items = [
            {"code": "GLU", "name": "Glucose", "ref_low": 5.0, "ref_high": 10.0},
            {"code": "CRE", "name": "Creatinine", "ref_low": 0.5, "ref_high": 1.5},
        ]
    payload: Dict[str, Any] = {
        "visit_id": visit_id,
        "test_items": test_items,
    }
    payload.update(overrides)
    return payload


def collect_sample_payload(*, sample_collected_at: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"sample_collected_at": sample_collected_at}
    payload.update(overrides)
    return payload


def send_to_lab_payload(*, external_lab_ref: Optional[str] = None,
                        **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "external_lab_ref": external_lab_ref or unique_external_lab_ref(),
    }
    payload.update(overrides)
    return payload


def external_lab_result_payload(
    *,
    external_lab_ref: str,
    results: List[Dict[str, Any]],
    event_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "external_lab_ref": external_lab_ref,
        "results": results,
        "event_id": event_id or unique_event_id("evt-lab"),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Drugs (PRD §3.7)
# ---------------------------------------------------------------------------
def create_drug_payload(
    *,
    code: Optional[str] = None,
    name: str = "Test Drug",
    controlled: bool = False,
    dosage_min_mg_per_kg: float = 1.0,
    dosage_max_mg_per_kg: float = 10.0,
    interactions: Optional[List[Dict[str, Any]]] = None,
    stock_units: int = 1000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": code or unique_drug_code(),
        "name": name,
        "controlled": controlled,
        "dosage_min_mg_per_kg": dosage_min_mg_per_kg,
        "dosage_max_mg_per_kg": dosage_max_mg_per_kg,
        "interactions": interactions if interactions is not None else [],
        "stock_units": stock_units,
    }
    payload.update(overrides)
    return payload


def update_drug_payload(**fields: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(fields)
    return payload


# ---------------------------------------------------------------------------
# Prescriptions (PRD §3.7)
# ---------------------------------------------------------------------------
def make_prescription_item(
    *,
    drug_code: str,
    dose_mg_per_kg: float = 5.0,
    frequency_per_day: int = 2,
    duration_days: int = 5,
    units: int = 50,
) -> Dict[str, Any]:
    return {
        "drug_code": drug_code,
        "dose_mg_per_kg": dose_mg_per_kg,
        "frequency_per_day": frequency_per_day,
        "duration_days": duration_days,
        "units": units,
    }


def create_prescription_payload(
    *,
    visit_id: str,
    items: List[Dict[str, Any]],
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "visit_id": visit_id,
        "items": items,
    }
    payload.update(overrides)
    return payload


def reject_prescription_payload(
    *,
    rejection_reason: str = "Dosage too aggressive; please revise.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"rejection_reason": rejection_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Cages and Hospitalizations (PRD §3.8)
# ---------------------------------------------------------------------------
def create_cage_payload(
    *,
    cage_code: Optional[str] = None,
    ward_code: str = "GENERAL",
    capacity: int = 2,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "cage_code": cage_code or unique_cage_code(),
        "ward_code": ward_code,
        "capacity": capacity,
    }
    payload.update(overrides)
    return payload


def create_hospitalization_payload(
    *,
    visit_id: str,
    cage_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "visit_id": visit_id,
        "cage_id": cage_id,
    }
    payload.update(overrides)
    return payload


def care_log_payload(
    *,
    note: str = "Routine vitals normal.",
    treatment_executed: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "note": note,
        "treatment_executed": treatment_executed,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Bills (PRD §3.9)
# ---------------------------------------------------------------------------
def create_bill_payload(
    *,
    visit_id: str,
    package_code: Optional[str] = None,
    insurance_estimate_cents: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "visit_id": visit_id,
        "insurance_estimate_cents": insurance_estimate_cents,
    }
    if package_code is not None:
        payload["package_code"] = package_code
    payload.update(overrides)
    return payload


def payment_payload(
    *,
    bill_id: str,
    amount_cents: int,
    event_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "bill_id": bill_id,
        "amount_cents": amount_cents,
        "event_id": event_id or unique_event_id("evt-pay"),
    }
    payload.update(overrides)
    return payload


def refund_request_payload(
    *,
    amount_cents: int,
    reason: str = "goodwill refund",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "amount_cents": amount_cents,
        "reason": reason,
    }
    payload.update(overrides)
    return payload


def refund_confirm_payload(
    *,
    bill_id: str,
    amount_cents: int,
    event_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "bill_id": bill_id,
        "amount_cents": amount_cents,
        "event_id": event_id or unique_event_id("evt-rconf"),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Misc admin
# ---------------------------------------------------------------------------
def im_emit_payload(
    *,
    recipient_owner_id: str,
    kind: str = "GENERIC",
    payload: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "recipient_owner_id": recipient_owner_id,
        "kind": kind,
        "payload": payload or {},
    }
    body.update(overrides)
    return body


def advance_clock_payload(*, seconds: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"seconds": seconds}
    payload.update(overrides)
    return payload


__all__ = [
    "unique_phone_e164",
    "unique_email",
    "unique_drug_code",
    "unique_vaccine_code",
    "unique_cage_code",
    "unique_batch_id",
    "unique_external_lab_ref",
    "unique_event_id",
    "unique_diagnosis_code",
    "create_owner_payload",
    "deposit_payload",
    "verify_contact_payload",
    "create_pet_payload",
    "update_pet_payload",
    "create_vaccine_schedule_payload",
    "record_vaccination_payload",
    "vaccine_recall_payload",
    "create_visit_payload",
    "create_treatment_record_payload",
    "amend_treatment_record_payload",
    "create_lab_report_payload",
    "collect_sample_payload",
    "send_to_lab_payload",
    "external_lab_result_payload",
    "create_drug_payload",
    "update_drug_payload",
    "make_prescription_item",
    "create_prescription_payload",
    "reject_prescription_payload",
    "create_cage_payload",
    "create_hospitalization_payload",
    "care_log_payload",
    "create_bill_payload",
    "payment_payload",
    "refund_request_payload",
    "refund_confirm_payload",
    "im_emit_payload",
    "advance_clock_payload",
]
