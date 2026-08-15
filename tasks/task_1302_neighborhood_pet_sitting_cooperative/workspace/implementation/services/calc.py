"""Calculation rules (scaffold §1.3): holiday-multiplier offer pricing,
provisional/final settlement variants, reliability event-wise scoring,
ledger appends with inline balance replay, overlap and threshold helpers."""

from decimal import Decimal

import clock
import db
from util import base_entity, new_id, round2, td_hours, touch

# --- Constants (scaffold §1.3) ---
MIN_DURATION_HOURS = Decimal(1)
MAX_DURATION_HOURS = Decimal(72)
MAX_OVERDRAFT_HOURS = Decimal("5.0")
JOINING_GRANT_HOURS = Decimal("10.0")
EARLY_DEPARTURE_THRESHOLD = Decimal("0.25")
EARLY_DEPARTURE_CREDIT_RATE = Decimal("0.5")
LATE_CANCEL_WINDOW_HOURS = Decimal(24)
LATE_CANCEL_PENALTY_FRACTION = Decimal("0.25")
INCIDENT_PENALTY_FRACTION = Decimal("0.5")

SCORE_INIT = 50
SCORE_SETTLE_BONUS = 2
SCORE_LATE_CANCEL = -8
SCORE_INCIDENT_AT_FAULT = -15
SCORE_ACCESS_LOST = -10
SCORE_DISPUTE_ESCALATED = -25
SCORE_MIN = 0
SCORE_MAX = 100
CLAIM_MIN_SCORE = 30


def compute_offer(start_at, end_at):
    """credit_hours_offered at posting: duration_hours * highest intersecting
    enabled holiday multiplier (no compounding), round-half-up 2dp.
    Returns (offered, multiplier)."""
    duration_hours = td_hours(end_at - start_at)
    applicable = [
        w["demand_multiplier"]
        for w in db.store["windows"].values()
        if w["enabled"] and w["window_start"] < end_at and w["window_end"] > start_at
    ]
    multiplier = max(applicable) if applicable else Decimal("1.0")
    return round2(duration_hours * multiplier), multiplier


def intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open interval overlap: [a1,b1) vs [a2,b2) overlap iff a1 < b2 and a2 < b1."""
    return a_start < b_end and b_start < a_end


def append_ledger(member, entry_type, delta, assignment_id=None, dispute_id=None, memo=""):
    """Append a CreditLedgerEntry and update the member's balance inline."""
    entry = {
        "id": new_id(),
        "created_at": clock.now(),
        "_seq": db.next_seq(),
        "member_id": member["id"],
        "entry_type": entry_type,
        "delta_hours": round2(delta),
        "sitting_assignment_id": assignment_id,
        "dispute_id": dispute_id,
        "memo": memo,
    }
    db.store["ledger"][entry["id"]] = entry
    member["credit_balance_hours"] = round2(
        member["credit_balance_hours"] + entry["delta_hours"]
    )
    touch(member)
    return entry


def adjust_reliability(member, delta):
    member["reliability_score"] = max(
        SCORE_MIN, min(SCORE_MAX, member["reliability_score"] + delta)
    )
    touch(member)


def assignment_for_request(request_id):
    for a in db.store["assignments"].values():
        if a["sitting_request_id"] == request_id:
            return a
    return None


def handoff_for_assignment(assignment_id):
    for h in db.store["handoffs"].values():
        if h["sitting_assignment_id"] == assignment_id:
            return h
    return None


def reverse_provisional(assignment):
    """Remove the provisional posting (full offer) from the sitter."""
    req = db.store["requests"].get(assignment["sitting_request_id"])
    sitter = db.store["members"].get(assignment["sitter_member_id"])
    if req is None or sitter is None:
        return
    sitter["provisional_credit_hours"] = round2(
        sitter["provisional_credit_hours"] - req["credit_hours_offered"]
    )
    touch(sitter)


def cancel_assignment(assignment, by):
    """by is 'OWNER' or 'SITTER'. Reverses the sitter's provisional hours."""
    assignment["status"] = "CANCELLED_BY_" + by
    touch(assignment)
    reverse_provisional(assignment)


def settle_assignment(assignment):
    """Final settlement variant (scaffold §1.3 sitting_credit_settlement):
    if the sitter departed early by strictly more than 25% of the scheduled
    duration, base = actual_hours * locked multiplier * 0.5; otherwise the
    full locked offer. Posts SIT_EARNED / SIT_SPENT ledger entries, reverses
    the provisional posting, and grants the settle reliability bonus."""
    req = db.store["requests"][assignment["sitting_request_id"]]
    sitter = db.store["members"][assignment["sitter_member_id"]]
    owner = db.store["members"][assignment["owner_member_id"]]

    scheduled_hours = td_hours(
        assignment["scheduled_end_at"] - assignment["scheduled_start_at"]
    )
    actual_hours = td_hours(assignment["actual_end_at"] - assignment["actual_start_at"])
    early_departure_hours = max(Decimal(0), scheduled_hours - actual_hours)
    early_fraction = (
        early_departure_hours / scheduled_hours
        if scheduled_hours > 0
        else Decimal(0)
    )
    if early_fraction > EARLY_DEPARTURE_THRESHOLD:
        base = actual_hours * req["_demand_multiplier"] * EARLY_DEPARTURE_CREDIT_RATE
    else:
        base = req["credit_hours_offered"]
    settled = round2(base)

    assignment["credit_hours_settled"] = settled
    assignment["status"] = "SETTLED"
    touch(assignment)

    append_ledger(
        sitter,
        "SIT_EARNED",
        settled,
        assignment_id=assignment["id"],
        memo=f"Hours earned for sitting assignment {assignment['id']}",
    )
    append_ledger(
        owner,
        "SIT_SPENT",
        -settled,
        assignment_id=assignment["id"],
        memo=f"Hours spent for sitting assignment {assignment['id']}",
    )
    sitter["provisional_credit_hours"] = round2(
        sitter["provisional_credit_hours"] - req["credit_hours_offered"]
    )
    touch(sitter)
    adjust_reliability(sitter, SCORE_SETTLE_BONUS)
    return settled
