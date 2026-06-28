"""Business logic: seat allocation, cascades, waitlist promotion, calculations.

Every behavior here traces to a PRD §3 sentence. The store keeps denormalized
counters (seats_reserved, waitlist_count, roster_size) reconciled with the rows
they summarize, within the single triggering request (PRD §2.5).
"""
from datetime import timedelta

from clock import clock
from db import db
from helpers import (
    parse_iso,
    add_months,
    ceil_days,
    LATE_CANCEL_WINDOW_HOURS,
)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def session_starts_at(session):
    return parse_iso(session["starts_at"])


# ---------------------------------------------------------------------------
# Waitlist promotion (PRD §3.4) — the closing step of cancel/freeze cascade.
# ---------------------------------------------------------------------------
def _waitlisted_of(session_id):
    return [
        r for r in db.reservations.values()
        if r["session_id"] == session_id and r["status"] == "WAITLISTED"
    ]


def _renumber_waitlist(session_id):
    """Renumber remaining WAITLISTED reservations contiguous from 1, ordered by
    waitlist_position then created order."""
    wl = _waitlisted_of(session_id)
    wl.sort(key=lambda r: (r.get("waitlist_position") or 0, r["_seq"]))
    for i, r in enumerate(wl, start=1):
        if r["waitlist_position"] != i:
            r["waitlist_position"] = i


def promote_waitlist_head(session):
    """Promote the head of this session's waitlist if a seat is open.

    Candidate: WAITLISTED reservation with lowest waitlist_position (ties broken
    by earliest created_at). Proceeds only while seats_reserved < capacity after
    the freeing event. Applies the deferred seat cost.
    """
    if session["seats_reserved"] >= session["capacity"]:
        return None
    wl = _waitlisted_of(session["id"])
    if not wl:
        return None
    wl.sort(key=lambda r: (r.get("waitlist_position") or 0, r["_seq"]))
    head = wl[0]

    head["status"] = "RESERVED"
    head["waitlist_position"] = None
    db.touch(head)

    session["seats_reserved"] += 1
    session["waitlist_count"] -= 1

    # Apply the deferred seat cost.
    if head["reservation_kind"] == "MEMBERSHIP":
        membership = db.memberships.get(head["membership_id"])
        if membership is not None and membership.get("punches_remaining") is not None:
            membership["punches_remaining"] -= 1
            head["punch_consumed"] = True
            db.touch(membership)
    elif head["reservation_kind"] == "DROP_IN":
        head["drop_in_fee_charged_cents"] = session["drop_in_fee_cents"]

    # Renumber remaining waitlisted reservations contiguous from 1.
    _renumber_waitlist(session["id"])
    return head


# ---------------------------------------------------------------------------
# Membership cascades (PRD §3.2, §3.3)
# ---------------------------------------------------------------------------
def cascade_cancel_future_reserved(membership):
    """Every reservation this membership holds on a future, still-SCHEDULED
    session in RESERVED status is transitioned RESERVED->CANCELLED; each such
    cancellation decrements that session's seats_reserved and promotes the head
    of that session's waitlist.

    This is the freeze / active-cancel cascade. Frozen/cancelled-by-membership
    reservations restore punch and refund fee (the seat is released by the box-
    side action, not a member late-cancel forfeit)."""
    now = clock.now()
    affected = [
        r for r in db.reservations.values()
        if r.get("membership_id") == membership["id"] and r["status"] == "RESERVED"
    ]
    # Stable order for determinism.
    affected.sort(key=lambda r: r["_seq"])
    for r in affected:
        session = db.sessions.get(r["session_id"])
        if session is None:
            continue
        if session["status"] != "SCHEDULED":
            continue
        if session_starts_at(session) <= now:
            continue  # not a future session
        # Cancel + free seat + promote.
        r["status"] = "CANCELLED"
        r["waitlist_position"] = None
        db.touch(r)
        session["seats_reserved"] -= 1
        if r.get("punch_consumed"):
            if membership.get("punches_remaining") is not None:
                membership["punches_remaining"] += 1
            r["punch_consumed"] = False
        if r.get("drop_in_fee_charged_cents"):
            r["drop_in_fee_charged_cents"] = 0
        promote_waitlist_head(session)
        db.touch(session)


# ---------------------------------------------------------------------------
# Calculations (PRD §3)
# ---------------------------------------------------------------------------
def compute_cancellation_fee(membership, plan):
    """§3.3 cancellation_fee.

    if commitment_months == 0: 0
    elif now < commitment_end_date: plan.early_termination_fee_cents
    else: 0
    """
    if plan["commitment_months"] == 0:
        return 0
    end = membership.get("commitment_end_date")
    if end is None:
        return 0
    now = clock.now()
    if now < parse_iso(end):
        return plan["early_termination_fee_cents"]
    return 0


def refund_on_cancel(reservation, session, membership):
    """§3.5 / refund_on_cancel. Member-initiated cancel of a RESERVED reservation.

    hours_before = (starts_at - now) / 1 hour
    < LATE_CANCEL_WINDOW_HOURS -> late: forfeit (no punch restore, no refund)
    >= LATE_CANCEL_WINDOW_HOURS -> timely: restore punch, refund drop-in fee
    Boundary == 12h is timely.
    """
    now = clock.now()
    starts = session_starts_at(session)
    hours_before = (starts - now).total_seconds() / 3600.0
    if hours_before < LATE_CANCEL_WINDOW_HOURS:
        # late cancel: forfeit
        return
    # timely cancel
    if reservation.get("punch_consumed"):
        if membership is not None and membership.get("punches_remaining") is not None:
            membership["punches_remaining"] += 1
            db.touch(membership)
        reservation["punch_consumed"] = False
    if reservation.get("drop_in_fee_charged_cents"):
        reservation["drop_in_fee_charged_cents"] = 0


def compute_is_pr(result):
    """§3.6 pr_determination. Only VERIFIED results compete. Strict comparison."""
    prior = [
        r for r in db.benchmark_results.values()
        if r["member_id"] == result["member_id"]
        and r["benchmark_name"] == result["benchmark_name"]
        and r["verified"] is True
        and r["id"] != result["id"]
    ]
    if not prior:
        return True
    if result["metric_kind"] == "TIME_SECONDS":
        best_prior = min(r["value"] for r in prior)
        return result["value"] < best_prior
    else:  # LOAD_KG
        best_prior = max(r["value"] for r in prior)
        return result["value"] > best_prior


# ---------------------------------------------------------------------------
# Membership activation helpers
# ---------------------------------------------------------------------------
def activate_membership(membership, plan):
    now = clock.now()
    membership["status"] = "ACTIVE"
    membership["contract_start_date"] = _iso(now)
    membership["commitment_end_date"] = _iso(add_months(now, plan["commitment_months"]))
    if plan["plan_type"] == "PUNCH":
        membership["punches_remaining"] = plan["punch_count"]
    # UNLIMITED: punches_remaining stays null
    db.touch(membership)


def _iso(dt):
    from response import iso_ms
    return iso_ms(dt)


def unfreeze_membership(membership):
    now = clock.now()
    started = parse_iso(membership["freeze_started_at"])
    frozen_days = ceil_days(now - started)
    membership["total_frozen_days"] = membership.get("total_frozen_days", 0) + frozen_days
    if membership.get("commitment_end_date") is not None:
        end = parse_iso(membership["commitment_end_date"])
        membership["commitment_end_date"] = _iso(end + timedelta(days=frozen_days))
    membership["freeze_started_at"] = None
    membership["status"] = "ACTIVE"
    db.touch(membership)
