"""Payload factories — one factory per input-bearing endpoint.

Each factory emits ONLY the fields PRD §2 and §3 declare as input
(source: input) for the relevant endpoint. Tests override via kwargs.

Field names mirror PRD prose exactly — no abbreviation, no guessing.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional

from .constants import (
    DEFAULT_DEPARTMENT_CODE,
    DEFAULT_HOSPITAL_ID,
    DEFAULT_REGION_CODE,
    DEFAULT_DOCTOR_BASE_FEE,
    DEFAULT_ECOMMERCE_ID,
    DEFAULT_PHARMACY_ID,
    IN_SCOPE_DISEASE,
)


def unique_suffix() -> str:
    return uuid.uuid4().hex[:10]


# ---------------------------------------------------------------------------
# Patient (PRD §3.1, §4)
# ---------------------------------------------------------------------------
def create_patient_payload(
    *,
    full_name: Optional[str] = None,
    date_of_birth: str = "1990-01-15",
    region_code: str = DEFAULT_REGION_CODE,
    insurance_policy_no: Optional[str] = None,
    preferred_hospital_id: Optional[str] = None,
    preferred_doctor_id: Optional[str] = None,
    chronic_condition_codes: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'Creating a Patient requires the legal full_name, a
    date_of_birth formatted as an ISO 8601 calendar date (YYYY-MM-DD),
    and a region_code from the server-known region enumeration.'"""
    payload: Dict[str, Any] = {
        "full_name": full_name or f"Patient {unique_suffix()}",
        "date_of_birth": date_of_birth,
        "region_code": region_code,
    }
    if insurance_policy_no is not None:
        payload["insurance_policy_no"] = insurance_policy_no
    if preferred_hospital_id is not None:
        payload["preferred_hospital_id"] = preferred_hospital_id
    if preferred_doctor_id is not None:
        payload["preferred_doctor_id"] = preferred_doctor_id
    if chronic_condition_codes is not None:
        payload["chronic_condition_codes"] = chronic_condition_codes
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Doctor (PRD §3.1, §4)
# ---------------------------------------------------------------------------
def create_doctor_payload(
    *,
    full_name: Optional[str] = None,
    hospital_id: str = DEFAULT_HOSPITAL_ID,
    department_code: str = DEFAULT_DEPARTMENT_CODE,
    specialty_codes: Optional[List[str]] = None,
    licensed_region_codes: Optional[List[str]] = None,
    max_concurrent_sessions: Optional[int] = None,
    rating_score: Optional[float] = None,
    base_fee: Optional[float] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'Registering a Doctor ... provides the full_name, the
    hospital_id ..., the primary department_code ..., the list of
    sub-specialty_codes, and the list of licensed_region_codes ...'"""
    payload: Dict[str, Any] = {
        "full_name": full_name or f"Doctor {unique_suffix()}",
        "hospital_id": hospital_id,
        "department_code": department_code,
        "specialty_codes": (
            specialty_codes if specialty_codes is not None
            else [IN_SCOPE_DISEASE]
        ),
        "licensed_region_codes": (
            licensed_region_codes if licensed_region_codes is not None
            else [DEFAULT_REGION_CODE]
        ),
    }
    if max_concurrent_sessions is not None:
        payload["max_concurrent_sessions"] = max_concurrent_sessions
    if rating_score is not None:
        payload["rating_score"] = rating_score
    if base_fee is not None:
        # Some implementations expose base_fee at create time as an extra
        # input; tests treat it as optional/server-known on the doctor profile.
        payload["base_fee"] = base_fee
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Pharmacist (PRD §3.1, §4)
# ---------------------------------------------------------------------------
def create_pharmacist_payload(
    *,
    full_name: Optional[str] = None,
    license_number: Optional[str] = None,
    status: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'A Pharmacist is registered with a full_name, a
    server-unique license_number, and an optional status that defaults
    to ACTIVE.'"""
    payload: Dict[str, Any] = {
        "full_name": full_name or f"Pharmacist {unique_suffix()}",
        "license_number": license_number or f"LIC-{unique_suffix()}",
    }
    if status is not None:
        payload["status"] = status
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# DepartmentMapping (PRD §3.1, §4)
# ---------------------------------------------------------------------------
def create_department_mapping_payload(
    *,
    department_code: str = DEFAULT_DEPARTMENT_CODE,
    disease_codes: Optional[List[str]] = None,
    triage_priority: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'DepartmentMapping rows are registered ... with a
    department_code identifier ..., an array of disease_codes that route
    to that department, and a triage_priority integer.'"""
    payload: Dict[str, Any] = {
        "department_code": department_code,
        "disease_codes": (
            disease_codes if disease_codes is not None
            else [IN_SCOPE_DISEASE]
        ),
        "triage_priority": triage_priority,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# TriageSession (PRD §3.2, §4)
# ---------------------------------------------------------------------------
def make_questionnaire_response(
    *,
    question_code: str,
    answer_value: str = "YES",
    severity_weight: int = 1,
) -> Dict[str, Any]:
    """PRD §3.2: 'questionnaire_responses, an array of objects each
    carrying a question_code, an answer_value, and a severity_weight.'"""
    return {
        "question_code": question_code,
        "answer_value": answer_value,
        "severity_weight": severity_weight,
    }


def create_triage_session_payload(
    *,
    patient_id: str,
    questionnaire_responses: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.2: 'A Patient opens a triage session by submitting the
    patient_id and the initial questionnaire_responses.'"""
    payload: Dict[str, Any] = {
        "patient_id": patient_id,
        "questionnaire_responses": (
            questionnaire_responses if questionnaire_responses is not None
            else [make_questionnaire_response(
                question_code="CHEST_PAIN", answer_value="YES",
                severity_weight=2,
            )]
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Consultation (PRD §3.3 – §3.5, §4)
# ---------------------------------------------------------------------------
def create_consultation_payload(
    *,
    triage_session_id: str,
    mode: str = "REAL_TIME",
    media_type: str = "TEXT_IMAGE",
    scheduled_start_at: Optional[str] = None,
    doctor_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.3: 'the body carries the triage_session_id, the desired
    mode (REAL_TIME for queue-based or APPOINTMENT for slot-based), a
    media_type (TEXT_IMAGE or VIDEO), and -- for APPOINTMENT mode -- a
    scheduled_start_at timestamp.'"""
    payload: Dict[str, Any] = {
        "triage_session_id": triage_session_id,
        "mode": mode,
        "media_type": media_type,
    }
    if scheduled_start_at is not None:
        payload["scheduled_start_at"] = scheduled_start_at
    if doctor_id is not None:
        payload["doctor_id"] = doctor_id
    payload.update(overrides)
    return payload


def quality_report_payload(report_tier: str = "DEGRADED") -> Dict[str, Any]:
    """PRD §3.5 / §4: quality-report carries a report_tier."""
    return {"report_tier": report_tier}


def transfer_payload(*, target_doctor_id: str) -> Dict[str, Any]:
    """PRD §3.5: 'The body carries the target_doctor_id'."""
    return {"target_doctor_id": target_doctor_id}


def image_attachment_payload(attachment_id: str) -> Dict[str, Any]:
    """PRD §3.5 / §4: image-attachments stores an attachment_id."""
    return {"attachment_id": attachment_id}


# ---------------------------------------------------------------------------
# Prescription (PRD §3.6, §4)
# ---------------------------------------------------------------------------
def make_prescription_item(
    *,
    drug_code: Optional[str] = None,
    quantity: int = 1,
    unit_price_cents: int = 500,
    dosage_text: str = "1 tablet/day",
) -> Dict[str, Any]:
    """PRD §3.6: 'Each entry in items carries a drug_code, a quantity, a
    unit_price_cents, and a dosage_text.'"""
    return {
        "drug_code": drug_code or f"DRUG-{unique_suffix()}",
        "quantity": quantity,
        "unit_price_cents": unit_price_cents,
        "dosage_text": dosage_text,
    }


def create_prescription_payload(
    *,
    consultation_id: str,
    disease_codes: Optional[List[str]] = None,
    items: Optional[List[Dict[str, Any]]] = None,
    dispatch_target_kind: str = "PHARMACY",
    dispatch_target_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.6: 'The draft payload carries the parent consultation_id,
    the targeted disease_codes, the line-item array items, the
    dispatch_target_kind ... and the dispatch_target_id for the chosen
    vendor.'"""
    payload: Dict[str, Any] = {
        "consultation_id": consultation_id,
        "disease_codes": (
            disease_codes if disease_codes is not None
            else [IN_SCOPE_DISEASE]
        ),
        "items": items if items is not None else [make_prescription_item()],
        "dispatch_target_kind": dispatch_target_kind,
        "dispatch_target_id": (
            dispatch_target_id if dispatch_target_id is not None
            else (DEFAULT_PHARMACY_ID
                  if dispatch_target_kind == "PHARMACY"
                  else DEFAULT_ECOMMERCE_ID)
        ),
    }
    payload.update(overrides)
    return payload


def reject_prescription_payload(
    rejection_reason: str = "Dosage incorrect; please revise.",
) -> Dict[str, Any]:
    """PRD §3.6: 'Rejection -- which requires a non-null rejection_reason
    in the request body -- transitions status from UNDER_REVIEW to
    REJECTED.'"""
    return {"rejection_reason": rejection_reason}


def revise_prescription_payload(
    *,
    items: Optional[List[Dict[str, Any]]] = None,
    disease_codes: Optional[List[str]] = None,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """PRD §3.6: 'Revision may optionally replace items and disease_codes.'"""
    payload: Dict[str, Any] = {}
    if items is not None:
        payload["items"] = items
    if disease_codes is not None:
        payload["disease_codes"] = disease_codes
    if version is not None:
        payload["version"] = version
    return payload


# ---------------------------------------------------------------------------
# InsuranceClaim (PRD §3.7, §4)
# ---------------------------------------------------------------------------
def verify_eligibility_payload(
    insurance_status: str = "ELIGIBLE",
) -> Dict[str, Any]:
    """PRD §3.7: 'the call body carries the insurance_status returned by
    the bureau'."""
    return {"insurance_status": insurance_status}


# ---------------------------------------------------------------------------
# FollowUpTask (PRD §3.8, §4)
# ---------------------------------------------------------------------------
def create_follow_up_payload(
    *,
    consultation_id: str,
    plan_template_code: str = "GENERIC_WEEKLY",
    scheduled_reminder_at: str,
    reminder_channels: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.8: 'The payload carries the parent consultation_id, a
    plan_template_code ..., a scheduled_reminder_at server-clock instant,
    and a non-empty subset of reminder_channels.'"""
    payload: Dict[str, Any] = {
        "consultation_id": consultation_id,
        "plan_template_code": plan_template_code,
        "scheduled_reminder_at": scheduled_reminder_at,
        "reminder_channels": (
            reminder_channels if reminder_channels is not None
            else ["SMS"]
        ),
    }
    payload.update(overrides)
    return payload


def submit_form_payload(
    form_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """PRD §3.8: 'The patient then submits the follow-up form, providing
    form_payload.'"""
    return {
        "form_payload": (
            form_payload if form_payload is not None
            else {"severity": 1}
        )
    }


# ---------------------------------------------------------------------------
# Test-driving endpoints (PRD §3.9)
# ---------------------------------------------------------------------------
def emit_event_payload(kind: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """PRD §3.9 / §4: '_events/emit accepts a kind and a payload.'"""
    return {"kind": kind, "payload": payload}


__all__ = [
    "unique_suffix",
    "create_patient_payload",
    "create_doctor_payload",
    "create_pharmacist_payload",
    "create_department_mapping_payload",
    "make_questionnaire_response",
    "create_triage_session_payload",
    "create_consultation_payload",
    "quality_report_payload",
    "transfer_payload",
    "image_attachment_payload",
    "make_prescription_item",
    "create_prescription_payload",
    "reject_prescription_payload",
    "revise_prescription_payload",
    "verify_eligibility_payload",
    "create_follow_up_payload",
    "submit_form_payload",
    "emit_event_payload",
]
