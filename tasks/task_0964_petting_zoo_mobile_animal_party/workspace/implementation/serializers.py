"""Entity -> JSON serialization. Datetimes become ISO 8601 UTC with 3 fractional digits."""
from util import fmt_dt


def _common(e):
    return {
        "id": e["id"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def _immutable(e):
    return {"id": e["id"], "created_at": fmt_dt(e["created_at"])}


def ser_customer(c):
    out = {"email": c["email"], "full_name": c["full_name"], "customer_type": c["customer_type"]}
    out.update(_common(c))
    return out


def ser_venue(v):
    out = {
        "customer_id": v["customer_id"],
        "name": v["name"],
        "address": v["address"],
        "venue_type": v["venue_type"],
        "water_access": v["water_access"],
        "surface_type": v["surface_type"],
        "travel_zone": v["travel_zone"],
        "distance_miles": v["distance_miles"],
        "max_guest_capacity": v["max_guest_capacity"],
        "requires_animal_permit": v["requires_animal_permit"],
        "requires_handwash_stations": v["requires_handwash_stations"],
    }
    out.update(_common(v))
    return out


def ser_animal(a):
    out = {
        "name": a["name"],
        "species": a["species"],
        "weight_class": a["weight_class"],
        "temperament_tier": a["temperament_tier"],
        "base_event_fee_cents": a["base_event_fee_cents"],
        "rest_buffer_hours": a["rest_buffer_hours"],
        "status": a["status"],
        "current_health_cert_expires_at": fmt_dt(a["current_health_cert_expires_at"]),
    }
    out.update(_common(a))
    return out


def ser_health_record(h):
    out = {
        "animal_id": h["animal_id"],
        "exam_date": fmt_dt(h["exam_date"]),
        "result": h["result"],
        "valid_until": fmt_dt(h["valid_until"]),
        "notes": h["notes"],
    }
    out.update(_immutable(h))
    return out


def ser_handler(h):
    out = {
        "name": h["name"],
        "certifications": list(h["certifications"]),
        "status": h["status"],
        "scheduled_minutes_total": h["scheduled_minutes_total"],
    }
    out.update(_common(h))
    return out


def ser_booking(b):
    out = {
        "customer_id": b["customer_id"],
        "venue_id": b["venue_id"],
        "start_time": fmt_dt(b["start_time"]),
        "end_time": fmt_dt(b["end_time"]),
        "guest_count": b["guest_count"],
        "child_guest_count": b["child_guest_count"],
        "booking_type": b["booking_type"],
        "planned_handwash_stations": b["planned_handwash_stations"],
        "status": b["status"],
        "payment_status": b["payment_status"],
        "quote_fresh": b["quote_fresh"],
        "animal_subtotal_cents": b["animal_subtotal_cents"],
        "addon_subtotal_cents": b["addon_subtotal_cents"],
        "discount_cents": b["discount_cents"],
        "surcharge_cents": b["surcharge_cents"],
        "travel_fee_cents": b["travel_fee_cents"],
        "guest_surcharge_cents": b["guest_surcharge_cents"],
        "quoted_total_cents": b["quoted_total_cents"],
        "final_total_cents": b["final_total_cents"],
        "deposit_amount_cents": b["deposit_amount_cents"],
        "total_paid_cents": b["total_paid_cents"],
        "required_handwash_stations": b["required_handwash_stations"],
        "required_staff_count": b["required_staff_count"],
        "compliance_screening_score": b["compliance_screening_score"],
        "compliance_audited_score": b["compliance_audited_score"],
        "actual_handwash_stations": b["actual_handwash_stations"],
        "actual_attendance_count": b["actual_attendance_count"],
    }
    out.update(_common(b))
    return out


def ser_booking_animal(ba):
    out = {
        "booking_id": ba["booking_id"],
        "animal_id": ba["animal_id"],
        "role": ba["role"],
        "status": ba["status"],
        "removal_reason": ba["removal_reason"],
    }
    out.update(_common(ba))
    return out


def ser_staff_assignment(s):
    out = {
        "booking_id": s["booking_id"],
        "handler_id": s["handler_id"],
        "role": s["role"],
        "status": s["status"],
        "release_reason": s["release_reason"],
    }
    out.update(_common(s))
    return out


def ser_addon(a):
    out = {
        "booking_id": a["booking_id"],
        "addon_type": a["addon_type"],
        "duration_minutes": a["duration_minutes"],
        "status": a["status"],
        "denial_reason": a["denial_reason"],
    }
    out.update(_common(a))
    return out


def ser_permit(p):
    out = {
        "booking_id": p["booking_id"],
        "permit_type": p["permit_type"],
        "jurisdiction": p["jurisdiction"],
        "status": p["status"],
        "submitted_by_user_id": p["submitted_by_user_id"],
        "decided_by_user_id": p["decided_by_user_id"],
        "denial_reason": p["denial_reason"],
    }
    out.update(_common(p))
    return out


def ser_waiver(w):
    out = {
        "booking_id": w["booking_id"],
        "required_signatures": w["required_signatures"],
        "signed_count": w["signed_count"],
        "status": w["status"],
    }
    out.update(_common(w))
    return out


def ser_insurance_certificate(c):
    out = {
        "customer_id": c["customer_id"],
        "provider": c["provider"],
        "policy_number": c["policy_number"],
        "coverage_amount_cents": c["coverage_amount_cents"],
        "expires_at": fmt_dt(c["expires_at"]),
        "status": c["status"],
    }
    out.update(_common(c))
    return out


def ser_weather_assessment(w):
    out = {
        "booking_id": w["booking_id"],
        "assessed_at": fmt_dt(w["assessed_at"]),
        "forecast_temp_f": w["forecast_temp_f"],
        "forecast_precip_pct": w["forecast_precip_pct"],
        "wind_mph": w["wind_mph"],
        "verdict": w["verdict"],
    }
    out.update(_immutable(w))
    return out


def ser_ledger_entry(e):
    out = {
        "booking_id": e["booking_id"],
        "entry_type": e["entry_type"],
        "amount_cents": e["amount_cents"],
        "description": e["description"],
    }
    out.update(_immutable(e))
    return out
