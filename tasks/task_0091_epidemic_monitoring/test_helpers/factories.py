"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact schema the PRD declares for the request
body (PRD §3.1–§3.9). Tests pass overrides for the values they want
to control.
"""
from __future__ import annotations

import random
import string
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# ISO 8601 UTC timestamp helper used by /_clock/advance and tests.
# ---------------------------------------------------------------------------
def iso_utc(dt: datetime) -> str:
    """Render a datetime as ISO 8601 UTC with three fractional digits
    (PRD §2.4 timestamp format)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def iso_utc_midnight(dt: datetime) -> str:
    """Render a UTC date at 00:00:00.000Z (PRD §3.2 onset_date /
    §3.4 start_date / §3.9 bulletin_date format)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.strftime("%Y-%m-%dT%H:%M:%S") + ".000Z"


_alpha = string.ascii_lowercase + string.digits


def random_suffix(n: int = 6) -> str:
    return "".join(random.choices(_alpha, k=n))


def random_person_hash() -> str:
    """16 lowercase hex chars per PRD §3.1 person_hash format."""
    return "".join(random.choices("0123456789abcdef", k=16))


# ---------------------------------------------------------------------------
# Institution (PRD §3.1)
# ---------------------------------------------------------------------------
def create_institution_payload(
    institution_code: Optional[str] = None,
    institution_type: str = "HOSPITAL",
    district_code: str = "D-001",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "institution_code": institution_code or f"INST{random_suffix(6).upper()}",
        "institution_type": institution_type,
        "district_code": district_code,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Region (PRD §3.1)
# ---------------------------------------------------------------------------
def create_region_payload(
    district_code: str = "D-001",
    population: int = 100000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "district_code": district_code,
        "population": population,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Person (PRD §3.1)
# ---------------------------------------------------------------------------
def create_person_payload(
    person_hash: Optional[str] = None,
    demographics: Optional[Dict[str, Any]] = None,
    district_code: str = "D-001",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "person_hash": person_hash or random_person_hash(),
        "demographics": demographics or {
            "age_band": "30-39",
            "gender": "F",
            "occupation_category": "office",
        },
        "district_code": district_code,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# IsolationFacility (PRD §3.1)
# ---------------------------------------------------------------------------
def create_facility_payload(
    facility_code: Optional[str] = None,
    district_code: str = "D-001",
    capacity: int = 5,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "facility_code": facility_code or f"FAC{random_suffix(6).upper()}",
        "district_code": district_code,
        "capacity": capacity,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Case (PRD §3.2)
# ---------------------------------------------------------------------------
def create_case_payload(
    person_id: str,
    reporting_institution_id: str,
    case_type: str = "CONFIRMED",
    onset_date: Optional[str] = None,
    symptoms: Optional[List[str]] = None,
    exposure_history: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "person_id": person_id,
        "reporting_institution_id": reporting_institution_id,
        "case_type": case_type,
        "onset_date": onset_date or iso_utc_midnight(
            datetime.now(timezone.utc),
        ),
        "symptoms": symptoms if symptoms is not None else ["FEVER", "COUGH"],
    }
    if exposure_history is not None:
        payload["exposure_history"] = exposure_history
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ContactEvent (PRD §3.3)
# ---------------------------------------------------------------------------
def create_contact_event_payload(
    source_person_id: str,
    target_person_id: str,
    event_type: str = "HOUSEHOLD",
    event_time: Optional[str] = None,
    duration_minutes: int = 60,
    distance_meters: float = 1.0,
    ingested_from: str = "MANUAL",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "source_person_id": source_person_id,
        "target_person_id": target_person_id,
        "event_type": event_type,
        "event_time": event_time or iso_utc(datetime.now(timezone.utc)),
        "duration_minutes": duration_minutes,
        "distance_meters": distance_meters,
        "ingested_from": ingested_from,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# TracingTask (PRD §3.3)
# ---------------------------------------------------------------------------
def create_tracing_task_payload(
    case_id: str,
    assigned_cdc_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "case_id": case_id,
        "assigned_cdc_id": assigned_cdc_id,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Isolation (PRD §3.4)
# ---------------------------------------------------------------------------
def create_isolation_payload(
    person_id: str,
    mode: str = "HOME",
    facility_id: Optional[str] = None,
    start_date: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "person_id": person_id,
        "mode": mode,
        "start_date": start_date or iso_utc_midnight(
            datetime.now(timezone.utc),
        ),
    }
    if facility_id is not None:
        payload["facility_id"] = facility_id
    payload.update(overrides)
    return payload


def daily_report_payload(
    report_date: Optional[str] = None,
    temperature_c: float = 36.6,
    symptoms: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "report_date": report_date or iso_utc_midnight(
            datetime.now(timezone.utc),
        ),
        "temperature_c": temperature_c,
        "symptoms": symptoms if symptoms is not None else [],
    }
    payload.update(overrides)
    return payload


def violation_payload(reason: str = "Geofence breach", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# TestOrder (PRD §3.5)
# ---------------------------------------------------------------------------
def create_test_order_payload(
    person_id: str,
    ordering_institution_id: str,
    test_type: str = "PCR",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "person_id": person_id,
        "ordering_institution_id": ordering_institution_id,
        "test_type": test_type,
    }
    payload.update(overrides)
    return payload


def test_result_payload(result: str = "NEGATIVE", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"result": result}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# RiskTierDecision (PRD §3.6)
# ---------------------------------------------------------------------------
def create_risk_decision_payload(region_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"region_id": region_id}
    payload.update(overrides)
    return payload


def approve_risk_decision_payload(
    final_tier: str,
    expert_reviewer_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "final_tier": final_tier,
        "expert_reviewer_id": expert_reviewer_id,
    }
    payload.update(overrides)
    return payload


def reject_risk_decision_payload(expert_reviewer_id: str,
                                  **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"expert_reviewer_id": expert_reviewer_id}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Supply (PRD §3.7)
# ---------------------------------------------------------------------------
def create_supply_item_payload(
    sku: Optional[str] = None,
    category: str = "PPE",
    reserve_quantity: int = 100,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "sku": sku or f"SKU-{random_suffix(6).upper()}",
        "category": category,
        "reserve_quantity": reserve_quantity,
    }
    payload.update(overrides)
    return payload


def create_supply_request_payload(
    sku: str,
    requesting_institution_id: str,
    requested_quantity: int = 10,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "sku": sku,
        "requesting_institution_id": requesting_institution_id,
        "requested_quantity": requested_quantity,
    }
    payload.update(overrides)
    return payload


def dispatch_payload(quantity: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"quantity": quantity}
    payload.update(overrides)
    return payload


def allocate_batch_payload(sku: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"sku": sku}
    payload.update(overrides)
    return payload


def consume_payload(consumed_quantity: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"consumed_quantity": consumed_quantity}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Bulletin (PRD §3.9)
# ---------------------------------------------------------------------------
def create_bulletin_payload(
    bulletin_date: Optional[str] = None,
    channels: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "bulletin_date": bulletin_date or iso_utc_midnight(
            datetime.now(timezone.utc),
        ),
        "channels": channels if channels is not None else ["WEBSITE"],
    }
    payload.update(overrides)
    return payload


def retract_bulletin_payload(reason: Optional[str] = None,
                              **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Test-driver endpoints (PRD §2.9)
# ---------------------------------------------------------------------------
def clock_advance_payload(seconds: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"seconds": seconds}
    payload.update(overrides)
    return payload


def events_emit_payload(source: str, payload: Dict[str, Any],
                        **overrides: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {"source": source, "payload": payload}
    out.update(overrides)
    return out


__all__ = [
    "iso_utc",
    "iso_utc_midnight",
    "random_suffix",
    "random_person_hash",
    "create_institution_payload",
    "create_region_payload",
    "create_person_payload",
    "create_facility_payload",
    "create_case_payload",
    "create_contact_event_payload",
    "create_tracing_task_payload",
    "create_isolation_payload",
    "daily_report_payload",
    "violation_payload",
    "create_test_order_payload",
    "test_result_payload",
    "create_risk_decision_payload",
    "approve_risk_decision_payload",
    "reject_risk_decision_payload",
    "create_supply_item_payload",
    "create_supply_request_payload",
    "dispatch_payload",
    "allocate_batch_payload",
    "consume_payload",
    "create_bulletin_payload",
    "retract_bulletin_payload",
    "clock_advance_payload",
    "events_emit_payload",
]
