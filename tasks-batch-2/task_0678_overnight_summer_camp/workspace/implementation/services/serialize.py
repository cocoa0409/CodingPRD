"""Serializers — render in-memory entities into API JSON.

Common system fields (PRD §2.4): id, created_at, updated_at, version. Computed
counts (session counts/posture, cabin occupancy/staffing, application balances,
offering seats, canteen balance) are reflected here from the maintained store.
"""
import db
from services import recompute, calc


def _common(entity):
    out = {
        "id": entity["id"],
        "created_at": db.iso(entity["created_at_dt"]),
        "updated_at": db.iso(entity["updated_at_dt"]),
        "version": entity["version"],
    }
    return out


def camp(c):
    out = _common(c)
    out.update({
        "name": c["name"],
        "counselor_camper_ratio": c["counselor_camper_ratio"],
        "cit_counts_as_half": c["cit_counts_as_half"],
        "deposit_cents": c["deposit_cents"],
        "deposit_grace_days": c["deposit_grace_days"],
        "canteen_low_balance_cents": c["canteen_low_balance_cents"],
    })
    return out


def session(s):
    out = _common(s)
    out.update({
        "camp_id": s["camp_id"],
        "name": s["name"],
        "starts_on": db.iso(s["starts_on_dt"]),
        "ends_on": db.iso(s["ends_on_dt"]),
        "visiting_day_on": db.iso(s["visiting_day_on_dt"]),
        "enrollment_open": s["enrollment_open"],
        "capacity": s["capacity"],
        "enrolled_count": recompute.session_enrolled_count(s["id"]),
        "committed_count": recompute.session_committed_count(s["id"]),
        "waitlist_length": recompute.session_waitlist_length(s["id"]),
        "ratio_posture": s["ratio_posture"],
        "status": s["status"],
    })
    return out


def cabin(c):
    out = _common(c)
    out.update({
        "session_id": c["session_id"],
        "name": c["name"],
        "gender_band": c["gender_band"],
        "min_age": c["min_age"],
        "max_age": c["max_age"],
        "bunk_capacity": c["bunk_capacity"],
        "occupied_bunks": c["occupied_bunks"],
        "staff_weight_x10": c["staff_weight_x10"],
        "is_staffable": c["is_staffable"],
    })
    return out


def staff_member(s):
    out = _common(s)
    out.update({
        "camp_id": s["camp_id"],
        "full_name": s["full_name"],
        "role_kind": s["role_kind"],
        "is_background_cleared": s["is_background_cleared"],
    })
    return out


def cabin_assignment(ca):
    out = _common(ca)
    out.update({
        "cabin_id": ca["cabin_id"],
        "staff_member_id": ca["staff_member_id"],
        "status": ca["status"],
    })
    return out


def camper(c):
    out = _common(c)
    out.update({
        "guardian_user_id": c["guardian_user_id"],
        "full_name": c["full_name"],
        "age": c["age"],
        "gender": c["gender"],
        "health_status": c["health_status"],
    })
    return out


def guardian(g):
    out = _common(g)
    out.update({
        "email": g["email"],
        "full_name": g["full_name"],
        "phone": g["phone"],
    })
    return out


def application(a):
    out = _common(a)
    # Money fields are derived (PRD §2.5/§3.5): compute live at read time so they
    # always reflect the current aid/payment ledger regardless of which mutation
    # last touched them.
    out.update({
        "camper_id": a["camper_id"],
        "session_id": a["session_id"],
        "cabin_id": a["cabin_id"],
        "enroll_status": a["enroll_status"],
        "payment_status": a["payment_status"],
        "submitted_at": db.iso(a["submitted_at_dt"]) if a.get("submitted_at_dt") else None,
        "offer_expires_at": db.iso(a["offer_expires_at_dt"]) if a.get("offer_expires_at_dt") else None,
        "list_tuition_cents": a["list_tuition_cents"],
        "aid_cents": calc.compute_aid_total(a),
        "estimated_balance_cents": calc.compute_estimated_balance(a),
        "settled_balance_cents": calc.compute_settled_balance(a),
        "deposit_paid_cents": a["deposit_paid_cents"],
    })
    return out


def health_form(h):
    out = _common(h)
    out.update({
        "camper_id": h["camper_id"],
        "has_life_threatening_allergy": h["has_life_threatening_allergy"],
        "epipen_on_file": h["epipen_on_file"],
        "daily_medication_count": h["daily_medication_count"],
        "status": h["status"],
        "review_note": h["review_note"],
    })
    return out


def financial_aid_award(a):
    out = _common(a)
    out.update({
        "application_id": a["application_id"],
        "kind": a["kind"],
        "amount_cents": a["amount_cents"],
        "status": a["status"],
    })
    return out


def payment(p):
    out = _common(p)
    out.update({
        "application_id": p["application_id"],
        "kind": p["kind"],
        "amount_cents": p["amount_cents"],
        "status": p["status"],
    })
    return out


def activity_offering(o):
    out = _common(o)
    out.update({
        "session_id": o["session_id"],
        "name": o["name"],
        "slot_day": o["slot_day"],
        "starts_minute": o["starts_minute"],
        "ends_minute": o["ends_minute"],
        "setup_buffer_minutes": o["setup_buffer_minutes"],
        "seat_capacity": o["seat_capacity"],
        "requires_swim_test": o["requires_swim_test"],
        "seats_taken": o["seats_taken"],
    })
    return out


def activity_enrollment(e):
    out = _common(e)
    out.update({
        "offering_id": e["offering_id"],
        "application_id": e["application_id"],
        "status": e["status"],
    })
    return out


def canteen_account(a):
    out = _common(a)
    # balance_cents / is_low are derived from the transaction ledger (PRD §3.9);
    # compute live at read time.
    balance = calc.compute_canteen_balance(a["id"])
    camp = recompute._camp_for_application(a["application_id"])
    low_threshold = camp["canteen_low_balance_cents"] if camp else 0
    out.update({
        "application_id": a["application_id"],
        "balance_cents": balance,
        "is_low": balance <= low_threshold,
    })
    return out


def canteen_transaction(t):
    # Append-only event: id + created_at only (PRD §2.4).
    return {
        "id": t["id"],
        "created_at": db.iso(t["created_at_dt"]),
        "account_id": t["account_id"],
        "kind": t["kind"],
        "amount_cents": t["amount_cents"],
        "status": t["status"],
    }
