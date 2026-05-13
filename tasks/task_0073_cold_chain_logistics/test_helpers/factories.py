"""Payload factories — one per entity, INPUT fields only.

Field names exactly mirror the PRD; tests should not invent
abbreviations. Each factory takes **overrides so a test can pin the
single value it cares about and let the defaults handle the rest.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


# ===========================================================================
# Unique identifier helpers
# ===========================================================================
def unique_suffix(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def unique_vehicle_no() -> str:
    return f"V-{uuid.uuid4().hex[:10].upper()}"


def unique_license_no() -> str:
    return f"L-{uuid.uuid4().hex[:10].upper()}"


def unique_idempotency_key() -> str:
    return f"idem-{uuid.uuid4().hex}"


def unique_party_id(role: str) -> str:
    return f"{role.lower()}-{uuid.uuid4().hex[:10]}"


def iso_utc(dt: datetime) -> str:
    """ISO 8601 UTC with millisecond precision (PRD §2.7)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ===========================================================================
# Vehicle / Driver
# ===========================================================================
def create_vehicle_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: 'A CARRIER creates a Vehicle by submitting vehicle_no,
    compartment_count, and insured_cap_cents.'"""
    defaults = {
        "vehicle_no": unique_vehicle_no(),
        "compartment_count": 2,
        "insured_cap_cents": 1_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_driver_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: 'A CARRIER registers each driver with license_no, name,
    and an optional max_daily_minutes.'"""
    defaults = {
        "license_no": unique_license_no(),
        "name": "Test Driver",
        # max_daily_minutes intentionally omitted to exercise default 660.
    }
    defaults.update(overrides)
    return defaults


# ===========================================================================
# TransportTask
# ===========================================================================
def _default_stops(start: datetime,
                   n_stops: int = 2) -> List[Dict[str, Any]]:
    """At least 2 stops (PRD §3.3); first sequence=1, planned_arrival_at
    strictly increasing (PRD §3.2)."""
    stops: List[Dict[str, Any]] = []
    for i in range(n_stops):
        arrival = start + timedelta(seconds=600 * (i + 1))
        stops.append({
            "sequence": i + 1,
            "location_label": f"Stop {i + 1}",
            "planned_arrival_at": iso_utc(arrival),
            "handover_required": True,
        })
    return stops


def create_transport_task_payload(
    *,
    shipper_id: str,
    carrier_id: str,
    consignee_id: str,
    planned_start_at: Optional[datetime] = None,
    duration_seconds: int = 3600,
    n_stops: int = 2,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.2 task creation payload.

    PRD §3.2: 'The cargo profile is cargo_type ... cargo_value_cents
    ... cargo_quantity. The temperature envelope is given by
    temp_min_celsius and temp_max_celsius. The parties are shipper_id,
    consignee_id, and carrier_id. The schedule is planned_start_at and
    planned_end_at. The sensor cadence is polling_interval_seconds.'"""
    if planned_start_at is None:
        planned_start_at = datetime(2030, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    planned_end_at = planned_start_at + timedelta(seconds=duration_seconds)
    stops = overrides.pop(
        "stops", _default_stops(planned_start_at, n_stops),
    )
    defaults: Dict[str, Any] = {
        "cargo_type": "FOOD",
        "cargo_value_cents": 1_000_000,
        "cargo_quantity": 100,
        "temp_min_celsius": -5.00,
        "temp_max_celsius": 8.00,
        "shipper_id": shipper_id,
        "consignee_id": consignee_id,
        "carrier_id": carrier_id,
        "planned_start_at": iso_utc(planned_start_at),
        "planned_end_at": iso_utc(planned_end_at),
        "polling_interval_seconds": 60,
        "stops": stops,
    }
    defaults.update(overrides)
    return defaults


def patch_transport_task_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §4: PATCH input keys include vehicle_id?, driver_id?,
    polling_interval_seconds?, version."""
    return dict(overrides)


# ===========================================================================
# Temperature reading
# ===========================================================================
def temperature_reading_payload(
    *,
    captured_at: datetime,
    temperature_celsius: float = 5.00,
    sensor_kind: str = "COMPARTMENT",
    sensor_id: Optional[str] = None,
    gps_lat: float = 39.9042,
    gps_lng: float = 116.4074,
    idempotency_key: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.5 reading payload."""
    defaults: Dict[str, Any] = {
        "sensor_id": sensor_id or f"sensor-{uuid.uuid4().hex[:8]}",
        "sensor_kind": sensor_kind,
        "temperature_celsius": temperature_celsius,
        "gps_lat": gps_lat,
        "gps_lng": gps_lng,
        "captured_at": iso_utc(captured_at),
        "idempotency_key": idempotency_key or unique_idempotency_key(),
    }
    defaults.update(overrides)
    return defaults


# ===========================================================================
# Alerts — response actions
# ===========================================================================
def response_action_payload(
    action_kind: str = "VENTILATION",
    *,
    notes: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.7: 'The action payload supplies action_kind ... and an
    optional notes field of zero to five hundred characters.'"""
    defaults: Dict[str, Any] = {"action_kind": action_kind}
    if notes is not None:
        defaults["notes"] = notes
    defaults.update(overrides)
    return defaults


# ===========================================================================
# Handover
# ===========================================================================
def handover_payload(
    *,
    from_party_id: str,
    to_party_id: str,
    temperature_at_handover_celsius: float = 5.00,
    quantity_attested: int = 100,
    photo_evidence_ref: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "from_party_id": from_party_id,
        "to_party_id": to_party_id,
        "temperature_at_handover_celsius": temperature_at_handover_celsius,
        "quantity_attested": quantity_attested,
        "photo_evidence_ref": photo_evidence_ref or f"photo-{uuid.uuid4().hex[:12]}",
    }
    defaults.update(overrides)
    return defaults


# ===========================================================================
# DamageAssessment
# ===========================================================================
def create_damage_assessment_payload(
    *,
    task_id: str,
    evidence_alert_ids: List[str],
    damaged_quantity: int = 5,
    damage_class: str = "MODERATE",
    salvage_pct: float = 0.10,
    cause_primary: str = "TEMPERATURE_DEVIATION",
    variant: str = "INSURED_VALUE",
    invoice_unit_value_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.9 assessment creation payload."""
    defaults: Dict[str, Any] = {
        "task_id": task_id,
        "damaged_quantity": damaged_quantity,
        "damage_class": damage_class,
        "salvage_pct": salvage_pct,
        "cause_primary": cause_primary,
        "evidence_alert_ids": list(evidence_alert_ids),
        "variant": variant,
    }
    if invoice_unit_value_cents is not None:
        defaults["invoice_unit_value_cents"] = invoice_unit_value_cents
    defaults.update(overrides)
    return defaults


def patch_damage_assessment_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §4 PATCH input."""
    return dict(overrides)


# ===========================================================================
# ResponsibilityDecision
# ===========================================================================
def create_responsibility_decision_payload(
    *,
    task_id: str,
    assessment_id: str,
    shipper_pct: float = 0.30,
    carrier_pct: float = 0.50,
    consignee_pct: float = 0.20,
    split_method: str = "DURATION_WEIGHTED",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.10 decision creation payload."""
    defaults: Dict[str, Any] = {
        "task_id": task_id,
        "assessment_id": assessment_id,
        "shipper_pct": shipper_pct,
        "carrier_pct": carrier_pct,
        "consignee_pct": consignee_pct,
        "split_method": split_method,
    }
    defaults.update(overrides)
    return defaults


def patch_responsibility_decision_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §4 PATCH input (shipper_pct?, carrier_pct?, consignee_pct?,
    split_method?, version)."""
    return dict(overrides)


def dispute_payload(reason: str = "Testing dispute path") -> Dict[str, Any]:
    return {"reason": reason}


# ===========================================================================
# InsuranceClaim
# ===========================================================================
def create_insurance_claim_payload(
    *,
    task_id: str,
    decision_id: str,
    requested_amount_cents: int = 1000,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.11 claim report payload."""
    defaults: Dict[str, Any] = {
        "task_id": task_id,
        "decision_id": decision_id,
        "requested_amount_cents": requested_amount_cents,
    }
    defaults.update(overrides)
    return defaults


def assess_claim_payload(assessed_amount_cents: int) -> Dict[str, Any]:
    return {"assessed_amount_cents": assessed_amount_cents}


def subrogate_payload(subrogation_recovered_cents: int) -> Dict[str, Any]:
    return {"subrogation_recovered_cents": subrogation_recovered_cents}


def reject_claim_payload(reason: str = "test reject") -> Dict[str, Any]:
    return {"reason": reason}


# ===========================================================================
# ComplianceReport
# ===========================================================================
def create_compliance_report_payload(
    *,
    regulatory_domain: str = "FOOD",
    period_start: datetime,
    period_end: datetime,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.12 report creation payload."""
    defaults: Dict[str, Any] = {
        "regulatory_domain": regulatory_domain,
        "period_start": iso_utc(period_start),
        "period_end": iso_utc(period_end),
    }
    defaults.update(overrides)
    return defaults


# ===========================================================================
# Misc
# ===========================================================================
def clock_advance_payload(seconds: int) -> Dict[str, Any]:
    return {"seconds": seconds}


def abort_payload(reason: str = "test abort") -> Dict[str, Any]:
    return {"reason": reason}


__all__ = [
    "unique_suffix", "unique_vehicle_no", "unique_license_no",
    "unique_idempotency_key", "unique_party_id", "iso_utc",
    "create_vehicle_payload", "create_driver_payload",
    "create_transport_task_payload", "patch_transport_task_payload",
    "temperature_reading_payload", "response_action_payload",
    "handover_payload",
    "create_damage_assessment_payload", "patch_damage_assessment_payload",
    "create_responsibility_decision_payload",
    "patch_responsibility_decision_payload", "dispute_payload",
    "create_insurance_claim_payload", "assess_claim_payload",
    "subrogate_payload", "reject_claim_payload",
    "create_compliance_report_payload",
    "clock_advance_payload", "abort_payload",
]
