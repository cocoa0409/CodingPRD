"""Payload factories — one per entity, input fields only (PRD section 4)."""
import itertools
from typing import Any, Dict, List, Optional

from .constants import (
    DEFAULT_EVENT_DATE,
    DEFAULT_POINTS_SCHEME,
    SENIOR_ENTRY_FEE_CENTS,
    SENIOR_MAX_AGE,
    SENIOR_MIN_AGE,
    SENIOR_MIN_COMBINED_WEIGHT_KG,
)

__all__ = [
    "create_season_payload",
    "create_class_payload",
    "create_driver_payload",
    "create_kart_payload",
    "create_event_payload",
    "create_entry_payload",
    "create_inspection_payload",
    "create_session_payload",
    "create_result_row",
    "create_results_payload",
    "create_incident_payload",
    "create_adjudication_payload",
    "create_booking_payload",
]

_counter = itertools.count(1)


def _next() -> int:
    return next(_counter)


def create_season_payload(**overrides) -> Dict[str, Any]:
    """Season input fields: name, year, points_scheme; drop_rounds and
    fastest_lap_bonus_points are optional and included only when supplied."""
    payload: Dict[str, Any] = {
        "name": f"Season {_next()}",
        "year": 2026,
        "points_scheme": list(DEFAULT_POINTS_SCHEME),
    }
    payload.update(overrides)
    return payload


def create_class_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": "SENIOR",
        "min_age": SENIOR_MIN_AGE,
        "max_age": SENIOR_MAX_AGE,
        "min_combined_weight_kg": SENIOR_MIN_COMBINED_WEIGHT_KG,
        "entry_fee_cents": SENIOR_ENTRY_FEE_CENTS,
        "rental_kart_allowed": True,
    }
    payload.update(overrides)
    return payload


def create_driver_payload(**overrides) -> Dict[str, Any]:
    n = _next()
    payload: Dict[str, Any] = {
        "full_name": f"Driver {n}",
        "date_of_birth": "1990-01-01",
        "body_weight_kg": 80.0,
        "license_type": "OWNER",
    }
    payload.update(overrides)
    return payload


def create_kart_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "fleet_number": f"K-{_next()}",
        "eligible_class_codes": ["SENIOR"],
    }
    payload.update(overrides)
    return payload


def create_event_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "round_number": 1,
        "event_date": DEFAULT_EVENT_DATE,
        "track_name": "Club Circuit",
    }
    payload.update(overrides)
    return payload


def create_entry_payload(
    driver_id: str,
    class_id: str,
    entry_type: str = "OWNER_DRIVER",
    kart_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """kart_id is included only when supplied: PRD 3.3 requires a RENTAL entry
    to carry it and an OWNER_DRIVER entry to omit it."""
    payload: Dict[str, Any] = {
        "driver_id": driver_id,
        "class_id": class_id,
        "entry_type": entry_type,
    }
    if kart_id is not None:
        payload["kart_id"] = kart_id
    payload.update(overrides)
    return payload


def create_inspection_payload(
    measured_combined_weight_kg: float, notes: Optional[str] = None, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"measured_combined_weight_kg": measured_combined_weight_kg}
    if notes is not None:
        payload["notes"] = notes
    payload.update(overrides)
    return payload


def create_session_payload(
    session_type: str = "MAIN",
    sequence: int = 1,
    expected_event_version: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"session_type": session_type, "sequence": sequence}
    if expected_event_version is not None:
        payload["expected_event_version"] = expected_event_version
    payload.update(overrides)
    return payload


def create_result_row(
    entry_id: str,
    finish_position: int,
    best_lap_ms: int,
    total_time_ms: int,
) -> Dict[str, Any]:
    return {
        "entry_id": entry_id,
        "finish_position": finish_position,
        "best_lap_ms": best_lap_ms,
        "total_time_ms": total_time_ms,
    }


def create_results_payload(
    results: List[Dict[str, Any]], expected_session_version: Optional[int] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"results": results}
    if expected_session_version is not None:
        payload["expected_session_version"] = expected_session_version
    return payload


def create_incident_payload(
    entry_id: str,
    session_id: str,
    description: str = "On-track contact",
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "entry_id": entry_id,
        "session_id": session_id,
        "description": description,
    }
    payload.update(overrides)
    return payload


def create_adjudication_payload(
    decision: str,
    penalty_kind: Optional[str] = None,
    penalty_seconds: Optional[int] = None,
) -> Dict[str, Any]:
    """penalty_seconds is included only for TIME_SECONDS penalties: PRD 3.6
    requires it present and positive exactly when penalty_kind is TIME_SECONDS."""
    payload: Dict[str, Any] = {"decision": decision}
    if penalty_kind is not None:
        payload["penalty_kind"] = penalty_kind
    if penalty_seconds is not None:
        payload["penalty_seconds"] = penalty_seconds
    return payload


def create_booking_payload(
    driver_id: str,
    kart_id: str,
    start_time: str,
    end_time: str,
    pricing_mode: str = "FLAT",
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "driver_id": driver_id,
        "kart_id": kart_id,
        "start_time": start_time,
        "end_time": end_time,
        "pricing_mode": pricing_mode,
    }
    payload.update(overrides)
    return payload
