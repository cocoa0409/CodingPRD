"""Serialize stored entity dicts into API output shapes.

Each entity exposes exactly the fields declared in SCAFFOLD 1.1. Derived fields
are recomputed/refreshed by the routes before serialization where required, so
serialization is a straight field projection.
"""


def facility_out(f):
    return {
        "id": f["id"],
        "name": f["name"],
        "timezone": f["timezone"],
        "open_minute": f["open_minute"],
        "close_minute": f["close_minute"],
        "token_price_cents": f["token_price_cents"],
        "hourly_rate_cents": f["hourly_rate_cents"],
        "posture": f["posture"],
        "open_incident_count": f["open_incident_count"],
        "epoch_index": f["epoch_index"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def lane_out(l):
    return {
        "id": l["id"],
        "facility_id": l["facility_id"],
        "label": l["label"],
        "kind": l["kind"],
        "buffer_minutes": l["buffer_minutes"],
        "hourly_rate_cents": l["hourly_rate_cents"],
        "maint_status": l["maint_status"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def machine_out(m):
    return {
        "id": m["id"],
        "facility_id": m["facility_id"],
        "lane_id": m["lane_id"],
        "model": m["model"],
        "pitch_count": m["pitch_count"],
        "status": m["status"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def maintenance_out(w):
    return {
        "id": w["id"],
        "facility_id": w["facility_id"],
        "lane_id": w["lane_id"],
        "start_utc": w["start_utc"],
        "end_utc": w["end_utc"],
        "severity": w["severity"],
        "status": w["status"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def member_out(m):
    return {
        "id": m["id"],
        "facility_id": m["facility_id"],
        "full_name": m["full_name"],
        "tier": m["tier"],
        "token_balance": m["token_balance"],
        "monthly_member_minutes_used": m["monthly_member_minutes_used"],
        "no_show_strikes": m["no_show_strikes"],
        "waiver_ok": m["waiver_ok"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def waiver_out(w):
    # PRD 2.4: Waiver has only id + created_at (no updated_at / version).
    return {
        "id": w["id"],
        "facility_id": w["facility_id"],
        "member_id": w["member_id"],
        "signed_at": w["signed_at"],
        "expires_at": w["expires_at"],
        "status": w["status"],
        "created_at": w["created_at"],
    }


def instructor_out(i):
    return {
        "id": i["id"],
        "facility_id": i["facility_id"],
        "full_name": i["full_name"],
        "rate_cents_per_hour": i["rate_cents_per_hour"],
        "active": i["active"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def booking_out(b):
    return {
        "id": b["id"],
        "facility_id": b["facility_id"],
        "lane_id": b["lane_id"],
        "member_id": b["member_id"],
        "instructor_id": b["instructor_id"],
        "machine_id": b["machine_id"],
        "kind": b["kind"],
        "pay_mode": b["pay_mode"],
        "lane_count": b["lane_count"],
        "team_lane_ids": b["team_lane_ids"],
        "party_guests": b["party_guests"],
        "start_utc": b["start_utc"],
        "end_utc": b["end_utc"],
        "duration_minutes": b["duration_minutes"],
        "quoted_cost_cents": b["quoted_cost_cents"],
        "final_cost_cents": b["final_cost_cents"],
        "token_cost": b["token_cost"],
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def program_out(p):
    return {
        "id": p["id"],
        "facility_id": p["facility_id"],
        "lane_id": p["lane_id"],
        "kind": p["kind"],
        "capacity": p["capacity"],
        "price_cents": p["price_cents"],
        "session_start_utc": p["session_start_utc"],
        "session_end_utc": p["session_end_utc"],
        "enrolled_count": p["enrolled_count"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def enrollment_out(e):
    return {
        "id": e["id"],
        "facility_id": e["facility_id"],
        "program_id": e["program_id"],
        "member_id": e["member_id"],
        "status": e["status"],
        "charged_cents": e["charged_cents"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }
