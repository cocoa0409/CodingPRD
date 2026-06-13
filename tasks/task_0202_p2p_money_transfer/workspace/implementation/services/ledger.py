"""Ledger postings, balance derivation, held-balance, risk scoring, default-payout.

Balance is ALWAYS derived from the append-only ledger (PRD §2.6), never stored as
a mutable counter. available_balance = settled_credits - settled_debits - held.
"""
import models
from db import db

# risk deltas (scaffold risk_score_update)
RISK_BLOCK_DELTA = 20
RISK_CHARGEBACK_DELTA = 35
RISK_DENIED_DELTA = -10


def post_ledger(account_id, direction, amount_cents, source_kind, source_ref_id, memo=""):
    """Append an immutable LedgerEntry (lean record: id + created_at only)."""
    entry = {
        "account_id": account_id,
        "direction": direction,          # CREDIT | DEBIT
        "amount_cents": amount_cents,
        "source_kind": source_kind,      # TRANSFER | WITHDRAWAL | REVERSAL | ADJUSTMENT
        "source_ref_id": source_ref_id,
        "memo": memo,
    }
    models._stamp_lean(entry)
    db.ledger_entries[entry["id"]] = entry
    return entry


def _settled_balance(account_id):
    """Sum of CREDIT minus DEBIT over all ledger postings for the account."""
    total = 0
    for e in db.ledger_entries.values():
        if e["account_id"] != account_id:
            continue
        if e["direction"] == "CREDIT":
            total += e["amount_cents"]
        else:
            total -= e["amount_cents"]
    return total


def compute_held(account_id):
    """held_balance = sum(amount of this account's HELD transfers as sender)
    + sum(gross of this account's REQUESTED withdrawals not yet paid out).
    """
    held = 0
    for t in db.transfers.values():
        if t["sender_account_id"] == account_id and t["status"] == "HELD":
            held += t["amount_cents"]
    for w in db.withdrawals.values():
        if w["account_id"] == account_id and w["status"] == "REQUESTED":
            held += w["gross_amount_cents"]
    return held


def recompute_account(account):
    """Recompute available_balance_cents and held_balance_cents from the ledger.

    The economic effect of holding funds is realized through the DEBIT posting that
    fires when a transfer is HELD or a withdrawal is REQUESTED (PRD §3.3/§3.9): those
    debits already lower the settled ledger total. So available is simply the running
    ledger balance (settled credits - settled debits), floored at 0, and held_balance
    is reported separately as the still-reserved magnitude. Subtracting held again
    would double-count it (e.g. seed 10000, hold 6000 -> debit makes settled 4000;
    available must read 4000 with held 6000, not -2000).
    """
    held = compute_held(account["id"])
    available = _settled_balance(account["id"])
    if available < 0:
        available = 0
    account["held_balance_cents"] = held
    account["available_balance_cents"] = available


def derive_tier(score):
    if score < 30:
        return "LOW"
    if score <= 69:
        return "ELEVATED"
    return "HIGH"


def adjust_risk(account, delta):
    """Additive risk delta clamped to [0,100]; re-derive tier. Bumps version."""
    new = account["risk_score"] + delta
    new = max(0, min(100, new))
    account["risk_score"] = new
    account["risk_tier"] = derive_tier(new)


def recompute_default_payout(account_id):
    """Earliest-VERIFIED FundingSource (created_at ASC, never id) gets is_default_payout."""
    candidates = [
        fs for fs in db.funding_sources.values()
        if fs["account_id"] == account_id and fs["status"] == "VERIFIED"
    ]
    chosen_id = None
    if candidates:
        chosen = min(candidates, key=lambda f: (f["created_at"], f["_seq"]))
        chosen_id = chosen["id"]
    for fs in db.funding_sources.values():
        if fs["account_id"] != account_id:
            continue
        new_flag = fs["id"] == chosen_id
        if fs.get("is_default_payout") != new_flag:
            fs["is_default_payout"] = new_flag
            models.touch(fs)
