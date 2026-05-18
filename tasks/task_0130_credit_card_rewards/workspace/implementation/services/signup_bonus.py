"""Signup-bonus qualification.

PRD §3.1 and scaffold calc_signup_bonus_qualification: window is the half-open
interval [opened_at, signup_bonus_deadline_at). Inside-window purchases add and
inside-window refunds subtract. Boundary >= 300_000 cents triggers QUALIFIED ->
AWARDED. If pending past deadline, transition to EXPIRED.
"""
from __future__ import annotations

from constants import SIGNUP_BONUS_POINTS, SIGNUP_MIN_SPEND_CENTS
from store import store
from utils import parse_iso


def recompute_qualifying_spend(account: dict) -> int:
    """Return the qualifying spend total (purchases - refunds) inside the
    signup window. Updates account['signup_bonus_qualifying_spend_cents'].
    """
    opened_at = parse_iso(account["opened_at"])
    deadline = parse_iso(account["signup_bonus_deadline_at"])
    aid = account["id"]

    purchases = 0
    refunds = 0
    for t in store.transactions.values():
        if t["account_id"] != aid:
            continue
        if t["status"] != "POSTED":
            continue
        posted_at = parse_iso(t["posted_at"])
        if not (opened_at <= posted_at < deadline):
            continue
        if t["txn_type"] == "PURCHASE":
            purchases += int(t["amount_cents"])
        elif t["txn_type"] == "REFUND":
            refunds += int(t["amount_cents"])

    qualifying = purchases - refunds
    account["signup_bonus_qualifying_spend_cents"] = qualifying
    return qualifying


def evaluate_qualification(account: dict) -> bool:
    """Run the signup-bonus state machine for `account`. Returns True if an
    AWARDED transition fired (caller should refresh balance).

    Pre-PENDING accounts are skipped.
    """
    from services.ledger import append_entry, recompute_balance

    if account["signup_bonus_state"] != "PENDING":
        return False

    qualifying = recompute_qualifying_spend(account)
    if qualifying >= SIGNUP_MIN_SPEND_CENTS:
        # PENDING -> QUALIFIED -> AWARDED (collapsed in one step per scaffold)
        account["signup_bonus_state"] = "AWARDED"
        append_entry(
            account_id=account["id"],
            entry_type="SIGNUP_BONUS",
            delta_points=SIGNUP_BONUS_POINTS,
            source_entity_type="Account",
            source_entity_id=account["id"],
        )
        recompute_balance(account)
        return True

    # If past deadline and not yet qualified, expire.
    deadline = parse_iso(account["signup_bonus_deadline_at"])
    now = store.now()
    if now >= deadline:
        account["signup_bonus_state"] = "EXPIRED"
        return False

    return False


def expire_unqualified_if_past_deadline(account: dict) -> bool:
    """Sweep-style helper: PENDING -> EXPIRED if now >= deadline."""
    if account["signup_bonus_state"] != "PENDING":
        return False
    deadline = parse_iso(account["signup_bonus_deadline_at"])
    if store.now() >= deadline:
        account["signup_bonus_state"] = "EXPIRED"
        return True
    return False
