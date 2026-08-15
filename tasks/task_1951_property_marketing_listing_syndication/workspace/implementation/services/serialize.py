"""Serializers: stored records -> JSON-ready dicts. Derived Listing fields are
computed fresh at read time (PRD 2.6)."""
from clock import iso_fmt
from services import derived


def agent_json(a):
    return {
        "id": a["id"],
        "full_name": a["full_name"],
        "license_number": a["license_number"],
        "email": a["email"],
        "created_at": iso_fmt(a["created_at"]),
        "updated_at": iso_fmt(a["updated_at"]),
        "version": a["version"],
    }


def listing_json(l, now):
    audited, provisional = derived.compute_breach_counts(l["id"], now)
    raw, weighted = derived.compute_scores(l["id"], now)
    return {
        "id": l["id"],
        "agent_id": l["agent_id"],
        "address_line1": l["address_line1"],
        "city": l["city"],
        "state_code": l["state_code"],
        "postal_code": l["postal_code"],
        "property_type": l["property_type"],
        "list_price_cents": l["list_price_cents"],
        "listing_expires_on": iso_fmt(l["listing_expires_on"]),
        "bedrooms": l["bedrooms"],
        "bathrooms": l["bathrooms"],
        "square_feet": l["square_feet"],
        "marketing_remarks": l["marketing_remarks"],
        "mls_number": l["mls_number"],
        "lifecycle_status": l["lifecycle_status"],
        "syndication_posture": derived.compute_posture(l, now),
        "relist_count": l["relist_count"],
        "terminal_entered_at": iso_fmt(l["terminal_entered_at"]),
        "terminal_price_cents": l["terminal_price_cents"],
        "feedback_score_raw": raw,
        "feedback_score_weighted": weighted,
        "audited_breach_count": audited,
        "provisional_breach_count": provisional,
        "created_at": iso_fmt(l["created_at"]),
        "updated_at": iso_fmt(l["updated_at"]),
        "version": l["version"],
    }


def media_json(m):
    return {
        "id": m["id"],
        "listing_id": m["listing_id"],
        "kind": m["kind"],
        "file_url": m["file_url"],
        "file_bytes": m["file_bytes"],
        "width_px": m["width_px"],
        "height_px": m["height_px"],
        "is_primary": m["is_primary"],
        "status": m["status"],
        "created_at": iso_fmt(m["created_at"]),
        "updated_at": iso_fmt(m["updated_at"]),
        "version": m["version"],
    }


def review_json(r):
    return {
        "id": r["id"],
        "listing_id": r["listing_id"],
        "status": r["status"],
        "remarks_snapshot": r["remarks_snapshot"],
        "flagged_terms": r["flagged_terms"],
        "notes": r["notes"],
        "decided_at": iso_fmt(r["decided_at"]),
        "created_at": iso_fmt(r["created_at"]),
        "updated_at": iso_fmt(r["updated_at"]),
        "version": r["version"],
    }


def portal_json(p):
    return {
        "id": p["id"],
        "portal_name": p["portal_name"],
        "status": p["status"],
        "sla_seconds": p["sla_seconds"],
        "discount_pct": p["discount_pct"],
        "rounding_increment_cents": p["rounding_increment_cents"],
        "created_at": iso_fmt(p["created_at"]),
        "updated_at": iso_fmt(p["updated_at"]),
        "version": p["version"],
    }


def blackout_json(b):
    return {
        "id": b["id"],
        "portal_account_id": b["portal_account_id"],
        "starts_at": iso_fmt(b["starts_at"]),
        "ends_at": iso_fmt(b["ends_at"]),
        "reason": b["reason"],
        "created_at": iso_fmt(b["created_at"]),
    }


def subscription_json(s):
    return {
        "id": s["id"],
        "listing_id": s["listing_id"],
        "portal_account_id": s["portal_account_id"],
        "status": s["status"],
        "created_at": iso_fmt(s["created_at"]),
        "updated_at": iso_fmt(s["updated_at"]),
        "version": s["version"],
    }


def job_json(j):
    return {
        "id": j["id"],
        "feed_subscription_id": j["feed_subscription_id"],
        "listing_id": j["listing_id"],
        "job_type": j["job_type"],
        "status": j["status"],
        "attempt_count": j["attempt_count"],
        "scheduled_at": iso_fmt(j["scheduled_at"]),
        "dispatched_at": iso_fmt(j["dispatched_at"]),
        "completed_at": iso_fmt(j["completed_at"]),
        "propagation_delay_seconds": j["propagation_delay_seconds"],
        "payload_display_price_cents": j["payload_display_price_cents"],
        "failure_code": j["failure_code"],
        "created_at": iso_fmt(j["created_at"]),
        "updated_at": iso_fmt(j["updated_at"]),
        "version": j["version"],
    }


def event_json(e):
    return {
        "id": e["id"],
        "listing_id": e["listing_id"],
        "seq": e["seq"],
        "event_type": e["event_type"],
        "old_price_cents": e["old_price_cents"],
        "new_price_cents": e["new_price_cents"],
        "old_remarks": e["old_remarks"],
        "new_remarks": e["new_remarks"],
        "from_lifecycle": e["from_lifecycle"],
        "to_lifecycle": e["to_lifecycle"],
        "created_at": iso_fmt(e["created_at"]),
    }


def window_json(w):
    return {
        "id": w["id"],
        "listing_id": w["listing_id"],
        "starts_at": iso_fmt(w["starts_at"]),
        "ends_at": iso_fmt(w["ends_at"]),
        "status": w["status"],
        "created_at": iso_fmt(w["created_at"]),
        "updated_at": iso_fmt(w["updated_at"]),
        "version": w["version"],
    }


def feedback_json(f):
    return {
        "id": f["id"],
        "showing_window_id": f["showing_window_id"],
        "listing_id": f["listing_id"],
        "rating": f["rating"],
        "comment": f["comment"],
        "status": f["status"],
        "created_at": iso_fmt(f["created_at"]),
        "updated_at": iso_fmt(f["updated_at"]),
        "version": f["version"],
    }


def relist_request_json(r):
    return {
        "id": r["id"],
        "listing_id": r["listing_id"],
        "relist_count_before": r["relist_count_before"],
        "price_reduction_pct": r["price_reduction_pct"],
        "new_list_price_cents": r["new_list_price_cents"],
        "fee_cents": r["fee_cents"],
        "created_at": iso_fmt(r["created_at"]),
        "updated_at": iso_fmt(r["updated_at"]),
        "version": r["version"],
    }
