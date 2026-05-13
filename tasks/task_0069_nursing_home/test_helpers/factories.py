"""Payload factories — one per endpoint that accepts a body.

Each factory emits the exact field names declared by the PRD §4 endpoint
table; defaults are chosen so the request will satisfy the PRD's
preconditions unless the test overrides them.
"""
from __future__ import annotations
import itertools
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Unique-suffix helpers (avoid id-card / room-number collisions across tests)
# ---------------------------------------------------------------------------
_counter = itertools.count(int(time.time() * 1000))


def unique_suffix() -> str:
    return f"{next(_counter):x}"


def unique_id_card() -> str:
    return f"ID-{unique_suffix()}"


def unique_room_number() -> str:
    return f"R-{unique_suffix()}"


def unique_bed_code() -> str:
    return f"B-{unique_suffix()}"


def unique_drug_code() -> str:
    return f"DRG-{unique_suffix()}"


def unique_payment_ref() -> str:
    return f"PAY-{unique_suffix()}"


def unique_idempotency_key() -> str:
    return f"IDEM-{unique_suffix()}"


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def iso_z(dt: datetime) -> str:
    """ISO 8601 UTC with milliseconds (PRD §2.4)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") \
        + f"{dt.microsecond // 1000:03d}Z"


def future_iso(seconds_ahead: int = 3600) -> str:
    return iso_z(datetime.now(timezone.utc) + timedelta(seconds=seconds_ahead))


def future_iso_hours(hours_ahead: int = 1) -> str:
    return future_iso(hours_ahead * 3600)


# ---------------------------------------------------------------------------
# Elder
# ---------------------------------------------------------------------------
def emergency_contact(name: str = "Adult Child",
                      relation: str = "CHILD",
                      phone: str = "555-1234") -> Dict[str, Any]:
    return {"name": name, "relation": relation, "phone": phone}


def create_elder_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: elder profile carrying full_name, date_of_birth, gender,
    id_card_number, and structured arrays plus advance_directive."""
    defaults: Dict[str, Any] = {
        "full_name": f"Elder {unique_suffix()}",
        "date_of_birth": "1940-01-01",
        "gender": "F",
        "id_card_number": unique_id_card(),
        "medical_history": [],
        "allergies": [],
        "dietary_requirements": [],
        "emergency_contacts": [emergency_contact()],
    }
    defaults.update(overrides)
    return defaults


def update_elder_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def deposit_payload(amount_cents: int,
                    external_payment_ref: Optional[str] = None,
                    **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"amount_cents": amount_cents}
    if external_payment_ref is not None:
        payload["external_payment_ref"] = external_payment_ref
    payload.update(overrides)
    return payload


