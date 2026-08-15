"""Entity -> public dict serializers (computed fields resolved here)."""

import db
from services import core


def window_view(w):
    return {
        "id": w["id"],
        "name": w["name"],
        "term_label": w["term_label"],
        "format": w["format"],
        "slot_length_minutes": w["slot_length_minutes"],
        "buffer_minutes": w["buffer_minutes"],
        "travel_minutes": w["travel_minutes"],
        "day_windows": [dict(d) for d in w["day_windows"]],
        "booking_open_at": w["booking_open_at"],
        "booking_close_at": w["booking_close_at"],
        "teacher_daily_conf_cap": w["teacher_daily_conf_cap"],
        "family_conf_cap": w["family_conf_cap"],
        "cancel_cutoff_hours": w["cancel_cutoff_hours"],
        "waitlist_offer_ttl_hours": w["waitlist_offer_ttl_hours"],
        "no_show_strike_threshold": w["no_show_strike_threshold"],
        "auto_no_show_grace_hours": w["auto_no_show_grace_hours"],
        "status": w["status"],
        "ops_run_index": w["ops_run_index"],
        "slots_total_count": core.slots_total_count(w["id"]),
        "slots_open_count": core.slots_count(w["id"], "OPEN"),
        "slots_held_count": core.slots_count(w["id"], "HELD"),
        "slots_booked_count": core.slots_count(w["id"], "BOOKED"),
        "bookings_confirmed_count": core.bookings_confirmed_count(w["id"]),
        "waitlist_waiting_count": core.waitlist_waiting_count(w["id"]),
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def teacher_view(t):
    return {
        "id": t["id"],
        "full_name": t["full_name"],
        "email": t["email"],
        "grade_band": t["grade_band"],
        "subjects": list(t["subjects"]),
        "room_location": t["room_location"],
        "supports_in_person": t["supports_in_person"],
        "supports_virtual": t["supports_virtual"],
        "daily_conf_cap_override": t["daily_conf_cap_override"],
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def family_view(f):
    return {
        "id": f["id"],
        "primary_guardian_name": f["primary_guardian_name"],
        "email": f["email"],
        "phone": f["phone"],
        "preferred_language": f["preferred_language"],
        "status": f["status"],
        "no_show_strike_count": core.family_strike_count(f["id"]),
        "strikes_cleared_total": f["strikes_cleared_total"],
        "attendance_risk_strict": core.family_risk_strict(f["id"]),
        "attendance_risk_score": core.family_risk_score(f["id"]),
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def student_view(s):
    return {
        "id": s["id"],
        "family_id": s["family_id"],
        "full_name": s["full_name"],
        "grade_level": s["grade_level"],
        "enrollment_status": s["enrollment_status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def link_view(l):
    return {
        "id": l["id"],
        "student_id": l["student_id"],
        "teacher_id": l["teacher_id"],
        "is_homeroom": l["is_homeroom"],
        "required_conference": l["required_conference"],
        "created_at": l["created_at"],
    }


def slot_view(s):
    return {
        "id": s["id"],
        "window_id": s["window_id"],
        "teacher_id": s["teacher_id"],
        "day_label": s["day_label"],
        "start_at": s["start_at"],
        "end_at": s["end_at"],
        "channel_allowed": s["channel_allowed"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def booking_view(b):
    return {
        "id": b["id"],
        "window_id": b["window_id"],
        "family_id": b["family_id"],
        "student_id": b["student_id"],
        "teacher_id": b["teacher_id"],
        "slot_id": b["slot_id"],
        "channel": b["channel"],
        "interpreter_language": b["interpreter_language"],
        "booked_by_role": b["booked_by_role"],
        "status": b["status"],
        "cancel_reason": b["cancel_reason"],
        "rescheduled_from_booking_id": b["rescheduled_from_booking_id"],
        "family_compactness_score": core.compactness_score(b["family_id"], b["window_id"]),
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def interpreter_view(i):
    return {
        "id": i["id"],
        "full_name": i["full_name"],
        "languages": list(i["languages"]),
        "supports_in_person": i["supports_in_person"],
        "supports_virtual": i["supports_virtual"],
        "max_consecutive_minutes": i["max_consecutive_minutes"],
        "base_minutes_per_window": i["base_minutes_per_window"],
        "hourly_rate_cents": i["hourly_rate_cents"],
        "status": i["status"],
        "committed_minutes": core.interpreter_committed_minutes(i["id"]),
        "created_seq": i["created_seq"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def request_view(r):
    return {
        "id": r["id"],
        "booking_id": r["booking_id"],
        "window_id": r["window_id"],
        "language": r["language"],
        "channel_required": r["channel_required"],
        "interpreter_id": r["interpreter_id"],
        "assigned_minutes": r["assigned_minutes"],
        "declined_interpreter_ids": list(r["declined_interpreter_ids"]),
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def waitlist_view(e):
    return {
        "id": e["id"],
        "window_id": e["window_id"],
        "family_id": e["family_id"],
        "student_id": e["student_id"],
        "teacher_id": e["teacher_id"],
        "channel_pref": e["channel_pref"],
        "status": e["status"],
        "offers_made_count": e["offers_made_count"],
        "offered_slot_id": e["offered_slot_id"],
        "offer_expires_at": e["offer_expires_at"],
        "declined_slot_ids": list(e["declined_slot_ids"]),
        "priority_score": e["priority_score"],
        "created_seq": e["created_seq"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def attendance_view(a):
    return {
        "id": a["id"],
        "booking_id": a["booking_id"],
        "outcome": a["outcome"],
        "marked_by_role": a["marked_by_role"],
        "marked_by_user_id": a["marked_by_user_id"],
        "note": a["note"],
        "created_at": a["created_at"],
    }


def outreach_view(t):
    return {
        "id": t["id"],
        "family_id": t["family_id"],
        "window_id": t["window_id"],
        "booking_id": t["booking_id"],
        "kind": t["kind"],
        "status": t["status"],
        "attempts_count": t["attempts_count"],
        "note": t["note"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }
