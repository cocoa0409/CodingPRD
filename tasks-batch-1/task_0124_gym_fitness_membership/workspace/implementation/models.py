"""Record creation (common fields) and per-entity serialization.

Internal records are plain dicts that store datetimes as aware datetime
objects plus a hidden monotonic '_seq'. Serializers convert to the public
JSON shape (datetimes -> ISO 8601 ms strings, computed/derived fields filled).
"""
import db
from util import fmt_dt


def stamp_new(record, versioned=True):
    """Attach common system fields to a freshly created record (PRD §2.4).

    id, created_at, updated_at, version (version omitted for CheckIn).
    A hidden _seq gives a total creation order for created_at-ascending sorts.
    """
    record["id"] = db.new_id()
    now = db.now()
    record["created_at"] = now
    record["_seq"] = db.next_seq()
    if versioned:
        record["updated_at"] = now
        record["version"] = 1
    return record


def touch(record):
    """Mutation bump: refresh updated_at, increment version (PRD §2.4, §2.6)."""
    record["updated_at"] = db.now()
    record["version"] = record.get("version", 0) + 1


# --------------------------------------------------------------------------
# Serializers — control exact public field set per entity.
# --------------------------------------------------------------------------

def _base(record):
    return {
        "id": record["id"],
        "created_at": fmt_dt(record["created_at"]),
        "updated_at": fmt_dt(record["updated_at"]),
        "version": record["version"],
    }


def serialize_plan(r):
    out = _base(r)
    out.update({
        "tier": r["tier"],
        "monthly_dues_cents": r["monthly_dues_cents"],
        "included_class_credits": r["included_class_credits"],
        "pt_discount_pct": r["pt_discount_pct"],
        "contract_term_months": r["contract_term_months"],
        "early_termination_fee_cents": r["early_termination_fee_cents"],
        "max_freeze_days_per_term": r["max_freeze_days_per_term"],
        "guest_passes_per_cycle": r["guest_passes_per_cycle"],
        "archived": r["archived"],
    })
    return out


def serialize_location(r):
    out = _base(r)
    out.update({
        "name": r["name"],
        "occupancy_cap": r["occupancy_cap"],
        "current_occupancy": current_occupancy(r["id"]),
    })
    return out


def serialize_member(r):
    out = _base(r)
    out.update({
        "plan_id": r["plan_id"],
        "home_location_id": r["home_location_id"],
        "full_name": r["full_name"],
        "email": r["email"],
        "membership_status": r["membership_status"],
        "dues_status": r["dues_status"],
        "class_credits_remaining": r["class_credits_remaining"],
        "guest_passes_remaining": r["guest_passes_remaining"],
        "wallet_credit_cents": r["wallet_credit_cents"],
        "cumulative_freeze_days": r["cumulative_freeze_days"],
        "past_due_since": fmt_dt(r["past_due_since"]),
        "contract_status": r["contract_status"],
        "contract_term_months": r["contract_term_months"],
        "signed_at": fmt_dt(r["signed_at"]),
        "cooling_off_ends_at": fmt_dt(r["cooling_off_ends_at"]),
        "term_ends_at": fmt_dt(r["term_ends_at"]),
    })
    return out


def serialize_class_session(r):
    out = _base(r)
    out.update({
        "location_id": r["location_id"],
        "title": r["title"],
        "starts_at": fmt_dt(r["starts_at"]),
        "ends_at": fmt_dt(r["ends_at"]),
        "capacity": r["capacity"],
        "waitlist_cap": r["waitlist_cap"],
        "status": r["status"],
        "booked_count": booked_count(r["id"]),
        "waitlisted_count": waitlisted_count(r["id"]),
    })
    return out


def serialize_booking(r):
    out = _base(r)
    out.update({
        "session_id": r["session_id"],
        "member_id": r["member_id"],
        "status": r["status"],
        "waitlist_position": waitlist_position(r),
        "credit_charged": r["credit_charged"],
        "booked_at": fmt_dt(r["booked_at"]),
    })
    return out


def serialize_pt_package(r):
    out = _base(r)
    out.update({
        "member_id": r["member_id"],
        "sessions_purchased": r["sessions_purchased"],
        "list_price_cents": r["list_price_cents"],
        "price_paid_cents": r["price_paid_cents"],
        "sessions_remaining": r["sessions_remaining"],
        "status": r["status"],
    })
    return out


def serialize_pt_session(r):
    out = _base(r)
    out.update({
        "package_id": r["package_id"],
        "trainer_name": r["trainer_name"],
        "starts_at": fmt_dt(r["starts_at"]),
        "status": r["status"],
        "deducted": r["deducted"],
    })
    return out


def serialize_dues_invoice(r):
    out = _base(r)
    out.update({
        "member_id": r["member_id"],
        "period_start": fmt_dt(r["period_start"]),
        "period_end": fmt_dt(r["period_end"]),
        "gross_amount_cents": r["gross_amount_cents"],
        "wallet_applied_cents": r["wallet_applied_cents"],
        "amount_due_cents": r["amount_due_cents"],
        "status": r["status"],
        "due_date": fmt_dt(r["due_date"]),
    })
    return out


def serialize_guest_pass(r):
    out = _base(r)
    out.update({
        "member_id": r["member_id"],
        "guest_name": r["guest_name"],
        "location_id": r["location_id"],
        "status": r["status"],
        "issued_at": fmt_dt(r["issued_at"]),
        "expires_at": fmt_dt(r["expires_at"]),
    })
    return out


def serialize_check_in(r):
    # CheckIn carries only id and created_at (PRD §2.4): no updated_at/version.
    return {
        "id": r["id"],
        "created_at": fmt_dt(r["created_at"]),
        "location_id": r["location_id"],
        "member_id": r["member_id"],
        "guest_pass_id": r["guest_pass_id"],
        "actor_kind": r["actor_kind"],
        "status": r["status"],
    }


# --------------------------------------------------------------------------
# Derived-field computations (PRD §2.6 reconciled-from-children fields).
# --------------------------------------------------------------------------

def booked_count(session_id):
    return sum(1 for b in db.store.bookings.values()
               if b["session_id"] == session_id and b["status"] == "BOOKED")


def waitlisted_count(session_id):
    return sum(1 for b in db.store.bookings.values()
               if b["session_id"] == session_id and b["status"] == "WAITLISTED")


def current_occupancy(location_id):
    return sum(1 for c in db.store.check_ins.values()
               if c["location_id"] == location_id and c["status"] == "OPEN")


def waitlist_ordered(session_id):
    """WAITLISTED bookings on a session ordered by created_at ASC (ms-total)."""
    waiting = [b for b in db.store.bookings.values()
               if b["session_id"] == session_id and b["status"] == "WAITLISTED"]
    return sorted(waiting, key=lambda b: (b["created_at"], b["_seq"]))


def waitlist_position(booking):
    """1-based rank among the session's WAITLISTED bookings (PRD §3.5)."""
    if booking["status"] != "WAITLISTED":
        return None
    ordered = waitlist_ordered(booking["session_id"])
    for idx, b in enumerate(ordered, start=1):
        if b["id"] == booking["id"]:
            return idx
    return None