def admit_payload(bed_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {"bed_id": bed_id}
    payload.update(overrides)
    return payload


def transfer_payload(target_bed_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {"target_bed_id": target_bed_id}
    payload.update(overrides)
    return payload


def leave_payload(reason: Optional[str] = None,
                  **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Room / Bed
# ---------------------------------------------------------------------------
def create_room_payload(**overrides: Any) -> Dict[str, Any]:
    defaults = {
        "room_number": unique_room_number(),
        "floor": 1,
        "room_type": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_bed_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.8 — bed input fields are bed_code, bed_type, monthly_bed_fee_cents."""
    defaults = {
        "bed_code": unique_bed_code(),
        "bed_type": "SINGLE",
        "monthly_bed_fee_cents": 60_000,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Waitlist
# ---------------------------------------------------------------------------
def create_waitlist_payload(elder_id: str,
                            requested_bed_type: str = "SINGLE",
                            **overrides: Any) -> Dict[str, Any]:
    payload = {"elder_id": elder_id,
               "requested_bed_type": requested_bed_type}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Care Assessments
# ---------------------------------------------------------------------------
def create_assessment_payload(adl_score: int = 80,
                              cognitive_score: int = 10,
                              medical_condition_score: int = 20,
                              **overrides: Any) -> Dict[str, Any]:
    """PRD §3.2 — three sub-scores; composite + classification are computed
    server-side on submit."""
    payload = {
        "adl_score": adl_score,
        "cognitive_score": cognitive_score,
        "medical_condition_score": medical_condition_score,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Care Plans
# ---------------------------------------------------------------------------
def daily_task(task_type: str = "BATHING",
               frequency_per_day: int = 1,
               notes: str = "") -> Dict[str, Any]:
    return {
        "task_type": task_type,
        "frequency_per_day": frequency_per_day,
        "notes": notes,
    }


def create_care_plan_payload(based_on_assessment_id: str,
                             daily_tasks: Optional[List[Dict[str, Any]]] = None,
                             **overrides: Any) -> Dict[str, Any]:
    payload = {
        "based_on_assessment_id": based_on_assessment_id,
        "daily_tasks": daily_tasks if daily_tasks is not None else [daily_task()],
    }
    payload.update(overrides)
    return payload


def supersede_payload(new_plan_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {"new_plan_id": new_plan_id}
    payload.update(overrides)
    return payload


def task_execution_payload(task_type: str = "BATHING",
                           scheduled_for: Optional[str] = None,
                           outcome: str = "COMPLETED",
                           notes: Optional[str] = None,
                           **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "task_type": task_type,
        "scheduled_for": scheduled_for or future_iso(0),
        "outcome": outcome,
    }
    if notes is not None:
        payload["notes"] = notes
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Prescriptions / Medication
# ---------------------------------------------------------------------------
def create_prescription_payload(drug_code: Optional[str] = None,
                                drug_name: str = "Aspirin",
                                is_controlled_substance: bool = False,
                                contraindicated_allergens: Optional[List[str]] = None,
                                interacts_with_drug_codes: Optional[List[str]] = None,
                                dose_mg: float = 100.0,
                                frequency_per_day: int = 2,
                                starts_on: Optional[str] = None,
                                ends_on: Optional[str] = None,
                                **overrides: Any) -> Dict[str, Any]:
    today = datetime.now(timezone.utc).date()
    payload = {
        "drug_code": drug_code or unique_drug_code(),
        "drug_name": drug_name,
        "is_controlled_substance": is_controlled_substance,
        "contraindicated_allergens": contraindicated_allergens or [],
        "interacts_with_drug_codes": interacts_with_drug_codes or [],
        "dose_mg": dose_mg,
        "frequency_per_day": frequency_per_day,
        "starts_on": starts_on or today.isoformat(),
        "ends_on": ends_on or (today + timedelta(days=7)).isoformat(),
    }
    payload.update(overrides)
    return payload


def administration_payload(scheduled_slot_at: str,
                           outcome: str = "ADMINISTERED",
                           witness_id: Optional[str] = None,
                           **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "scheduled_slot_at": scheduled_slot_at,
        "outcome": outcome,
    }
    if witness_id is not None:
        payload["witness_id"] = witness_id
    payload.update(overrides)
    return payload


def medication_error_payload(elder_id: str,
                             error_type: str = "OTHER",
                             severity: str = "MINOR",
                             description: str = "Freestanding error report",
                             administration_id: Optional[str] = None,
                             prescription_id: Optional[str] = None,
                             **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "elder_id": elder_id,
        "error_type": error_type,
        "severity": severity,
        "description": description,
    }
    if administration_id is not None:
        payload["administration_id"] = administration_id
    if prescription_id is not None:
        payload["prescription_id"] = prescription_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Visit Reservation / Epidemic
# ---------------------------------------------------------------------------
def health_screening_payload(temperature_c: float = 36.6,
                             symptoms: Optional[List[str]] = None,
                             recent_exposure: bool = False) -> Dict[str, Any]:
    return {
        "temperature_c": temperature_c,
        "symptoms": symptoms if symptoms is not None else [],
        "recent_exposure": recent_exposure,
    }


def create_visit_reservation_payload(slot_start_at: str,
                                     slot_end_at: str,
                                     visitor_name: str = "Visitor",
                                     visitor_id_number: Optional[str] = None,
                                     visitor_relation: str = "CHILD",
                                     **overrides: Any) -> Dict[str, Any]:
    payload = {
        "visitor_name": visitor_name,
        "visitor_id_number": visitor_id_number or f"VID-{unique_suffix()}",
        "visitor_relation": visitor_relation,
        "slot_start_at": slot_start_at,
        "slot_end_at": slot_end_at,
    }
    payload.update(overrides)
    return payload


def check_in_payload(visitor_id_number: str,
                     temperature_c: float = 36.6,
                     symptoms: Optional[List[str]] = None,
                     recent_exposure: bool = False,
                     **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "visitor_id_number": visitor_id_number,
        "health_screening": health_screening_payload(
            temperature_c=temperature_c,
            symptoms=symptoms,
            recent_exposure=recent_exposure,
        ),
    }
    payload.update(overrides)
    return payload


def epidemic_config_payload(mode: str = "NORMAL",
                            max_temperature_c: Optional[float] = None,
                            max_visitors_per_day: Optional[int] = None,
                            **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"mode": mode}
    if max_temperature_c is not None:
        payload["max_temperature_c"] = max_temperature_c
    if max_visitors_per_day is not None:
        payload["max_visitors_per_day"] = max_visitors_per_day
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Billing
# ---------------------------------------------------------------------------
def create_bill_payload(cycle_start_date: str,
                        cycle_end_date: str,
                        billing_mode: str = "PACKAGE",
                        **overrides: Any) -> Dict[str, Any]:
    payload = {
        "cycle_start_date": cycle_start_date,
        "cycle_end_date": cycle_end_date,
        "billing_mode": billing_mode,
    }
    payload.update(overrides)
    return payload


def pay_bill_payload(external_payment_ref: Optional[str] = None,
                     **overrides: Any) -> Dict[str, Any]:
    payload = {
        "external_payment_ref": external_payment_ref or unique_payment_ref(),
    }
    payload.update(overrides)
    return payload


def adjust_bill_payload(adjustment_reason: str,
                        override_amount_due_cents: int,
                        **overrides: Any) -> Dict[str, Any]:
    payload = {
        "adjustment_reason": adjustment_reason,
        "override_amount_due_cents": override_amount_due_cents,
    }
    payload.update(overrides)
    return payload


def refund_payload(refund_amount_cents: int,
                   reason: str = "duplicate billing",
                   **overrides: Any) -> Dict[str, Any]:
    payload = {
        "refund_amount_cents": refund_amount_cents,
        "reason": reason,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# External events / operational
# ---------------------------------------------------------------------------
def external_event_payload(source: str,
                           event_type: str,
                           payload: Dict[str, Any],
                           idempotency_key: Optional[str] = None,
                           **overrides: Any) -> Dict[str, Any]:
    body = {
        "source": source,
        "idempotency_key": idempotency_key or unique_idempotency_key(),
        "event_type": event_type,
        "payload": payload,
    }
    body.update(overrides)
    return body


def clock_payload(seconds: int) -> Dict[str, Any]:
    return {"seconds": seconds}


__all__ = [
    "unique_suffix", "unique_id_card", "unique_room_number",
    "unique_bed_code", "unique_drug_code", "unique_payment_ref",
    "unique_idempotency_key",
    "iso_z", "future_iso", "future_iso_hours",
    "emergency_contact",
    "create_elder_payload", "update_elder_payload", "deposit_payload",
    "admit_payload", "transfer_payload", "leave_payload",
    "create_room_payload", "create_bed_payload",
    "create_waitlist_payload",
    "create_assessment_payload",
    "daily_task", "create_care_plan_payload", "supersede_payload",
    "task_execution_payload",
    "create_prescription_payload", "administration_payload",
    "medication_error_payload",
    "health_screening_payload", "create_visit_reservation_payload",
    "check_in_payload", "epidemic_config_payload",
    "create_bill_payload", "pay_bill_payload",
    "adjust_bill_payload", "refund_payload",
    "external_event_payload", "clock_payload",
]
