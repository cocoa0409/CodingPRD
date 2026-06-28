"""Loyalty point movements, ledger writes, and tier recompute.

PRD §3.1: point_balance is spendable; lifetime_points_earned is monotone on
earn, reduced only by reversal of an earned credit; tier recomputed whenever
lifetime_points_earned changes. Every point movement writes an immutable
LoyaltyLedgerEntry (id + created_at only) carrying member_id, entry_type
(EARN | REDEEM | REVERSAL), signed points_delta, source_ref_type
(VISIT | ENROLLMENT | BOOKING) and source_ref_id.
"""

from clock import clock
from db import db, new_id
from services import calculations


def append_ledger(member_id, entry_type, points_delta, source_ref_type, source_ref_id):
    entry = {
        "id": new_id(),
        "member_id": member_id,
        "entry_type": entry_type,
        "points_delta": points_delta,
        "source_ref_type": source_ref_type,
        "source_ref_id": source_ref_id,
        "created_at": clock.now_iso(),
        "_seq": db.next_seq(),
    }
    db.ledger_entries[entry["id"]] = entry
    return entry


def recompute_tier(member):
    member["tier"] = calculations.member_tier(member["lifetime_points_earned"])


def credit_earn(member, points, source_ref_type, source_ref_id):
    """EARN: add to both point_balance and lifetime_points_earned, recompute tier,
    append an EARN ledger entry. Only called when points > 0."""
    if points <= 0:
        return None
    member["point_balance"] += points
    member["lifetime_points_earned"] += points
    recompute_tier(member)
    return append_ledger(member["id"], "EARN", points, source_ref_type, source_ref_id)


def debit_redeem(member, points, source_ref_type, source_ref_id):
    """REDEEM: subtract points from point_balance (NOT lifetime), append a REDEEM
    ledger entry for the negative amount. Only called when points > 0."""
    if points <= 0:
        return None
    member["point_balance"] -= points
    return append_ledger(member["id"], "REDEEM", -points, source_ref_type, source_ref_id)


def reverse_earn(member, points, source_ref_type, source_ref_id):
    """REVERSAL: claw back a previously credited earn from both counters,
    recompute tier, append a REVERSAL ledger entry for the negative amount."""
    if points <= 0:
        return None
    member["point_balance"] -= points
    member["lifetime_points_earned"] -= points
    recompute_tier(member)
    return append_ledger(member["id"], "REVERSAL", -points, source_ref_type, source_ref_id)
