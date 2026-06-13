"""Business logic: calculations, state transitions, cascades (§1.3, §3)."""

import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from models import next_seq, touch, recompute_credit_balance

# --- Calculation constants (§1.3) -------------------------------------------
LATE_CANCEL_BASE_CENTS = 1500
NO_SHOW_BASE_CENTS = 2500
TIER2_SURCHARGE_CENTS = 1000
TIER3_SURCHARGE_CENTS = 2500
INSTRUCTOR_TRAVEL_BUFFER_MIN = 30
ROOM_CLEANING_BUFFER_MIN = 15
NO_SHOW_BLOCK_THRESHOLD = 3
STRIKE_WINDOW_DAYS = 30
CHECKIN_LEAD_HOURS = 2


# --- Wallet ledger ----------------------------------------------------------

def append_wallet_entry(membership_id, kind, delta, note, reservation_id=None):
    rec = {
        "id": db.new_id(),
        "_seq": next_seq(),
        "created_at": db.utcnow(),
        "membership_id": membership_id,
        "reservation_id": reservation_id,
        "kind": kind,
        "delta": delta,
        "note": note,
    }
    db.wallet_entries[rec["id"]] = rec
    recompute_credit_balance(membership_id)
    return rec


# --- Strikes & standing (§3.7, §1.3 member_standing_strike) -----------------

def recompute_standing(member_id):
    """no_show_strikes = count of ASSESSED fees in trailing STRIKE_WINDOW_DAYS."""
    member = db.members[member_id]
    now = db.now_clock()
    window_start = now - timedelta(days=STRIKE_WINDOW_DAYS)
    count = 0
    for f in db.fee_charges.values():
        if f["member_id"] != member_id:
            continue
        if f["status"] != "ASSESSED":
            continue
        if f["_event_clock"] >= window_start:
            count += 1
    member["no_show_strikes"] = count
    member["standing"] = "RESTRICTED" if count >= NO_SHOW_BLOCK_THRESHOLD else "GOOD"
    touch(member)


# --- Fee assessment (§1.3 late_fee_assessment, §3.8) ------------------------

def assess_fee(member_id, reservation_id, kind, credit_refunded):
    """Create a FeeCharge using the member's strike count BEFORE this event.

    Returns the fee amount in cents. Increments the member's strike via standing
    recompute after the fee row exists (the new ASSESSED row counts itself).
    """
    member = db.members[member_id]
    prior_strikes = member["no_show_strikes"]
    base = LATE_CANCEL_BASE_CENTS if kind == "LATE_CANCEL" else NO_SHOW_BASE_CENTS
    if prior_strikes <= 1:
        surcharge = 0
    elif prior_strikes <= 3:
        surcharge = TIER2_SURCHARGE_CENTS
    else:
        surcharge = TIER3_SURCHARGE_CENTS
    amount = base + surcharge

    ts = db.utcnow()
    fee = {
        "id": db.new_id(),
        "_seq": next_seq(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "member_id": member_id,
        "reservation_id": reservation_id,
        "kind": kind,
        "amount_cents": amount,
        "status": "ASSESSED",
        "credit_refunded": credit_refunded,
        # Clock snapshot used for the trailing-window strike computation.
        "_event_clock": db.now_clock(),
    }
    db.fee_charges[fee["id"]] = fee
    # Recompute strikes/standing now that the ASSESSED fee row exists.
    recompute_standing(member_id)
    return fee


# --- Waitlist auto-promotion (§1.3 waitlist_promotion, §3.7) -----------------

def waitlist_candidates(session_id):
    cands = [
        r for r in db.reservations.values()
        if r["session_id"] == session_id and r["booking_status"] == "WAITLISTED"
    ]
    cands.sort(key=lambda r: r["_seq"])  # created_at ASC, never by id
    return cands


def recompute_waitlist_positions(session_id):
    cands = waitlist_candidates(session_id)
    for idx, r in enumerate(cands, start=1):
        r["waitlist_position"] = idx
        touch(r)


def recompute_session_counts(session_id):
    sess = db.class_sessions[session_id]
    booked = sum(
        1 for r in db.reservations.values()
        if r["session_id"] == session_id and r["booking_status"] == "BOOKED"
    )
    waitlisted = sum(
        1 for r in db.reservations.values()
        if r["session_id"] == session_id and r["booking_status"] == "WAITLISTED"
    )
    sess["booked_count"] = booked
    sess["waitlisted_count"] = waitlisted


def run_promotion(session_id):
    """Fill freed seats from the waitlist in created_at order (§3.7).

    Walks the head of the waitlist for each free seat: promotes a payable head
    (active membership + sufficient credit), or releases an unpayable head and
    proceeds to the next in line. Recomputes counts/positions/status afterward.
    The session itself is NOT version-bumped here (promotion is a system action
    folded into the triggering request's own mutations).
    """
    sess = db.class_sessions[session_id]
    template = db.class_templates[sess["template_id"]]
    cost = template["credit_cost"]

    candidates = waitlist_candidates(session_id)
    free_seats = sess["seat_capacity"] - sess["booked_count"]

    for _ in range(max(0, free_seats)):
        promoted = False
        while candidates and not promoted:
            head = candidates.pop(0)
            membership = db.memberships.get(head["membership_id"])
            if (membership and membership["status"] == "ACTIVE"
                    and membership["credit_balance"] >= cost):
                append_wallet_entry(
                    membership["id"], "RESERVE_DEBIT", -cost,
                    "Seat reserved via waitlist promotion",
                    reservation_id=head["id"],
                )
                head["booking_status"] = "BOOKED"
                head["credits_charged"] = cost
                head["promoted_at"] = db.now_clock()
                head["waitlist_position"] = 0
                touch(head)
                sess["booked_count"] += 1
                promoted = True
            else:
                # Head cannot pay -> release and skip to next in line.
                head["booking_status"] = "RELEASED"
                head["attendance_status"] = "CANCELLED"
                head["waitlist_position"] = 0
                touch(head)

    recompute_session_counts(session_id)
    recompute_waitlist_positions(session_id)
    if sess["status"] in ("OPEN", "FULL"):
        sess["status"] = "FULL" if sess["booked_count"] == sess["seat_capacity"] else "OPEN"


# --- Cancellation refund (§1.3 cancellation_refund, §3.4) -------------------

def compute_cancellation_refund(membership):
    plan = db.package_plans[membership["plan_id"]]
    if plan["kind"] in ("INTRO", "CREDIT_PACK"):
        return 0
    cycle_len = plan["validity_days"]
    elapsed_days = math.floor(
        (db.now_clock() - membership["cycle_start"]).total_seconds() / 86400.0
    ) - membership["freeze_days_used"]
    remaining_days = max(0, cycle_len - elapsed_days)
    # Full-precision ratio, single final round_half_up.
    ratio = Decimal(remaining_days) / Decimal(cycle_len)
    refund = (Decimal(plan["price_cents"]) * ratio).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(refund)


def forfeit_credits(membership, note="Credits forfeited"):
    balance = membership["credit_balance"]
    if balance > 0:
        append_wallet_entry(
            membership["id"], "EXPIRY_FORFEIT", -balance, note,
        )
    recompute_credit_balance(membership["id"])
