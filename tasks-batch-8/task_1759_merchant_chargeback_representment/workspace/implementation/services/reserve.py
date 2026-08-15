"""Rolling-reserve domain logic (PRD 3.3, SCAFFOLD calculations:
reserve_hold_rounding, reserve_target, releasable_reserve)."""

from datetime import timedelta

from clock import CLOCK
from db import db
from records import new_ledger_entry, touch
from util import OPEN_CASE_STATUSES, rhu


def account_for_merchant(merchant_id):
    for acct in db.reserve_accounts.values():
        if acct["merchant_id"] == merchant_id:
            return acct
    return None


def entries_of(account_id):
    return [e for e in db.ledger_entries.values() if e["reserve_account_id"] == account_id]


def refold_held(acct):
    """held_cents = sum(HOLD) - sum(RELEASE) - sum(FORFEIT); never negative by construction."""
    total = 0
    for e in entries_of(acct["id"]):
        if e["entry_type"] == "HOLD":
            total += e["amount_cents"]
        elif e["entry_type"] in ("RELEASE", "FORFEIT"):
            total -= e["amount_cents"]
    acct["held_cents"] = total


def post_entry(acct, entry_type, amount_cents, source_kind, source_id, release_eligible_at):
    entry = new_ledger_entry(acct["id"], entry_type, amount_cents, source_kind, source_id, release_eligible_at)
    db.ledger_entries[entry["id"]] = entry
    refold_held(acct)
    return entry


def per_transaction_hold(amount_cents, reserve_rate_bps):
    """round_half_up(amount_cents * reserve_rate_bps / 10000) — per transaction FIRST."""
    return rhu(amount_cents * reserve_rate_bps, 10000)


def recompute_target(merchant):
    """reserve_target calculation; stamps last_recomputed_at; creates no ledger entries.

    Caller is responsible for touching the account (grouped with any held refold).
    """
    acct = account_for_merchant(merchant["id"])
    if acct is None:
        return None
    now = CLOCK.now()
    window_start = now - timedelta(days=90)
    trailing_sales = sum(
        t["amount_cents"]
        for t in db.transactions.values()
        if t["merchant_id"] == merchant["id"] and window_start <= t["occurred_at"] <= now
    )
    rate_floor = rhu(merchant["reserve_rate_bps"] * trailing_sales, 10000)
    if merchant["reserve_mode"] == "EXPOSURE_BASED":
        open_exposure = sum(
            c["amount_cents"]
            for c in db.chargebacks.values()
            if c["merchant_id"] == merchant["id"]
            and c["case_status"] in OPEN_CASE_STATUSES
            and c["funds_status"] == "MERCHANT_DEBITED"
        )
        target = max(rate_floor, 2 * open_exposure)
    else:  # FIXED_TIER — exposure ignored
        target = rate_floor
    acct["target_cents"] = target
    acct["last_recomputed_at"] = now
    return acct


def compute_release_amount(acct):
    """releasable_reserve waterfall. Returns the release amount (may be <= 0)."""
    now = CLOCK.now()
    matured = 0
    scheduled_releases = 0
    for e in entries_of(acct["id"]):
        if (e["entry_type"] == "HOLD" and e["source_kind"] == "TRANSACTION_SETTLEMENT"
                and e["release_eligible_at"] is not None and e["release_eligible_at"] <= now):
            matured += e["amount_cents"]
        elif e["entry_type"] == "RELEASE" and e["source_kind"] == "SCHEDULED_RELEASE":
            scheduled_releases += e["amount_cents"]
    releasable = max(0, matured - scheduled_releases)
    excess = max(0, acct["held_cents"] - acct["target_cents"])
    return min(releasable, excess)


def has_program_reserve_lock(merchant_id):
    for en in db.program_enrollments.values():
        if en["merchant_id"] == merchant_id and en["status"] in ("ACTIVE", "REMEDIATION"):
            return True
    return False


def apply_transaction_ingest_side_effects(merchant, txn):
    """Shared by single and batch ingest: clearing credit, reserve HOLD, refold+recompute."""
    acct = account_for_merchant(merchant["id"])
    hold = per_transaction_hold(txn["amount_cents"], merchant["reserve_rate_bps"])
    merchant["clearing_balance_cents"] += txn["amount_cents"] - hold
    touch(merchant)
    if hold > 0:
        post_entry(acct, "HOLD", hold, "TRANSACTION_SETTLEMENT", txn["id"],
                   txn["occurred_at"] + timedelta(days=90))
    recompute_target(merchant)
    touch(acct)
