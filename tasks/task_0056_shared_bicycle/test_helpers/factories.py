"""Payload factories — one factory per input-bearing endpoint.

Each factory emits ONLY the fields PRD §3/§4 declares as input
(source: input) for the relevant endpoint. Tests override via kwargs.

Field names mirror PRD prose exactly — no abbreviation, no guessing.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Unique-id / name helpers
# ---------------------------------------------------------------------------
def unique_suffix() -> str:
    return uuid.uuid4().hex[:10]


def unique_region_name(prefix: str = "Region") -> str:
    return f"{prefix}-{unique_suffix()}"


def unique_lock_id() -> str:
    return f"LOCK-{unique_suffix().upper()}"


def unique_rider_name(prefix: str = "Rider") -> str:
    return f"{prefix}-{unique_suffix()}"


def unique_geofence_label(prefix: str = "Fence") -> str:
    return f"{prefix}-{unique_suffix()}"


# ---------------------------------------------------------------------------
# Region  POST /regions  (PRD §3.1)
# ---------------------------------------------------------------------------
def create_region_payload(
    *,
    name: Optional[str] = None,
    deployment_quota: int = 50,
    low_density_threshold: int = 0,
    high_density_threshold: int = 999,
    in_zone_return_reward_cents: Optional[int] = None,
    out_of_zone_penalty_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'An admin sets it up by providing a unique name, a positive
    deployment_quota capping how many bikes may ever be ON_SHELF in the
    region at once, a non-negative low_density_threshold, a strictly larger
    high_density_threshold, and the two policy amounts that drive
    end-of-ride incentives: in_zone_return_reward_cents ... and
    out_of_zone_penalty_cents ... Both incentives default to 0 when the
    region is created without them.'"""
    payload: Dict[str, Any] = {
        "name": name or unique_region_name(),
        "deployment_quota": deployment_quota,
        "low_density_threshold": low_density_threshold,
        "high_density_threshold": high_density_threshold,
    }
    if in_zone_return_reward_cents is not None:
        payload["in_zone_return_reward_cents"] = in_zone_return_reward_cents
    if out_of_zone_penalty_cents is not None:
        payload["out_of_zone_penalty_cents"] = out_of_zone_penalty_cents
    payload.update(overrides)
    return payload


