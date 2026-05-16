"""Response serializers for each entity — emit canonical field shapes."""


def serialize_family(f):
    return {
        "id": f["id"],
        "household_name": f["household_name"],
        "primary_email": f["primary_email"],
        "residency_status": f["residency_status"],
        "archived": f["archived"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def serialize_guardian(g):
    return {
        "id": g["id"],
        "family_id": g["family_id"],
        "full_name": g["full_name"],
        "phone": g["phone"],
        "relationship": g["relationship"],
        "is_primary": g["is_primary"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def serialize_child(c):
    return {
        "id": c["id"],
        "family_id": c["family_id"],
        "full_name": c["full_name"],
        "date_of_birth": c["date_of_birth"],
        "medical_authorization_status": c["medical_authorization_status"],
        "pickup_authorization_status": c["pickup_authorization_status"],
        "emergency_contact_count": c["emergency_contact_count"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_emergency_contact(e):
    return {
        "id": e["id"],
        "child_id": e["child_id"],
        "full_name": e["full_name"],
        "phone": e["phone"],
        "relationship": e["relationship"],
        "priority": e["priority"],
        "archived": e["archived"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_authorization(a):
    return {
        "id": a["id"],
        "child_id": a["child_id"],
        "guardian_id": a["guardian_id"],
        "kind": a["kind"],
        "scope_text": a["scope_text"],
        "effective_at": a["effective_at"],
        "expires_at": a["expires_at"],
        "status": a["status"],
        "revoked_at": a.get("revoked_at"),
        "created_at": a["created_at"],
    }


def serialize_session(s, *, include_days=False):
    payload = {
        "id": s["id"],
        "title": s["title"],
        "kind": s["kind"],
        "age_min": s["age_min"],
        "age_max": s["age_max"],
        "reference_date": s["reference_date"],
        "weekly_capacity": s["weekly_capacity"],
        "week_start": s["week_start"],
        "week_count": s["week_count"],
        "base_weekly_fee_cents": s["base_weekly_fee_cents"],
        "rainy_day_pool_per_week": s["rainy_day_pool_per_week"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }
    if include_days:
        # PRD §3.3 materializes one SessionDay per business day on OPEN.
        # Expose them on the per-session read so callers can discover
        # the ids needed to call /camp/session-days/{id}.
        from db import db
        days = [
            sd for sd in db.session_days.values()
            if sd["session_id"] == s["id"]
        ]
        days.sort(key=lambda d: (d["week_index"], d["day_date"]))
        payload["session_days"] = [serialize_session_day(d) for d in days]
    return payload


def serialize_enrollment(e):
    return {
        "id": e["id"],
        "child_id": e["child_id"],
        "session_id": e["session_id"],
        "week_index": e["week_index"],
        "status": e["status"],
        "list_fee_cents": e["list_fee_cents"],
        "sibling_discount_cents": e["sibling_discount_cents"],
        "scholarship_discount_cents": e["scholarship_discount_cents"],
        "final_fee_cents": e["final_fee_cents"],
        "scholarship_award_id": e.get("scholarship_award_id"),
        "waitlist_position": e.get("waitlist_position"),
        "cancelled_at": e.get("cancelled_at"),
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_scholarship(s):
    return {
        "id": s["id"],
        "family_id": s["family_id"],
        "total_credit_cents": s["total_credit_cents"],
        "consumed_credit_cents": s["consumed_credit_cents"],
        "granted_for_kind": s["granted_for_kind"],
        "status": s["status"],
        "revoked_at": s.get("revoked_at"),
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_session_day(sd):
    return {
        "id": sd["id"],
        "session_id": sd["session_id"],
        "week_index": sd["week_index"],
        "day_date": sd["day_date"],
        "weather_status": sd["weather_status"],
        "rainy_day_used": sd["rainy_day_used"],
        "outdoor_headcount": sd["outdoor_headcount"],
        "created_at": sd["created_at"],
    }
