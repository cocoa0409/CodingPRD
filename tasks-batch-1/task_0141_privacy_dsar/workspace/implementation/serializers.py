"""Resource -> JSON serialisers.

Each entity is stored as a plain dict with native python values (datetimes are
stored as aware UTC datetimes; computed fields are recomputed at read time). The
serialisers project a stored row into the exact JSON shape the API returns,
formatting timestamps to ISO 8601 UTC millisecond precision (PRD §2.4).

Computed fields (open_request_count, deadline_at, business_days_remaining,
discovery_finding_count, fulfillment_progress_pct, identity_attempts,
extension_count, ack_deadline_at) are derived in services and passed in, so
serialisers stay pure projection.
"""

from timeutil import format_iso


def _ts(dt):
    return format_iso(dt) if dt is not None else None


def controller_out(c, open_request_count):
    return {
        "id": c["id"],
        "name": c["name"],
        "jurisdiction": c["jurisdiction"],
        "dpo_email": c["dpo_email"],
        "open_request_count": open_request_count,
        "created_at": _ts(c["created_at"]),
        "updated_at": _ts(c["updated_at"]),
        "version": c["version"],
    }


def data_subject_out(s):
    return {
        "id": s["id"],
        "controller_id": s["controller_id"],
        "email": s["email"],
        "full_name": s["full_name"],
        "jurisdiction_residency": s["jurisdiction_residency"],
        "known_record_count": s["known_record_count"],
        "created_at": _ts(s["created_at"]),
        "updated_at": _ts(s["updated_at"]),
        "version": s["version"],
    }


def processor_out(p):
    return {
        "id": p["id"],
        "controller_id": p["controller_id"],
        "name": p["name"],
        "notify_email": p["notify_email"],
        "sla_ack_hours": p["sla_ack_hours"],
        "status": p["status"],
        "created_at": _ts(p["created_at"]),
        "updated_at": _ts(p["updated_at"]),
        "version": p["version"],
    }


def consent_record_out(c):
    return {
        "id": c["id"],
        "data_subject_id": c["data_subject_id"],
        "purpose": c["purpose"],
        "state": c["state"],
        "withdrawn_at": _ts(c["withdrawn_at"]),
        "created_at": _ts(c["created_at"]),
        "updated_at": _ts(c["updated_at"]),
        "version": c["version"],
    }


def legal_hold_out(h):
    return {
        "id": h["id"],
        "controller_id": h["controller_id"],
        "data_subject_id": h["data_subject_id"],
        "matter_reference": h["matter_reference"],
        "data_categories": list(h["data_categories"]),
        "state": h["state"],
        "created_at": _ts(h["created_at"]),
        "updated_at": _ts(h["updated_at"]),
        "version": h["version"],
    }


def dsar_request_out(r, computed):
    return {
        "id": r["id"],
        "controller_id": r["controller_id"],
        "data_subject_id": r["data_subject_id"],
        "request_type": r["request_type"],
        "received_at": _ts(r["received_at"]),
        "status": r["status"],
        "identity_attempts": r["identity_attempts"],
        "extension_count": r["extension_count"],
        "deadline_at": _ts(r["deadline_at"]),
        "business_days_remaining": computed["business_days_remaining"],
        "discovery_finding_count": computed["discovery_finding_count"],
        "fulfillment_progress_pct": computed["fulfillment_progress_pct"],
        "verified_by_user_id": r["verified_by_user_id"],
        "created_at": _ts(r["created_at"]),
        "updated_at": _ts(r["updated_at"]),
        "version": r["version"],
    }


def discovery_finding_out(f):
    return {
        "id": f["id"],
        "dsar_request_id": f["dsar_request_id"],
        "processor_id": f["processor_id"],
        "data_category": f["data_category"],
        "record_count": f["record_count"],
        "confidence": f["confidence"],
        "state": f["state"],
        "created_at": _ts(f["created_at"]),
        "updated_at": _ts(f["updated_at"]),
        "version": f["version"],
    }


def exemption_claim_out(e):
    return {
        "id": e["id"],
        "dsar_request_id": e["dsar_request_id"],
        "data_category": e["data_category"],
        "basis": e["basis"],
        "state": e["state"],
        "created_at": _ts(e["created_at"]),
        "updated_at": _ts(e["updated_at"]),
        "version": e["version"],
    }


def fulfillment_item_out(i):
    return {
        "id": i["id"],
        "dsar_request_id": i["dsar_request_id"],
        "discovery_finding_id": i["discovery_finding_id"],
        "processor_id": i["processor_id"],
        "data_category": i["data_category"],
        "action": i["action"],
        "record_count": i["record_count"],
        "state": i["state"],
        "created_at": _ts(i["created_at"]),
        "updated_at": _ts(i["updated_at"]),
        "version": i["version"],
    }


def processor_notification_out(n):
    return {
        "id": n["id"],
        "fulfillment_item_id": n["fulfillment_item_id"],
        "processor_id": n["processor_id"],
        "dispatched_at": _ts(n["dispatched_at"]),
        "ack_deadline_at": _ts(n["ack_deadline_at"]),
        "state": n["state"],
        "created_at": _ts(n["created_at"]),
        "updated_at": _ts(n["updated_at"]),
        "version": n["version"],
    }


def audit_event_out(a):
    # Append-only: id + created_at only (no updated_at / version) per PRD §2.4.
    return {
        "id": a["id"],
        "dsar_request_id": a["dsar_request_id"],
        "actor_role": a["actor_role"],
        "actor_user_id": a["actor_user_id"],
        "event_type": a["event_type"],
        "detail": a["detail"],
        "created_at": _ts(a["created_at"]),
    }


def system_clock_out(store):
    return {"current_utc": format_iso(store.now())}
