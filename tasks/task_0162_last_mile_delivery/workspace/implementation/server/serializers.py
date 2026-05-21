"""Serializers convert in-memory entity dicts to JSON-safe payloads."""
from decimal import Decimal
from typing import Any, Dict

from . import store
from .services.calculations import dec2


def _money(v: Any):
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(dec2(v))
    return float(dec2(Decimal(str(v))))


def _km(v: Any):
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(dec2(v))
    return float(dec2(Decimal(str(v))))


def serialize_customer(c: dict) -> Dict[str, Any]:
    # Recompute the rolling 30-day count on read.
    from .services.rolling import recompute_customer_rolling
    recompute_customer_rolling(c)
    return {
        "id": c["id"],
        "email": c.get("email"),
        "full_name": c.get("full_name"),
        "phone": c.get("phone"),
        "default_address_id": c.get("default_address_id"),
        "driver_release_authorized": bool(c.get("driver_release_authorized", False)),
        "redelivery_attempts_used_30d": int(c.get("redelivery_attempts_used_30d", 0)),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_address(a: dict) -> Dict[str, Any]:
    return {
        "id": a["id"],
        "customer_id": a["customer_id"],
        "line1": a.get("line1"),
        "city": a.get("city"),
        "postal_code": a.get("postal_code"),
        "latitude": a.get("latitude"),
        "longitude": a.get("longitude"),
        "residential": bool(a.get("residential", True)),
        "created_at": a["created_at"],
    }


def serialize_transit_center(tc: dict) -> Dict[str, Any]:
    return {
        "id": tc["id"],
        "code": tc.get("code"),
        "serviced_postal_prefixes": list(tc.get("serviced_postal_prefixes", [])),
        "hazmat_certified": bool(tc.get("hazmat_certified", False)),
        "parcels_on_belt": int(tc.get("parcels_on_belt", 0)),
        "latitude": tc.get("latitude"),
        "longitude": tc.get("longitude"),
        "created_at": tc["created_at"],
        "updated_at": tc["updated_at"],
        "version": tc["version"],
    }


def serialize_driver(d: dict) -> Dict[str, Any]:
    return {
        "id": d["id"],
        "badge_id": d.get("badge_id"),
        "home_center_id": d.get("home_center_id"),
        "hazmat_endorsement": bool(d.get("hazmat_endorsement", False)),
        "status": d.get("status", "OFF_DUTY"),
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def serialize_parcel(p: dict) -> Dict[str, Any]:
    return {
        "id": p["id"],
        "tracking_number": p["tracking_number"],
        "customer_id": p["customer_id"],
        "destination_address_id": p.get("destination_address_id"),
        "origin_center_id": p["origin_center_id"],
        "weight_kg": float(p["weight_kg"]),
        "declared_value": _money(p["declared_value"]),
        "signature_required": bool(p.get("signature_required", False)),
        "hazmat_class": p.get("hazmat_class", "NONE"),
        "time_window_start": p["time_window_start"],
        "time_window_end": p["time_window_end"],
        "status": p["status"],
        "redelivery_attempts": int(p.get("redelivery_attempts", 0)),
        "quoted_fee": _money(p.get("quoted_fee", 0)),
        "final_fee": _money(p["final_fee"]) if p.get("final_fee") is not None else None,
        "last_attempt_outcome": p.get("last_attempt_outcome", "NONE"),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_route(r: dict) -> Dict[str, Any]:
    return {
        "id": r["id"],
        "center_id": r["center_id"],
        "driver_id": r["driver_id"],
        "planned_date": r["planned_date"],
        "status": r["status"],
        "total_distance_km": _km(r.get("total_distance_km", 0)),
        "stop_count": int(r.get("stop_count", 0)),
        "hazmat_present": bool(r.get("hazmat_present", False)),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_route_stop(s: dict) -> Dict[str, Any]:
    return {
        "id": s["id"],
        "route_id": s["route_id"],
        "parcel_id": s["parcel_id"],
        "sequence": int(s["sequence"]),
        "planned_arrival": s.get("planned_arrival"),
        "planned_departure": s.get("planned_departure"),
        "status": s.get("status", "PLANNED"),
        "created_at": s["created_at"],
    }


def serialize_delivery_attempt(a: dict) -> Dict[str, Any]:
    return {
        "id": a["id"],
        "parcel_id": a["parcel_id"],
        "route_stop_id": a["route_stop_id"],
        "driver_id": a["driver_id"],
        "attempted_at": a["attempted_at"],
        "outcome": a["outcome"],
        "signature_blob_ref": a.get("signature_blob_ref"),
        "release_location": a.get("release_location"),
        "created_at": a["created_at"],
    }


def serialize_appointment(a: dict) -> Dict[str, Any]:
    return {
        "id": a["id"],
        "parcel_id": a["parcel_id"],
        "requested_window_start": a["requested_window_start"],
        "requested_window_end": a["requested_window_end"],
        "status": a["status"],
        "fee_charged": _money(a.get("fee_charged", 0)),
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_clock(c) -> Dict[str, Any]:
    from .clock import iso8601_ms, clock as _clk
    return {"now": iso8601_ms(_clk.now())}
