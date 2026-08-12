"""Entity serializers — shape entities for API output."""
import db


def ceremony_out(c):
    db_c = c
    return {
        "id": db_c["id"],
        "name": db_c["name"],
        "ceremony_date": db_c["ceremony_date"],
        "venue_id": db_c["venue_id"],
        "rain_venue_id": db_c["rain_venue_id"],
        "readiness_posture": db_c["readiness_posture"],
        "weather_mode": db_c["weather_mode"],
        "ticket_ratio": db_c["ticket_ratio"],
        "guest_ticket_base_cap": db_c["guest_ticket_base_cap"],
        "honor_bonus_tickets": db_c["honor_bonus_tickets"],
        "rehearsal_required": db_c["rehearsal_required"],
        "pronunciation_deadline": db_c["pronunciation_deadline"],
        "ticket_request_deadline": db_c["ticket_request_deadline"],
        "regalia_order_deadline": db_c["regalia_order_deadline"],
        "effective_capacity": db_c["effective_capacity"],
        "ticket_pool_total": db_c["ticket_pool_total"],
        "ticket_pool_remaining": db_c["ticket_pool_remaining"],
        "open_seat_count": db_c["open_seat_count"],
        "created_at": db_c["created_at"],
        "updated_at": db_c["updated_at"],
        "version": db_c["version"],
    }


def venue_out(v):
    return {
        "id": v["id"],
        "name": v["name"],
        "address": v["address"],
        "total_capacity": v["total_capacity"],
        "accessible_capacity": v["accessible_capacity"],
        "indoor": v["indoor"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def graduate_out(g):
    return {
        "id": g["id"],
        "ceremony_id": g["ceremony_id"],
        "full_name": g["full_name"],
        "email": g["email"],
        "institutional_gpa_credits": g["institutional_gpa_credits"],
        "institutional_quality_points": g["institutional_quality_points"],
        "transfer_gpa_credits": g["transfer_gpa_credits"],
        "transfer_quality_points": g["transfer_quality_points"],
        "credits_completed": g["credits_completed"],
        "credits_required": g["credits_required"],
        "outstanding_hold_count": g["outstanding_hold_count"],
        "status": g["status"],
        "honor_tier": g["honor_tier"],
        "honor_basis": g["honor_basis"],
        "conduct_strike_count": g["conduct_strike_count"],
        "walk_privilege_revoked": g["walk_privilege_revoked"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def audit_out(a):
    return {
        "id": a["id"],
        "graduate_id": a["graduate_id"],
        "result": a["result"],
        "fail_reasons": a["fail_reasons"],
        "provisional_honor_tier": a["provisional_honor_tier"],
        "appeal_status": a["appeal_status"],
        "audited_by_user_id": a["audited_by_user_id"],
        "decided_by_user_id": a["decided_by_user_id"],
        "notes": a["notes"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def allocation_out(a):
    return {
        "id": a["id"],
        "graduate_id": a["graduate_id"],
        "ceremony_id": a["ceremony_id"],
        "requested_count": a["requested_count"],
        "entitlement_count": a["entitlement_count"],
        "provisional_granted_count": a["provisional_granted_count"],
        "granted_count": a["granted_count"],
        "waitlist_position": a["waitlist_position"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def regalia_out(o):
    return {
        "id": o["id"],
        "graduate_id": o["graduate_id"],
        "items": o["items"],
        "subtotal_cents": o["subtotal_cents"],
        "discount_cents": o["discount_cents"],
        "late_fee_cents": o["late_fee_cents"],
        "total_cents": o["total_cents"],
        "status": o["status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def seat_out(s):
    return {
        "id": s["id"],
        "ceremony_id": s["ceremony_id"],
        "graduate_id": s["graduate_id"],
        "section": s["section"],
        "row_label": s["row_label"],
        "seat_number": s["seat_number"],
        "accessible": s["accessible"],
        "status": s["status"],
        "evicted_reason": s["evicted_reason"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def reader_card_out(r):
    return {
        "id": r["id"],
        "graduate_id": r["graduate_id"],
        "phonetic_spelling": r["phonetic_spelling"],
        "status": r["status"],
        "approved_by_user_id": r["approved_by_user_id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def batch_out(b):
    return {
        "id": b["id"],
        "ceremony_id": b["ceremony_id"],
        "scheduled_print_date": b["scheduled_print_date"],
        "status": b["status"],
        "created_by_user_id": b["created_by_user_id"],
        "released_by_user_id": b["released_by_user_id"],
        "diploma_count": b["diploma_count"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def diploma_out(d):
    return {
        "id": d["id"],
        "graduate_id": d["graduate_id"],
        "print_batch_id": d["print_batch_id"],
        "printed_name": d["printed_name"],
        "honors_text": d["honors_text"],
        "pinned_honor_tier": d["pinned_honor_tier"],
        "corrected_name": d["corrected_name"],
        "correction_count": d["correction_count"],
        "status": d["status"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def session_out(s):
    return {
        "id": s["id"],
        "ceremony_id": s["ceremony_id"],
        "venue_id": s["venue_id"],
        "start_utc": s["start_utc"],
        "end_utc": s["end_utc"],
        "capacity": s["capacity"],
        "registered_count": s["registered_count"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def attendance_out(a):
    return {
        "id": a["id"],
        "rehearsal_session_id": a["rehearsal_session_id"],
        "graduate_id": a["graduate_id"],
        "status": a["status"],
        "checked_in_at": a["checked_in_at"],
        "recorded_by_user_id": a["recorded_by_user_id"],
        "waived_by_user_id": a["waived_by_user_id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def accommodation_out(r):
    return {
        "id": r["id"],
        "graduate_id": r["graduate_id"],
        "ceremony_id": r["ceremony_id"],
        "request_type": r["request_type"],
        "notes": r["notes"],
        "status": r["status"],
        "approved_by_user_id": r["approved_by_user_id"],
        "fulfilled_by_user_id": r["fulfilled_by_user_id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def vendor_out(c):
    return {
        "id": c["id"],
        "ceremony_id": c["ceremony_id"],
        "vendor_type": c["vendor_type"],
        "vendor_user_id": c["vendor_user_id"],
        "coverage_start_utc": c["coverage_start_utc"],
        "coverage_end_utc": c["coverage_end_utc"],
        "setup_buffer_minutes": c["setup_buffer_minutes"],
        "fee_cents": c["fee_cents"],
        "deliverable_url": c["deliverable_url"],
        "cancellation_fee_cents": c["cancellation_fee_cents"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }
