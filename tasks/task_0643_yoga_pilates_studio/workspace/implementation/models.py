"""Entity construction, common-field management, and serialization.

Common fields (PRD §2.4):
  - id: UUID, no prefix, set at creation
  - created_at: ISO 8601 UTC, 3 fractional digits, fixed at creation
  - updated_at: refreshed on every mutation (FeeCharge is exempt)
  - version: integer, starts at 1, +1 on every mutation (FeeCharge is exempt)

Timestamps are stamped from the LOGICAL clock (the system clock the whole spec
evaluates against). FeeCharge carries only id + created_at.
"""
from db import store


def _stamp_common(rec):
    now = store.now_iso()
    rec_id = store.new_id()
    rec["id"] = rec_id
    rec["created_at"] = now
    rec["updated_at"] = now
    rec["version"] = 1
    rec["_seq"] = store.next_seq()
    return rec


def touch(rec):
    """Mark a record mutated: bump version, refresh updated_at."""
    rec["version"] = rec.get("version", 1) + 1
    rec["updated_at"] = store.now_iso()


# ---- Field sets that are serialized publicly (order does not matter for JSON) ----

_INTERNAL_FIELDS = {"_seq"}


def serialize(rec):
    return {k: v for k, v in rec.items() if k not in _INTERNAL_FIELDS}


# ---------------------------------------------------------------------------
# Entity factories
# ---------------------------------------------------------------------------

def make_member(email, full_name, home_studio_state):
    rec = {
        "email": email,
        "full_name": full_name,
        "home_studio_state": home_studio_state,
        "is_new_student": True,
        "lifetime_attended_count": 0,
        "no_show_strike_count": 0,
        "account_status": "ACTIVE",
        "outstanding_fee_cents": 0,
    }
    return _stamp_common(rec)


def make_room(name, room_type, station_capacity):
    rec = {
        "name": name,
        "room_type": room_type,
        "station_capacity": station_capacity,
        "status": "OPEN",
    }
    return _stamp_common(rec)


def make_teacher(full_name, certifications):
    rec = {
        "full_name": full_name,
        "certifications": list(certifications),
        "status": "ACTIVE",
    }
    return _stamp_common(rec)


def make_intro_offer(name, price_cents, credits_total, window_days):
    rec = {
        "name": name,
        "price_cents": price_cents,
        "credits_total": credits_total,
        "window_days": window_days,
        "status": "ACTIVE",
    }
    return _stamp_common(rec)


def make_class_session(room_id, teacher_id, discipline, start_utc, end_utc,
                       published_capacity, waitlist_capacity, recurrence_parent_id):
    rec = {
        "room_id": room_id,
        "teacher_id": teacher_id,
        "recurrence_parent_id": recurrence_parent_id,
        "discipline": discipline,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "published_capacity": published_capacity,
        "waitlist_capacity": waitlist_capacity,
        "status": "SCHEDULED",
        "booked_count": 0,
        "waitlisted_count": 0,
    }
    return _stamp_common(rec)


def make_entitlement(member_id, kind, intro_offer_id, price_cents, credits_total,
                     cycle_start_utc, cycle_end_utc, auto_renew, rollover_cap):
    credits_remaining = -1 if credits_total == -1 else credits_total
    rec = {
        "member_id": member_id,
        "kind": kind,
        "intro_offer_id": intro_offer_id,
        "price_cents": price_cents,
        "credits_total": credits_total,
        "credits_used": 0,
        "credits_remaining": credits_remaining,
        "cycle_start_utc": cycle_start_utc,
        "cycle_end_utc": cycle_end_utc,
        "auto_renew": auto_renew,
        "rollover_cap": rollover_cap,
        "lifecycle_status": "PENDING",
        "freeze_status": "UNFROZEN",
        "frozen_at_utc": None,
        "frozen_days_consumed": 0,
    }
    return _stamp_common(rec)


def recompute_credits_remaining(ent):
    if ent["credits_total"] == -1:
        ent["credits_remaining"] = -1
    else:
        ent["credits_remaining"] = ent["credits_total"] - ent["credits_used"]


def make_reservation(member_id, class_session_id, entitlement_id, status,
                     waitlist_position, credit_charged, booked_at_utc):
    rec = {
        "member_id": member_id,
        "class_session_id": class_session_id,
        "entitlement_id": entitlement_id,
        "status": status,
        "waitlist_position": waitlist_position,
        "credit_charged": credit_charged,
        "booked_at_utc": booked_at_utc,
    }
    return _stamp_common(rec)


def make_fee_charge(member_id, reservation_id, fee_type, amount_cents):
    """FeeCharge carries only id + created_at (PRD §2.4). No updated_at/version."""
    now = store.now_iso()
    rec = {
        "id": store.new_id(),
        "created_at": now,
        "member_id": member_id,
        "reservation_id": reservation_id,
        "fee_type": fee_type,
        "amount_cents": amount_cents,
        "status": "UNPAID",
        "_seq": store.next_seq(),
    }
    return rec


def make_workshop(room_id, lead_teacher_id, title, kind, start_utc, end_utc,
                  seat_capacity, deposit_cents, price_cents):
    rec = {
        "room_id": room_id,
        "lead_teacher_id": lead_teacher_id,
        "title": title,
        "kind": kind,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "seat_capacity": seat_capacity,
        "deposit_cents": deposit_cents,
        "price_cents": price_cents,
        "status": "DRAFT",
        "confirmed_seat_count": 0,
    }
    return _stamp_common(rec)


def make_enrollment(member_id, workshop_id):
    rec = {
        "member_id": member_id,
        "workshop_id": workshop_id,
        "status": "APPLIED",
        "deposit_paid_cents": 0,
        "balance_due_cents": 0,
    }
    return _stamp_common(rec)
