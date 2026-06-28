"""Cascading side effects: capacity release, lapse/cancel cascades, waitlist
promotion (PRD §2.5, §3.2, §3.5).

A unifying rule (PRD §2.5): when one operation mutates several entities, EVERY
affected entity has its updated_at refreshed and version incremented.
"""
from db import db, now
from services.common import touch
from services import calc


def release_slot_capacity(slot, heads):
    """Release `heads` from a slot's held_count; reopen if it dips below capacity.

    Bumps the slot's version/updated_at (PRD §2.5).
    """
    slot["held_count"] = slot["held_count"] - heads
    if slot["held_count"] < slot["capacity"] and slot["status"] == "CLOSED":
        slot["status"] = "OPEN"
    touch(slot)


def add_slot_capacity(slot, heads):
    """Add `heads` to a slot's held_count; close it if it reaches capacity."""
    slot["held_count"] = slot["held_count"] + heads
    if slot["held_count"] >= slot["capacity"]:
        slot["status"] = "CLOSED"
    touch(slot)


def promote_head_waitlister(session):
    """Promote the rank-1 WAITLISTED registration of a session to ENROLLED.

    Allowed when a rank-1 waitlister exists and enrolled_count < capacity after
    the vacating withdrawal. On promotion: status ENROLLED, waitlist_rank 0,
    enrolled_count += 1, remaining waitlisted each drop one rank, tuition charged
    under the member-discount rule (PRD §3.5). Bumps session + promoted reg.
    """
    if session["enrolled_count"] >= session["capacity"]:
        return None
    waitlisted = [r for r in db.registrations.values()
                  if r["program_session_id"] == session["id"]
                  and r["status"] == "WAITLISTED"]
    if not waitlisted:
        return None
    head = min(waitlisted, key=lambda r: r["waitlist_rank"])
    if head["waitlist_rank"] != 1:
        # Defensive: ranks should be contiguous from 1, but guard anyway.
        return None

    # Promote.
    head["status"] = "ENROLLED"
    head["waitlist_rank"] = 0
    head["charged_cents"] = _tuition_for(head, session)
    touch(head)

    session["enrolled_count"] = session["enrolled_count"] + 1
    touch(session)

    # Re-rank remaining waitlisted of this session (each rank -= 1).
    for r in db.registrations.values():
        if (r["program_session_id"] == session["id"]
                and r["status"] == "WAITLISTED"):
            r["waitlist_rank"] = r["waitlist_rank"] - 1
            touch(r)
    return head


def rerank_after_waitlist_removal(session, removed_rank):
    """Re-rank waitlisted registrations of a session below `removed_rank`."""
    for r in db.registrations.values():
        if (r["program_session_id"] == session["id"]
                and r["status"] == "WAITLISTED"
                and r["waitlist_rank"] > removed_rank):
            r["waitlist_rank"] = r["waitlist_rank"] - 1
            touch(r)


def _tuition_for(reg, session):
    membership_id = reg["membership_id"]
    applies = False
    discount_pct = 0
    if membership_id:
        m = db.memberships.get(membership_id)
        if m is not None and m["status"] == "ACTIVE":
            plan = db.membership_plans.get(m["plan_id"])
            if plan is not None:
                applies = True
                discount_pct = plan["program_discount_pct"]
    return calc.program_tuition_charge(session["tuition_cents"], applies, discount_pct)


def withdraw_enrolled_registration(reg):
    """Withdraw an ENROLLED registration: dec enrolled_count, promote head."""
    session = db.program_sessions.get(reg["program_session_id"])
    reg["status"] = "WITHDRAWN"
    touch(reg)
    if session is not None:
        session["enrolled_count"] = session["enrolled_count"] - 1
        touch(session)
        promote_head_waitlister(session)


def cancel_held_reservation_for_cascade(res):
    """Cancel a HELD reservation during a membership cascade.

    Releases party_size from the slot's held_count. (Lapse/cancel cascades do
    not refund guest passes — guest_passes_remaining is zeroed wholesale.)
    """
    res["status"] = "CANCELLED"
    touch(res)
    slot = db.time_slots.get(res["time_slot_id"])
    if slot is not None:
        release_slot_capacity(slot, res["party_size"])


def lapse_membership(membership):
    """ACTIVE -> LAPSED with the full cascade (PRD §2.5, §3.2).

    - Every HELD reservation owned by this membership whose slot start is at or
      after now -> CANCELLED, releasing held_count.
    - Every ENROLLED future registration owned by this membership -> WITHDRAWN,
      decrementing enrolled_count and promoting the head waitlister.
    - guest_passes_remaining -> 0.
    """
    current = now()
    membership["status"] = "LAPSED"

    # Cascade HELD reservations whose slot has not yet started.
    for res in list(db.reservations.values()):
        if (res["membership_id"] == membership["id"]
                and res["status"] == "HELD"):
            slot = db.time_slots.get(res["time_slot_id"])
            if slot is not None and slot["starts_at"] >= current:
                cancel_held_reservation_for_cascade(res)

    # Cascade ENROLLED future registrations.
    for reg in list(db.registrations.values()):
        if (reg["membership_id"] == membership["id"]
                and reg["status"] == "ENROLLED"):
            session = db.program_sessions.get(reg["program_session_id"])
            if session is not None and session["starts_at"] >= current:
                withdraw_enrolled_registration(reg)

    membership["guest_passes_remaining"] = 0
    touch(membership)


def cancel_membership(membership):
    """PENDING/ACTIVE/LAPSED -> CANCELLED with cascade (PRD §3.2).

    Cancels every HELD reservation owned by the membership (releasing held_count)
    and sets guest_passes_remaining to 0.
    """
    membership["status"] = "CANCELLED"
    for res in list(db.reservations.values()):
        if (res["membership_id"] == membership["id"]
                and res["status"] == "HELD"):
            cancel_held_reservation_for_cascade(res)
    membership["guest_passes_remaining"] = 0
    touch(membership)
