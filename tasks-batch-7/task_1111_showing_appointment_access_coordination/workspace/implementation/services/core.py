"""Entity construction, serializers, activity events, and shared helpers."""

import uuid
from datetime import timedelta

import clock
import db


def new_id():
    return str(uuid.uuid4())


def stamp_new(entity, with_version=True):
    """Set common system fields on a freshly created entity."""
    now = clock.now()
    entity["id"] = new_id()
    entity["created_at"] = now
    entity["updated_at"] = now
    if with_version:
        entity["version"] = 1
    return entity


def touch(entity):
    """Refresh updated_at and bump version on a mutation."""
    entity["updated_at"] = clock.now()
    entity["version"] += 1


def add_activity(listing_id, showing_request_id, event_type, actor_role, detail):
    ev = {
        "id": new_id(),
        "created_at": clock.now(),
        "listing_id": listing_id,
        "showing_request_id": showing_request_id,
        "event_type": event_type,
        "actor_role": actor_role,
        "detail": detail,
    }
    db.activity_events[ev["id"]] = ev
    return ev


# ---------------------------------------------------------------------------
# Serializers (datetime -> ISO strings)
# ---------------------------------------------------------------------------

def _iso(v):
    """System-managed fields (created_at/updated_at): three fractional digits."""
    return clock.fmt(v) if v is not None else None


def _iso_minute(v):
    """Domain/scheduling timestamps: minute precision, no fractional digits."""
    return clock.fmt_minute(v) if v is not None else None


def seller_view(s):
    return {
        "id": s["id"],
        "full_name": s["full_name"],
        "contact_email": s["contact_email"],
        "approval_timeout_minutes": s["approval_timeout_minutes"],
        "auto_approve": s["auto_approve"],
        "created_at": _iso(s["created_at"]),
        "updated_at": _iso(s["updated_at"]),
        "version": s["version"],
    }


def agent_view(a):
    return {
        "id": a["id"],
        "full_name": a["full_name"],
        "license_number": a["license_number"],
        "brokerage_name": a["brokerage_name"],
        "verification_status": a["verification_status"],
        "standing": a["standing"],
        "active_strike_points": a["active_strike_points"],
        "created_at": _iso(a["created_at"]),
        "updated_at": _iso(a["updated_at"]),
        "version": a["version"],
    }


def listing_view(l):
    return {
        "id": l["id"],
        "seller_id": l["seller_id"],
        "listing_agent_id": l["listing_agent_id"],
        "address": l["address"],
        "occupancy_type": l["occupancy_type"],
        "status": l["status"],
        "buffer_minutes": l["buffer_minutes"],
        "max_showings_per_day": l["max_showings_per_day"],
        "min_notice_minutes": l["min_notice_minutes"],
        "confirmed_showing_count": l["confirmed_showing_count"],
        "avg_feedback_score": l["avg_feedback_score"],
        "created_at": _iso(l["created_at"]),
        "updated_at": _iso(l["updated_at"]),
        "version": l["version"],
    }


def verification_case_view(c):
    return {
        "id": c["id"],
        "agent_id": c["agent_id"],
        "license_document_ref": c["license_document_ref"],
        "status": c["status"],
        "review_notes": c["review_notes"],
        "reviewed_at": _iso_minute(c["reviewed_at"]),
        "resubmission_count": c["resubmission_count"],
        "created_at": _iso(c["created_at"]),
        "updated_at": _iso(c["updated_at"]),
        "version": c["version"],
    }


def blackout_window_view(w):
    return {
        "id": w["id"],
        "listing_id": w["listing_id"],
        "start_at": _iso_minute(w["start_at"]),
        "end_at": _iso_minute(w["end_at"]),
        "reason": w["reason"],
        "created_at": _iso(w["created_at"]),
        "updated_at": _iso(w["updated_at"]),
        "version": w["version"],
    }


def showing_request_view(r):
    return {
        "id": r["id"],
        "listing_id": r["listing_id"],
        "buyer_agent_id": r["buyer_agent_id"],
        "start_at": _iso_minute(r["start_at"]),
        "end_at": _iso_minute(r["end_at"]),
        "buyer_name": r["buyer_name"],
        "note": r["note"],
        "status": r["status"],
        "approval_deadline": _iso_minute(r["approval_deadline"]),
        "confirm_by_deadline": _iso_minute(r["confirm_by_deadline"]),
        "decline_reason": r["decline_reason"],
        "cancel_actor": r["cancel_actor"],
        "cancelled_at": _iso_minute(r["cancelled_at"]),
        "completed_at": _iso_minute(r["completed_at"]),
        "reschedule_count": r["reschedule_count"],
        "created_at": _iso(r["created_at"]),
        "updated_at": _iso(r["updated_at"]),
        "version": r["version"],
    }


def credential_view(c):
    return {
        "id": c["id"],
        "showing_request_id": c["showing_request_id"],
        "credential_type": c["credential_type"],
        "access_code": c["access_code"],
        "instructions_text": c["instructions_text"],
        "active_from": _iso_minute(c["active_from"]),
        "expires_at": _iso_minute(c["expires_at"]),
        "status": c["status"],
        "redeemed_at": _iso_minute(c["redeemed_at"]),
        "created_at": _iso(c["created_at"]),
        "updated_at": _iso(c["updated_at"]),
        "version": c["version"],
    }


def feedback_view(f):
    return {
        "id": f["id"],
        "showing_request_id": f["showing_request_id"],
        "status": f["status"],
        "sent_at": _iso_minute(f["sent_at"]),
        "due_at": _iso_minute(f["due_at"]),
        "q1": f["q1"],
        "q2": f["q2"],
        "q3": f["q3"],
        "q4": f["q4"],
        "q5": f["q5"],
        "comment": f["comment"],
        "overall_score": f["overall_score"],
        "submitted_at": _iso_minute(f["submitted_at"]),
        "created_at": _iso(f["created_at"]),
        "updated_at": _iso(f["updated_at"]),
        "version": f["version"],
    }


def strike_view(s):
    return {
        "id": s["id"],
        "agent_id": s["agent_id"],
        "showing_request_id": s["showing_request_id"],
        "strike_type": s["strike_type"],
        "weight": s["weight"],
        "status": s["status"],
        "expires_at": _iso_minute(s["expires_at"]),
        "created_at": _iso(s["created_at"]),
        "updated_at": _iso(s["updated_at"]),
        "version": s["version"],
    }


def activity_event_view(e):
    return {
        "id": e["id"],
        "created_at": _iso(e["created_at"]),
        "listing_id": e["listing_id"],
        "showing_request_id": e["showing_request_id"],
        "event_type": e["event_type"],
        "actor_role": e["actor_role"],
        "detail": e["detail"],
    }


# ---------------------------------------------------------------------------
# Cross-entity lookups
# ---------------------------------------------------------------------------

def credentials_of_request(request_id):
    return [c for c in db.access_credentials.values()
            if c["showing_request_id"] == request_id]


def feedback_of_request(request_id):
    return [f for f in db.feedback_requests.values()
            if f["showing_request_id"] == request_id]


def requests_of_listing(listing_id):
    return [r for r in db.showing_requests.values() if r["listing_id"] == listing_id]


def strikes_of_agent(agent_id):
    return [s for s in db.strike_records.values() if s["agent_id"] == agent_id]
