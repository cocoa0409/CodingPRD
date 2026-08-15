"""Entity -> wire-dict serializers. Datetimes stored as ISO strings already;
common fields per PRD §2.5: id, created_at, updated_at, version."""

from db import iso_out, _parse_iso


def serialize_route(r):
    return {
        "id": r["id"],
        "route_code": r["route_code"],
        "origin_terminal": r["origin_terminal"],
        "destination_terminal": r["destination_terminal"],
        "crossing_minutes": r["crossing_minutes"],
        "turnaround_minutes": r["turnaround_minutes"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_vessel(v):
    return {
        "id": v["id"],
        "vessel_name": v["vessel_name"],
        "vehicle_deck_linear_feet": v["vehicle_deck_linear_feet"],
        "passenger_capacity": v["passenger_capacity"],
        "crew_class": v["crew_class"],
        "status": v["status"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def serialize_fare_schedule(f):
    return {
        "id": f["id"],
        "route_id": f["route_id"],
        "season": f["season"],
        "effective_from": f["effective_from"],
        "effective_to": f["effective_to"],
        "passenger_standard_cents": f["passenger_standard_cents"],
        "passenger_resident_cents": f["passenger_resident_cents"],
        "passenger_commuter_cents": f["passenger_commuter_cents"],
        "vehicle_standard_base_cents": f["vehicle_standard_base_cents"],
        "vehicle_oversize_base_cents": f["vehicle_oversize_base_cents"],
        "vehicle_overlength_per_foot_cents": f["vehicle_overlength_per_foot_cents"],
        "fuel_surcharge_cents": f["fuel_surcharge_cents"],
        "status": f["status"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def serialize_sailing(s):
    return {
        "id": s["id"],
        "route_id": s["route_id"],
        "vessel_id": s["vessel_id"],
        "departure_time": s["departure_time"],
        "arrival_time": s["arrival_time"],
        "season": s["season"],
        "status": s["status"],
        "cancel_reason": s.get("cancel_reason"),
        "reserved_vehicle_feet": s["reserved_vehicle_feet"],
        "standby_cleared_feet": s["standby_cleared_feet"],
        "booked_passengers": s["booked_passengers"],
        "reserved_deck_allotment_feet": s["reserved_deck_allotment_feet"],
        "manning_ok": s["manning_ok"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_customer(c):
    return {
        "id": c["id"],
        "full_name": c["full_name"],
        "email": c["email"],
        "fare_class": c["fare_class"],
        "refund_credit_cents": c["refund_credit_cents"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_booking(b):
    return {
        "id": b["id"],
        "sailing_id": b["sailing_id"],
        "customer_id": b["customer_id"],
        "fare_schedule_id": b["fare_schedule_id"],
        "passenger_count": b["passenger_count"],
        "has_vehicle": b["has_vehicle"],
        "vehicle_length_feet": b.get("vehicle_length_feet"),
        "status": b["status"],
        "quoted_fare_cents": b.get("quoted_fare_cents"),
        "final_fare_cents": b.get("final_fare_cents"),
        "rebooked_to_booking_id": b.get("rebooked_to_booking_id"),
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def serialize_standby_entry(e):
    return {
        "id": e["id"],
        "sailing_id": e["sailing_id"],
        "customer_id": e["customer_id"],
        "has_vehicle": e["has_vehicle"],
        "vehicle_length_feet": e.get("vehicle_length_feet"),
        "passenger_count": e["passenger_count"],
        "priority_class": e["priority_class"],
        "queued_at": e["queued_at"],
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_crew_member(m):
    return {
        "id": m["id"],
        "full_name": m["full_name"],
        "credential_class": m["credential_class"],
        "status": m["status"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def serialize_crew_assignment(a):
    return {
        "id": a["id"],
        "sailing_id": a["sailing_id"],
        "crew_member_id": a["crew_member_id"],
        "shift_start": a["shift_start"],
        "shift_end": a["shift_end"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }
