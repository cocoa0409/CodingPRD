"""Entity serializers. Recompute derived fields at read time for safety."""
from services import calc


def serialize_center(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "name": c["name"],
        "hazmat_certified": c["hazmat_certified"],
        "sort_capacity": c["sort_capacity"],
        "sorted_count": calc.center_live_sorted_count(c["id"]),
        "status": c["status"],
    }


def serialize_driver(d):
    return {
        "id": d["id"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
        "name": d["name"],
        "hazmat_certified": d["hazmat_certified"],
        "vehicle_capacity_kg": d["vehicle_capacity_kg"],
        "failure_points": d["failure_points"],
        "status": d["status"],
    }


def serialize_parcel(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "tracking_code": p["tracking_code"],
        "weight_kg": p["weight_kg"],
        "service_level": p["service_level"],
        "signature_required": p["signature_required"],
        "hazmat_class": p["hazmat_class"],
        "driver_release_authorized": p["driver_release_authorized"],
        "sorted_at_center_id": p["sorted_at_center_id"],
        "status": p["status"],
    }


def serialize_route(r):
    calc.recompute_route_metrics(r)
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "driver_id": r["driver_id"],
        "origin_center_id": r["origin_center_id"],
        "service_date": r["service_date"],
        "max_stops": r["max_stops"],
        "planned_weight_kg": r["planned_weight_kg"],
        "committed_weight_kg": r["committed_weight_kg"],
        "stop_count": r["stop_count"],
        "status": r["status"],
    }


def serialize_stop(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "route_id": s["route_id"],
        "parcel_id": s["parcel_id"],
        "sequence": s["sequence"],
        "window_start_min": s["window_start_min"],
        "window_end_min": s["window_end_min"],
        "attempt_count": s["attempt_count"],
        "redelivery_fee_cents": s["redelivery_fee_cents"],
        "status": s["status"],
    }


def serialize_attempt(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "stop_id": a["stop_id"],
        "outcome": a["outcome"],
        "signature_name": a.get("signature_name"),
        "used_driver_release": a["used_driver_release"],
        "attempt_index": a["attempt_index"],
    }


def serialize_appointment(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "stop_id": a["stop_id"],
        "requested_start_min": a["requested_start_min"],
        "requested_end_min": a["requested_end_min"],
        "status": a["status"],
    }
