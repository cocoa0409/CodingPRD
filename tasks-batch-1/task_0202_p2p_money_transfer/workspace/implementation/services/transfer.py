"""Transfer lifecycle: limit pre-flight, risk gate, settle/hold branches.

Shared by direct sends, money-request pay, and split-share pay.
"""
from datetime import timedelta

import models
from db import db
from errors import err
from services import ledger

# risk gate thresholds (scaffold transfer_risk_gate)
LARGE_AMOUNT_THRESHOLD_CENTS = 100000
UNVERIFIED_RECIPIENT_CAP_CENTS = 5000

DAILY_WINDOW_HOURS = 24
WEEKLY_WINDOW_DAYS = 7


def _window_usage(sender_id, since):
    """Sum amount_cents of sender's transfers in {SENT,HELD,SETTLED} with created_at >= since."""
    total = 0
    for t in db.transfers.values():
        if t["sender_account_id"] != sender_id:
            continue
        if t["status"] not in ("SENT", "HELD", "SETTLED"):
            continue
        if t["created_at"] >= since:
            total += t["amount_cents"]
    return total


def limit_check(sender, amount_cents):
    """Raise ERR_DAILY/WEEKLY_LIMIT_EXCEEDED if amount exceeds the binding window.

    A send of exactly the effective headroom is allowed; one cent over is rejected.
    Binding window for the error: daily if daily_remaining <= weekly_remaining else weekly.
    """
    now = db.now()
    daily_since = now - timedelta(hours=DAILY_WINDOW_HOURS)
    weekly_since = now - timedelta(days=WEEKLY_WINDOW_DAYS)
    daily_used = _window_usage(sender["id"], daily_since)
    weekly_used = _window_usage(sender["id"], weekly_since)
    daily_remaining = sender["daily_send_limit_cents"] - daily_used
    weekly_remaining = sender["weekly_send_limit_cents"] - weekly_used
    effective_remaining = min(daily_remaining, weekly_remaining)
    if amount_cents <= effective_remaining:
        return
    if daily_remaining <= weekly_remaining:
        raise err("ERR_DAILY_LIMIT_EXCEEDED", "Daily send limit exceeded.")
    raise err("ERR_WEEKLY_LIMIT_EXCEEDED", "Weekly send limit exceeded.")


def risk_gate(sender, recipient, amount_cents):
    """Return (route, reason_code). route is 'SETTLE' or 'HOLD'. First match wins."""
    if sender["risk_tier"] == "HIGH":
        return "HOLD", "HIGH_TIER"
    if amount_cents >= LARGE_AMOUNT_THRESHOLD_CENTS:
        return "HOLD", "LARGE_AMOUNT"
    if (not recipient["is_recipient_verified"]) and amount_cents > UNVERIFIED_RECIPIENT_CAP_CENTS:
        return "HOLD", "UNVERIFIED_RECIPIENT"
    return "SETTLE", None


def create_transfer(sender, recipient, amount_cents, memo="", source_money_request_id=None):
    """Run the full send pathway (post limit/funds/frozen/self checks done by caller's
    validation ordering — caller passes already-validated entities).

    Performs limit_check, insufficient-funds, then risk gate + branch side effects.
    Returns the created Transfer dict.
    """
    # ordering per PRD §2.5: self/frozen handled by caller before this; here:
    # (13/14) daily/weekly limit, then (15) funds.
    limit_check(sender, amount_cents)
    if sender["available_balance_cents"] < amount_cents:
        raise err("ERR_INSUFFICIENT_FUNDS", "Insufficient funds.")

    route, reason_code = risk_gate(sender, recipient, amount_cents)

    transfer = {
        "sender_account_id": sender["id"],
        "recipient_account_id": recipient["id"],
        "amount_cents": amount_cents,
        "memo": memo if memo is not None else "",
        "status": "SENT",
        "risk_flagged": False,
        "hold_id": None,
        "source_money_request_id": source_money_request_id,
        "settled_at": None,
    }
    models._stamp_create(transfer)
    db.transfers[transfer["id"]] = transfer

    if route == "SETTLE":
        _settle_new(transfer, sender, recipient)
    else:
        _hold_new(transfer, sender, recipient, reason_code)
    return transfer


def _settle_new(transfer, sender, recipient):
    transfer["settled_at"] = db.now()
    transfer["status"] = "SETTLED"
    models.touch(transfer)
    ledger.post_ledger(sender["id"], "DEBIT", transfer["amount_cents"],
                       "TRANSFER", transfer["id"], "transfer out")
    ledger.post_ledger(recipient["id"], "CREDIT", transfer["amount_cents"],
                       "TRANSFER", transfer["id"], "transfer in")
    ledger.recompute_account(sender)
    ledger.recompute_account(recipient)
    models.touch(sender)
    models.touch(recipient)


def _hold_new(transfer, sender, recipient, reason_code):
    transfer["risk_flagged"] = True
    transfer["status"] = "HELD"
    # debit sender now; funds move from available to held. Recipient NOT credited.
    ledger.post_ledger(sender["id"], "DEBIT", transfer["amount_cents"],
                       "TRANSFER", transfer["id"], "transfer held")
    hold = {
        "transfer_id": transfer["id"],
        "reason_code": reason_code,
        "status": "PENDING_REVIEW",
        "reviewer_user_id": None,
    }
    models._stamp_create(hold)
    db.risk_holds[hold["id"]] = hold
    transfer["hold_id"] = hold["id"]
    models.touch(transfer)
    ledger.recompute_account(sender)
    models.touch(sender)


def clear_hold_cascade(transfer):
    """RiskHold CLEARED -> Transfer HELD->SETTLED: credit recipient, recompute balances."""
    sender = db.accounts[transfer["sender_account_id"]]
    recipient = db.accounts[transfer["recipient_account_id"]]
    transfer["settled_at"] = db.now()
    transfer["status"] = "SETTLED"
    models.touch(transfer)
    ledger.post_ledger(recipient["id"], "CREDIT", transfer["amount_cents"],
                       "TRANSFER", transfer["id"], "transfer cleared")
    # held drops on sender (HELD transfer now SETTLED), recipient available rises
    ledger.recompute_account(sender)
    ledger.recompute_account(recipient)
    models.touch(sender)
    models.touch(recipient)


def block_hold_cascade(transfer):
    """RiskHold BLOCKED -> Transfer HELD->REVERSED: refund sender, +20 risk, rewind usage."""
    sender = db.accounts[transfer["sender_account_id"]]
    transfer["status"] = "REVERSED"
    models.touch(transfer)
    # refund the debit: CREDIT back to sender (source_kind REVERSAL)
    ledger.post_ledger(sender["id"], "CREDIT", transfer["amount_cents"],
                       "REVERSAL", transfer["id"], "hold blocked refund")
    # held drops (transfer no longer HELD), available rises via the credit
    ledger.recompute_account(sender)
    ledger.adjust_risk(sender, ledger.RISK_BLOCK_DELTA)
    models.touch(sender)
    # limit-window usage rewinds automatically: REVERSED transfers are excluded
    # from the {SENT,HELD,SETTLED} window sums, so no explicit counter to rewind.
