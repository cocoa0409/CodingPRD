"""Bucket credit ledger (calculation `bucket_credit_ledger`, PRD §2.8).

Invariant: balance == granted - redeemed - expired at all times.
The ledger tracks each grant event with its remaining amount for FIFO
redemption and expiry (oldest grant consumed first; ties by drop
created_at ASC).
"""

from datetime import timedelta

import db

CREDIT_TTL_DAYS = 365


def record_grant(participant_id, amount, occurred_at, drop_created_at, drop_id):
    """Record a credit grant in the FIFO ledger (amount may be negative for
    reconciliation deltas — negative amounts reduce the oldest outstanding
    grant remainders, i.e. reverse prior grants FIFO)."""
    if amount == 0:
        return
    participant = db.participants[participant_id]
    if amount > 0:
        db.credit_ledger.append({
            "participant_id": participant_id,
            "amount": amount,
            "remaining": amount,
            "occurred_at": occurred_at,
            "created_at": drop_created_at,
            "drop_id": drop_id,
        })
        participant["bucket_credits_granted_total"] += amount
        participant["bucket_credit_balance"] += amount
    else:
        # Negative delta: reverse prior grants FIFO (oldest first)
        to_reverse = -amount
        entries = _sorted_entries(participant_id)
        for entry in entries:
            if to_reverse <= 0:
                break
            if entry["remaining"] <= 0:
                continue
            take = min(entry["remaining"], to_reverse)
            entry["remaining"] -= take
            to_reverse -= take
        participant["bucket_credits_granted_total"] += amount  # amount is negative
        participant["bucket_credit_balance"] += amount


def _sorted_entries(participant_id):
    entries = [e for e in db.credit_ledger if e["participant_id"] == participant_id]
    entries.sort(key=lambda e: (e["occurred_at"], e["created_at"]))
    return entries


def redeem(participant_id, credits):
    """Consume credits FIFO for a redemption. Returns nothing; caller has
    already validated affordability."""
    participant = db.participants[participant_id]
    participant["bucket_credits_redeemed_total"] += credits
    participant["bucket_credit_balance"] -= credits
    # Consume ledger FIFO
    to_consume = credits
    for entry in _sorted_entries(participant_id):
        if to_consume <= 0:
            break
        if entry["remaining"] <= 0:
            continue
        take = min(entry["remaining"], to_consume)
        entry["remaining"] -= take
        to_consume -= take


def refund(participant_id, credits):
    """Refund redeemed credits (allocation cancel) — restores balance without
    counting a redemption. Credits go back onto the oldest consumed entries
    first (restore FIFO order)."""
    participant = db.participants[participant_id]
    participant["bucket_credits_redeemed_total"] -= credits
    participant["bucket_credit_balance"] += credits
    # Restore to oldest entries with consumed amounts
    to_restore = credits
    for entry in _sorted_entries(participant_id):
        if to_restore <= 0:
            break
        capacity = entry["amount"] - entry["remaining"]
        if capacity <= 0:
            continue
        give = min(capacity, to_restore)
        entry["remaining"] += give
        to_restore -= give


def expire_for_participant(participant_id):
    """Ops-run credit expiry: credits granted > 365 days ago (by granting
    drop's occurred_at) and not yet redeemed expire."""
    now = db.clock_now()
    cutoff = now - timedelta(days=CREDIT_TTL_DAYS)
    expired_total = 0
    for entry in _sorted_entries(participant_id):
        if entry["remaining"] <= 0:
            continue
        if entry["occurred_at"] < cutoff or (now - entry["occurred_at"]) > timedelta(days=CREDIT_TTL_DAYS):
            expired_total += entry["remaining"]
            entry["remaining"] = 0
    if expired_total:
        participant = db.participants[participant_id]
        participant["bucket_credits_expired_total"] += expired_total
        participant["bucket_credit_balance"] -= expired_total
    return expired_total


def expire_all_balance(participant_id):
    """Participant deactivation: fold entire balance into expired total."""
    participant = db.participants[participant_id]
    bal = participant["bucket_credit_balance"]
    if bal > 0:
        participant["bucket_credits_expired_total"] += bal
        participant["bucket_credit_balance"] = 0
        for entry in _sorted_entries(participant_id):
            entry["remaining"] = 0
    return bal
