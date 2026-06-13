"""Entity record construction, common-field stamping, and serialization (§2.4)."""

import itertools

import db
from response import fmt_ts

# Monotonic sequence to give every record a strict, deterministic creation
# order independent of clock resolution. Used as the authoritative tiebreaker
# for list sorting (created_at ASC) and waitlist ordering (created_at ASC).
_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def base_record(common_fields=True):
    """Build the system-managed common fields for a fresh record."""
    ts = db.utcnow()
    rec = {
        "id": db.new_id(),
        "_seq": next_seq(),
        "created_at": ts,
    }
    if common_fields:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """Bump updated_at + version on a mutation (§2.4, §2.5)."""
    rec["updated_at"] = db.utcnow()
    if "version" in rec:
        rec["version"] += 1


# --- Serialization ----------------------------------------------------------
# Each serializer emits exactly the public fields for that entity, with system
# timestamps formatted per §2.4 and internal bookkeeping (_seq, transient flags)
# stripped.

_COMMON = ("id", "created_at", "updated_at", "version")


def _common_out(rec, with_version=True):
    out = {"id": rec["id"], "created_at": fmt_ts(rec["created_at"])}
    if with_version:
        out["updated_at"] = fmt_ts(rec["updated_at"])
        out["version"] = rec["version"]
    return out


def studio_out(rec):
    out = _common_out(rec)
    out.update({
        "name": rec["name"],
        "state_code": rec["state_code"],
        "timezone": rec["timezone"],
        "status": rec["status"],
        "active_room_count": active_room_count(rec["id"]),
    })
    return out


def room_out(rec):
    out = _common_out(rec)
    out.update({
        "studio_id": rec["studio_id"],
        "name": rec["name"],
        "physical_capacity": rec["physical_capacity"],
        "status": rec["status"],
    })
    return out


def instructor_out(rec):
    out = _common_out(rec)
    out.update({
        "full_name": rec["full_name"],
        "home_studio_id": rec["home_studio_id"],
        "status": rec["status"],
    })
    return out


def template_out(rec):
    out = _common_out(rec)
    out.update({
        "name": rec["name"],
        "duration_min": rec["duration_min"],
        "credit_cost": rec["credit_cost"],
        "late_cancel_window_hours": rec["late_cancel_window_hours"],
        "status": rec["status"],
    })
    return out


def plan_out(rec):
    out = _common_out(rec)
    out.update({
        "name": rec["name"],
        "kind": rec["kind"],
        "price_cents": rec["price_cents"],
        "grant_credits": rec["grant_credits"],
        "validity_days": rec["validity_days"],
        "rollover_cap": rec["rollover_cap"],
        "freeze_max_days": rec["freeze_max_days"],
        "intro_once_per_member": rec["intro_once_per_member"],
        "status": rec["status"],
    })
    return out


def member_out(rec):
    out = _common_out(rec)
    out.update({
        "email": rec["email"],
        "full_name": rec["full_name"],
        "home_studio_id": rec["home_studio_id"],
        "has_used_intro": rec["has_used_intro"],
        "no_show_strikes": rec["no_show_strikes"],
        "standing": rec["standing"],
    })
    return out


def membership_out(rec):
    out = _common_out(rec)
    out.update({
        "member_id": rec["member_id"],
        "plan_id": rec["plan_id"],
        "status": rec["status"],
        "credit_balance": rec["credit_balance"],
        "activated_at": fmt_ts(rec.get("activated_at")),
        "cycle_start": fmt_ts(rec.get("cycle_start")),
        "expires_at": fmt_ts(rec.get("expires_at")),
        "frozen_at": fmt_ts(rec.get("frozen_at")),
        "freeze_days_used": rec["freeze_days_used"],
        "rolled_over_credits": rec["rolled_over_credits"],
        "refund_cents": rec["refund_cents"],
    })
    return out


def wallet_entry_out(rec):
    # WalletEntry is leaner: id + created_at only (§2.4). No version/updated_at.
    return {
        "id": rec["id"],
        "created_at": fmt_ts(rec["created_at"]),
        "membership_id": rec["membership_id"],
        "reservation_id": rec.get("reservation_id"),
        "kind": rec["kind"],
        "delta": rec["delta"],
        "note": rec.get("note"),
    }


def session_out(rec):
    out = _common_out(rec)
    out.update({
        "studio_id": rec["studio_id"],
        "room_id": rec["room_id"],
        "instructor_id": rec["instructor_id"],
        "template_id": rec["template_id"],
        "starts_at": fmt_ts(rec["starts_at"]),
        "ends_at": fmt_ts(rec["ends_at"]),
        "seat_capacity": rec["seat_capacity"],
        "waitlist_capacity": rec["waitlist_capacity"],
        "status": rec["status"],
        "booked_count": rec["booked_count"],
        "waitlisted_count": rec["waitlisted_count"],
    })
    return out


def reservation_out(rec):
    out = _common_out(rec)
    out.update({
        "session_id": rec["session_id"],
        "member_id": rec["member_id"],
        "membership_id": rec["membership_id"],
        "booking_status": rec["booking_status"],
        "attendance_status": rec["attendance_status"],
        "credits_charged": rec["credits_charged"],
        "waitlist_position": rec["waitlist_position"],
        "late_fee_cents": rec["late_fee_cents"],
        "promoted_at": fmt_ts(rec.get("promoted_at")),
    })
    return out


def fee_out(rec):
    out = _common_out(rec)
    out.update({
        "member_id": rec["member_id"],
        "reservation_id": rec["reservation_id"],
        "kind": rec["kind"],
        "amount_cents": rec["amount_cents"],
        "status": rec["status"],
        "credit_refunded": rec["credit_refunded"],
    })
    return out


# --- Derived counters (§2.5) ------------------------------------------------

def active_room_count(studio_id):
    return sum(
        1 for r in db.rooms.values()
        if r["studio_id"] == studio_id and r["status"] == "ACTIVE"
    )


def recompute_credit_balance(membership_id):
    total = sum(
        w["delta"] for w in db.wallet_entries.values()
        if w["membership_id"] == membership_id
    )
    db.memberships[membership_id]["credit_balance"] = total
    return total
