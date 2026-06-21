"""Resource serializers — produce the public JSON shape for each entity."""
import domain
from store import db


def ser_owner(o):
    return {
        "id": o["id"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
        "full_name": o["full_name"],
        "email": o["email"],
        "phone": o["phone"],
    }


def ser_trainer(t):
    return {
        "id": t["id"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
        "full_name": t["full_name"],
        "certified_levels": list(t["certified_levels"]),
        "handles_private": t["handles_private"],
        "status": t["status"],
    }


def ser_dog(d, refresh=False):
    if refresh:
        domain.refresh_dog_computed(d)
    else:
        # always reflect current computed facets
        d["vaccination_posture"] = domain.dog_posture_now(d["id"])
        d["highest_completed_level"] = domain.compute_highest_completed_level(d["id"])
        d["intake_status"] = domain.compute_intake_status(d["id"])
    return {
        "id": d["id"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
        "owner_id": d["owner_id"],
        "name": d["name"],
        "breed": d["breed"],
        "birth_date": d["birth_date"],
        "vaccination_posture": d["vaccination_posture"],
        "highest_completed_level": d["highest_completed_level"],
        "intake_status": d["intake_status"],
    }


def ser_vaccination(v):
    return {
        "id": v["id"],
        "created_at": v["created_at"],
        "dog_id": v["dog_id"],
        "vaccine_type": v["vaccine_type"],
        "administered_on": v["administered_on"],
        "expires_on": v["expires_on"],
        "voided": v["voided"],
    }


def ser_intake(i):
    return {
        "id": i["id"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
        "dog_id": i["dog_id"],
        "reactivity_score": i["reactivity_score"],
        "bite_history": i["bite_history"],
        "recommended_level": i["recommended_level"],
        "outcome": i["outcome"],
        "requires_private_first": i["requires_private_first"],
    }


def ser_series(s):
    domain.recompute_series_seats(s)
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "title": s["title"],
        "level": s["level"],
        "prerequisite_level": s["prerequisite_level"],
        "modality": s["modality"],
        "capacity": s["capacity"],
        "session_count": s["session_count"],
        "list_price_cents": s["list_price_cents"],
        "credit_cost": s["credit_cost"],
        "enrolled_count": s["enrolled_count"],
        "seats_available": s["seats_available"],
        "status": s["status"],
    }


def ser_session(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "series_id": s["series_id"],
        "trainer_id": s["trainer_id"],
        "sequence_index": s["sequence_index"],
        "starts_at": s["starts_at"],
        "ends_at": s["ends_at"],
        "is_makeup_slot": s["is_makeup_slot"],
        "status": s["status"],
    }


def ser_enrollment(e, refresh=False):
    if refresh:
        domain.refresh_enrollment_progress(e)
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
        "dog_id": e["dog_id"],
        "series_id": e["series_id"],
        "payment_method": e["payment_method"],
        "package_id": e["package_id"],
        "price_charged_cents": e["price_charged_cents"],
        "credits_debited": e["credits_debited"],
        "sessions_attended": e["sessions_attended"],
        "sessions_remaining": e["sessions_remaining"],
        "graduation_eligible": e["graduation_eligible"],
        "refund_cents": e["refund_cents"],
        "credits_refunded": e["credits_refunded"],
        "status": e["status"],
    }


def ser_package(p, refresh=False):
    if refresh:
        domain.recompute_package(p)
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "owner_id": p["owner_id"],
        "tier": p["tier"],
        "credits_total": p["credits_total"],
        "price_paid_cents": p["price_paid_cents"],
        "credits_consumed": p["credits_consumed"],
        "credits_remaining": p["credits_remaining"],
        "status": p["status"],
    }


def ser_redemption(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "package_id": r["package_id"],
        "enrollment_id": r["enrollment_id"],
        "kind": r["kind"],
        "credits": r["credits"],
    }


def ser_attendance(a):
    domain.refresh_attendance_eligible(a)
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "enrollment_id": a["enrollment_id"],
        "session_id": a["session_id"],
        "state": a["state"],
        "makeup_eligible": a["makeup_eligible"],
    }


def ser_makeup(m):
    return {
        "id": m["id"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
        "attendance_id": m["attendance_id"],
        "makeup_session_id": m["makeup_session_id"],
        "status": m["status"],
    }


def ser_certificate(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "enrollment_id": c["enrollment_id"],
        "dog_id": c["dog_id"],
        "level": c["level"],
        "serial": c["serial"],
    }
