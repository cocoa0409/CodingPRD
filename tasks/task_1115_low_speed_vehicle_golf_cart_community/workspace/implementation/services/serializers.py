"""Entity creation and serialization. Common fields per PRD §2.5:
id (UUID, no prefix), created_at, updated_at (ISO 8601 UTC, 3 fractional
digits), version (integer from 1). Datetimes serialize in the same format.
"""
import db
from db import new_id, iso_now, format_ts


def base_entity():
    ts = iso_now()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def _num(v):
    """Decimal scores serialize as JSON numbers."""
    from decimal import Decimal
    if isinstance(v, Decimal):
        return float(v)
    return v


def community_view(c):
    return {
        "id": c["id"], "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"],
        "name": c["name"],
        "min_driver_age": c["min_driver_age"],
        "insurance_required": c["insurance_required"],
        "fleet_program_enabled": c["fleet_program_enabled"],
        "min_liability_coverage_cents": c["min_liability_coverage_cents"],
        "renewal_window_days": c["renewal_window_days"],
        "late_grace_days": c["late_grace_days"],
        "checked_out_count": c["checked_out_count"],
    }


def permit_holder_view(h):
    return {
        "id": h["id"], "created_at": h["created_at"], "updated_at": h["updated_at"],
        "version": h["version"],
        "community_id": h["community_id"],
        "full_name": h["full_name"],
        "birth_date": h["birth_date"],
        "driver_license_class": h["driver_license_class"],
        "eligibility_status": h["eligibility_status"],
        "compliance_status": h["compliance_status"],
        "points_balance": h["points_balance"],
        "wallet_balance_cents": h["wallet_balance_cents"],
    }


def vehicle_view(v):
    return {
        "id": v["id"], "created_at": v["created_at"], "updated_at": v["updated_at"],
        "version": v["version"],
        "holder_id": v["holder_id"],
        "vehicle_type": v["vehicle_type"],
        "seat_count": v["seat_count"],
        "has_headlights": v["has_headlights"],
        "has_brake_lights": v["has_brake_lights"],
        "has_turn_signals": v["has_turn_signals"],
        "has_horn": v["has_horn"],
        "has_windshield": v["has_windshield"],
        "has_seatbelts": v["has_seatbelts"],
        "has_reflectors": v["has_reflectors"],
        "mirror_count": v["mirror_count"],
        "equipment_count": v["equipment_count"],
        "vehicle_status": v["vehicle_status"],
    }


def registration_view(r):
    return {
        "id": r["id"], "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
        "vehicle_id": r["vehicle_id"],
        "holder_id": r["holder_id"],
        "registration_year": r["registration_year"],
        "status": r["status"],
        "provisional_fee_cents": r["provisional_fee_cents"],
        "finalized_fee_cents": r["finalized_fee_cents"],
        "late_fee_cents": r["late_fee_cents"],
        "total_due_cents": r["total_due_cents"],
        "paid_cents": r["paid_cents"],
        "renewal_score_provisional": _num(r["renewal_score_provisional"]),
        "renewal_score_audited": _num(r["renewal_score_audited"]),
        "valid_from": format_ts(r["valid_from"]),
        "expiry_date": format_ts(r["expiry_date"]),
    }


def inspection_view(i):
    return {
        "id": i["id"], "created_at": i["created_at"], "updated_at": i["updated_at"],
        "version": i["version"],
        "registration_id": i["registration_id"],
        "scheduled_at": format_ts(i["scheduled_at"]),
        "status": i["status"],
        "headlights_score": i["headlights_score"],
        "brake_lights_score": i["brake_lights_score"],
        "turn_signals_score": i["turn_signals_score"],
        "horn_score": i["horn_score"],
        "mirrors_score": i["mirrors_score"],
        "windshield_score": i["windshield_score"],
        "seatbelts_score": i["seatbelts_score"],
        "reflectors_score": i["reflectors_score"],
        "total_score": _num(i["total_score"]),
        "passed": i["passed"],
    }


def insurance_policy_view(p):
    return {
        "id": p["id"], "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"],
        "holder_id": p["holder_id"],
        "vehicle_id": p["vehicle_id"],
        "provider_name": p["provider_name"],
        "policy_number": p["policy_number"],
        "liability_coverage_cents": p["liability_coverage_cents"],
        "effective_date": p["effective_date"],
        "expiry_date": p["expiry_date"].isoformat() if hasattr(p["expiry_date"], "isoformat") else p["expiry_date"],
        "status": p["status"],
    }


def route_view(r):
    return {
        "id": r["id"], "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
        "community_id": r["community_id"],
        "name": r["name"],
        "route_type": r["route_type"],
        "allowed_vehicle_class": r["allowed_vehicle_class"],
        "designation_status": r["designation_status"],
    }


def route_pass_view(p):
    return {
        "id": p["id"], "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"],
        "route_id": p["route_id"],
        "registration_id": p["registration_id"],
        "holder_id": p["holder_id"],
        "start_at": format_ts(p["start_at"]),
        "end_at": format_ts(p["end_at"]),
        "status": p["status"],
    }


def charging_station_view(s):
    return {
        "id": s["id"], "created_at": s["created_at"], "updated_at": s["updated_at"],
        "version": s["version"],
        "community_id": s["community_id"],
        "name": s["name"],
        "slot_count": s["slot_count"],
        "rate_cents_per_min": s["rate_cents_per_min"],
        "status": s["status"],
    }


def charging_reservation_view(r):
    return {
        "id": r["id"], "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
        "station_id": r["station_id"],
        "holder_id": r["holder_id"],
        "slot_index": r["slot_index"],
        "start_at": format_ts(r["start_at"]),
        "end_at": format_ts(r["end_at"]),
        "fee_cents": r["fee_cents"],
        "status": r["status"],
    }


def fleet_vehicle_view(v):
    return {
        "id": v["id"], "created_at": v["created_at"], "updated_at": v["updated_at"],
        "version": v["version"],
        "community_id": v["community_id"],
        "station_id": v["station_id"],
        "label": v["label"],
        "status": v["status"],
    }


def fleet_dispatch_view(d):
    return {
        "id": d["id"], "created_at": d["created_at"], "updated_at": d["updated_at"],
        "version": d["version"],
        "vehicle_id": d["vehicle_id"],
        "holder_id": d["holder_id"],
        "shift_start": format_ts(d["shift_start"]),
        "shift_end": format_ts(d["shift_end"]),
        "status": d["status"],
        "returned_at": format_ts(d["returned_at"]),
        "late_fine_cents": d["late_fine_cents"],
    }


def violation_view(v):
    return {
        "id": v["id"], "created_at": v["created_at"], "updated_at": v["updated_at"],
        "version": v["version"],
        "holder_id": v["holder_id"],
        "registration_id": v["registration_id"],
        "violation_code": v["violation_code"],
        "points_assessed": v["points_assessed"],
        "fine_cents": v["fine_cents"],
        "occurred_at": format_ts(v["occurred_at"]),
        "status": v["status"],
    }