def patch_region_payload(
    *,
    deployment_quota: Optional[int] = None,
    low_density_threshold: Optional[int] = None,
    high_density_threshold: Optional[int] = None,
    in_zone_return_reward_cents: Optional[int] = None,
    out_of_zone_penalty_cents: Optional[int] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'Updates to thresholds, quota, or incentive amounts are
    accepted through the region-update capability described in §4 and may
    include an OCC version.'"""
    payload: Dict[str, Any] = {}
    if deployment_quota is not None:
        payload["deployment_quota"] = deployment_quota
    if low_density_threshold is not None:
        payload["low_density_threshold"] = low_density_threshold
    if high_density_threshold is not None:
        payload["high_density_threshold"] = high_density_threshold
    if in_zone_return_reward_cents is not None:
        payload["in_zone_return_reward_cents"] = in_zone_return_reward_cents
    if out_of_zone_penalty_cents is not None:
        payload["out_of_zone_penalty_cents"] = out_of_zone_penalty_cents
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Geofence  POST /regions/{region_id}/geofences  (PRD §3.1)
# ---------------------------------------------------------------------------
def make_square_polygon(
    *,
    center_lat: float = 30.0,
    center_lng: float = 120.0,
    side: float = 0.001,
) -> List[Dict[str, float]]:
    """Counter-clockwise 4-vertex polygon centred at (center_lat, center_lng).

    PRD §3.1: 'an ordered polygon of at least 3 and at most 32
    {lat, lng} vertices'.
    """
    h = side / 2.0
    return [
        {"lat": center_lat - h, "lng": center_lng - h},
        {"lat": center_lat - h, "lng": center_lng + h},
        {"lat": center_lat + h, "lng": center_lng + h},
        {"lat": center_lat + h, "lng": center_lng - h},
    ]


def create_geofence_payload(
    *,
    label: Optional[str] = None,
    kind: str = "ALLOWED_PARKING",
    polygon: Optional[List[Dict[str, float]]] = None,
    active: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'An admin defines a fence inside a specific region by
    providing a label, a kind (ALLOWED_PARKING, RESTRICTED, or FORBIDDEN),
    an ordered polygon of at least 3 and at most 32 {lat, lng} vertices,
    and an optional active flag (defaulting to true).'"""
    payload: Dict[str, Any] = {
        "label": label or unique_geofence_label(),
        "kind": kind,
        "polygon": polygon or make_square_polygon(),
    }
    if active is not None:
        payload["active"] = active
    payload.update(overrides)
    return payload


def patch_geofence_payload(
    *,
    polygon: Optional[List[Dict[str, float]]] = None,
    active: Optional[bool] = None,
    kind: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if polygon is not None:
        payload["polygon"] = polygon
    if active is not None:
        payload["active"] = active
    if kind is not None:
        payload["kind"] = kind
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Bike  POST /bikes  (PRD §3.2)
# ---------------------------------------------------------------------------
def create_bike_payload(
    *,
    model: str = "STANDARD",
    lock_id: Optional[str] = None,
    battery_pct: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.2: 'A bike is registered to the platform with its model
    (STANDARD or E_BIKE), its globally-unique lock_id, and an optional
    battery_pct.'"""
    payload: Dict[str, Any] = {
        "model": model,
        "lock_id": lock_id or unique_lock_id(),
    }
    if battery_pct is not None:
        payload["battery_pct"] = battery_pct
    payload.update(overrides)
    return payload


def patch_bike_payload(
    *,
    battery_pct: Optional[int] = None,
    last_lat: Optional[float] = None,
    last_lng: Optional[float] = None,
    lock_state: Optional[str] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if battery_pct is not None:
        payload["battery_pct"] = battery_pct
    if last_lat is not None:
        payload["last_lat"] = last_lat
    if last_lng is not None:
        payload["last_lng"] = last_lng
    if lock_state is not None:
        payload["lock_state"] = lock_state
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


def shelf_payload(*, action: str = "ON", **overrides: Any) -> Dict[str, Any]:
    """PRD §4: 'On-shelf or off-shelf workflow within a region' — action
    is 'ON' or 'OFF'."""
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


def bike_fault_report_payload(
    *,
    category: str = "FLAT_TIRE",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.5 (out-of-ride fault): 'Only category is supplied.'"""
    payload: Dict[str, Any] = {"category": category}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Rider  POST /riders  (PRD §3.3)
# ---------------------------------------------------------------------------
def create_rider_payload(
    *,
    name: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.3: 'Riders are registered with a display name.'"""
    payload: Dict[str, Any] = {"name": name or unique_rider_name()}
    payload.update(overrides)
    return payload


def wallet_credit_payload(
    *,
    amount_cents: int = 10000,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.3: 'Admin top-up credits an amount_cents directly into
    wallet_balance_cents.'"""
    payload: Dict[str, Any] = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def grant_free_minutes_payload(
    *,
    minutes: int = 10,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.3: 'Free-minute grant adds minutes to free_minutes_remaining.'"""
    payload: Dict[str, Any] = {"minutes": minutes}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Ride  POST /rides  (PRD §3.4)
# ---------------------------------------------------------------------------
def create_ride_payload(
    *,
    rider_id: str,
    bike_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.4: 'A rider initiates a ride by submitting a rider_id and a
    bike_id.'"""
    payload: Dict[str, Any] = {"rider_id": rider_id, "bike_id": bike_id}
    payload.update(overrides)
    return payload


def end_ride_payload(
    *,
    end_lat: float = 30.5,
    end_lng: float = 120.5,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.4: 'Locking up and ending the ride is the rider supplying an
    end_lat and end_lng.'"""
    payload: Dict[str, Any] = {"end_lat": end_lat, "end_lng": end_lng}
    payload.update(overrides)
    return payload


def ride_fault_report_payload(
    *,
    end_lat: float = 30.5,
    end_lng: float = 120.5,
    category: str = "FLAT_TIRE",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.5 (mid-ride fault): 'A rider who hits trouble in the middle
    of a ride reports it by providing end_lat, end_lng, and a fault
    category.'"""
    payload: Dict[str, Any] = {
        "end_lat": end_lat,
        "end_lng": end_lng,
        "category": category,
    }
    payload.update(overrides)
    return payload


def dispute_payload(
    *,
    reason: str = "Fare looks wrong",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.10: 'A rider who believes their fare was wrong opens a
    dispute on a SETTLED ride by submitting a reason.'"""
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


def adjust_payload(
    *,
    new_final_fare_cents: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.10: 'An admin resolves a dispute by submitting a
    new_final_fare_cents — the corrected total.'"""
    payload: Dict[str, Any] = {
        "new_final_fare_cents": new_final_fare_cents,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# WorkOrder  POST /workorders  (PRD §3.6)
# ---------------------------------------------------------------------------
def create_workorder_payload(
    *,
    bike_id: str,
    cause: str = "USER_REPORT",
    category: str = "FLAT_TIRE",
    sla_minutes: int = 240,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.6: 'providing the bike_id, the originating cause (one of
    USER_REPORT, LONG_STATIONARY, LOCK_ABNORMAL, LOW_BATTERY, or
    RECALL), a category, and an sla_minutes allowance.'"""
    payload: Dict[str, Any] = {
        "bike_id": bike_id,
        "cause": cause,
        "category": category,
        "sla_minutes": sla_minutes,
    }
    payload.update(overrides)
    return payload


def assign_workorder_payload(
    *,
    assigned_operator_id: str = "operator-assigned-001",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.6: 'An assigned_operator_id must be supplied — its absence
    yields ERR_OPERATOR_REQUIRED.'"""
    payload: Dict[str, Any] = {
        "assigned_operator_id": assigned_operator_id,
    }
    payload.update(overrides)
    return payload


def resolve_workorder_payload(
    *,
    resolution_note: str = "Repaired and back on shelf",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.6: 'a resolution_note is required at this point.'"""
    payload: Dict[str, Any] = {"resolution_note": resolution_note}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# TransferOrder  POST /transfers  (PRD §3.8)
# ---------------------------------------------------------------------------
def create_transfer_payload(
    *,
    from_region_id: str,
    to_region_id: str,
    bike_ids: List[str],
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.8: 'Planning a transfer requires the source and destination
    region ids as from_region_id and to_region_id, plus a non-empty
    ordered list of bike_ids to move.'"""
    payload: Dict[str, Any] = {
        "from_region_id": from_region_id,
        "to_region_id": to_region_id,
        "bike_ids": list(bike_ids),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# LossRecord  POST /loss-records  (PRD §3.11)
# ---------------------------------------------------------------------------
def create_loss_record_payload(
    *,
    bike_id: str,
    cause: str = "DAMAGE",
    responsibility: str = "UNKNOWN",
    responsible_party_id: Optional[str] = None,
    financial_impact_cents: int = 5000,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.11: 'an admin records the event by supplying a bike_id ...,
    a cause (one of THEFT, DAMAGE, ABANDONED), a responsibility
    attribution (one of RIDER, OPERATOR, UNKNOWN), an optional
    responsible_party_id ..., and a strictly positive
    financial_impact_cents.'"""
    payload: Dict[str, Any] = {
        "bike_id": bike_id,
        "cause": cause,
        "responsibility": responsibility,
        "financial_impact_cents": financial_impact_cents,
    }
    if responsible_party_id is not None:
        payload["responsible_party_id"] = responsible_party_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Test-driving payloads (PRD §2.6, §3.9, §3.12)
# ---------------------------------------------------------------------------
def clock_advance_payload(
    *, minutes: int = 1, **overrides: Any,
) -> Dict[str, Any]:
    """PRD §2.6: 'The clock-advance capability accepts a single
    non-negative integer minutes parameter.'"""
    payload: Dict[str, Any] = {"minutes": minutes}
    payload.update(overrides)
    return payload


def emit_event_payload(
    *,
    target_system: str = "payment",
    subject_type: str = "Ride",
    subject_id: str,
    payload: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.12: 'An admin-only test-driving emission capability accepts
    a target_system, subject_type, subject_id, and payload.'"""
    out: Dict[str, Any] = {
        "target_system": target_system,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "payload": payload or {},
    }
    out.update(overrides)
    return out


__all__ = [
    "unique_suffix",
    "unique_region_name",
    "unique_lock_id",
    "unique_rider_name",
    "unique_geofence_label",
    "make_square_polygon",
    "create_region_payload",
    "patch_region_payload",
    "create_geofence_payload",
    "patch_geofence_payload",
    "create_bike_payload",
    "patch_bike_payload",
    "shelf_payload",
    "bike_fault_report_payload",
    "create_rider_payload",
    "wallet_credit_payload",
    "grant_free_minutes_payload",
    "create_ride_payload",
    "end_ride_payload",
    "ride_fault_report_payload",
    "dispute_payload",
    "adjust_payload",
    "create_workorder_payload",
    "assign_workorder_payload",
    "resolve_workorder_payload",
    "create_transfer_payload",
    "create_loss_record_payload",
    "clock_advance_payload",
    "emit_event_payload",
]
