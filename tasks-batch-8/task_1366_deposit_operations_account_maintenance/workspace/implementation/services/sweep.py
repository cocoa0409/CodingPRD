"""Daily sweep (PRD §3.8, §3.9): dormancy evaluation, inactivity-fee
assessment, zero-balance auto-close, escheat close, and statement
production/suppression.

Constants: DORMANT_DAYS 365, ESCHEAT_DAYS 1095, ESCHEAT_CLOSE_DAYS 1125,
INACTIVITY_FEE_CENTS 500, FEE_PERIOD_DAYS 30.
"""

from datetime import date

import db
from services import account as acct_svc
from services.account import (
    DEST_OWNER,
    DEST_STATE_ESCHEAT,
    closure_cascade,
    post_transaction,
    settle_interest_txn,
    touch_account,
)
from services.interest import rounding_variant_for_product

DORMANT_DAYS = 365
ESCHEAT_DAYS = 1095
ESCHEAT_CLOSE_DAYS = 1125
INACTIVITY_FEE_CENTS = 500
FEE_PERIOD_DAYS = 30


def _days_inactive(acct, sweep: date) -> int:
    last = date.fromisoformat(acct["last_customer_activity_date"])
    return (sweep - last).days


def _close_account(acct, close_date_str: str, payout: int, destination: str,
                   signer_reason: str) -> None:
    acct["lifecycle_status"] = "CLOSED"
    acct["closure_payout_cents"] = payout
    acct["closure_payout_destination"] = destination
    closure_cascade(acct, close_date_str, signer_reason)
    touch_account(acct)


def _assess_fees(acct, sweep: date, sweep_date_str: str):
    """inactivity_fee_assessment (SCAFFOLD §1.3). Returns (count, cents, closed)."""
    dormant_since = date.fromisoformat(acct["dormant_since_date"])
    should_have = 1 + (sweep - dormant_since).days // FEE_PERIOD_DAYS
    fees_due_now = max(0, should_have - acct["fees_assessed_count"])

    assessed = 0
    cents = 0
    for _ in range(fees_due_now):
        fee_i = min(INACTIVITY_FEE_CENTS, acct["balance_cents"])
        if fee_i == 0:
            break  # a zero-amount fee is never posted; posting stops there
        post_transaction(acct, "INACTIVITY_FEE", fee_i, False, sweep_date_str)
        acct["fees_assessed_count"] += 1
        assessed += 1
        cents += fee_i

    # Zero-balance auto-close (PRD §3.9): a DORMANT account whose fee run
    # drains the balance to exactly zero closes in the same sweep.
    closed = False
    if acct["balance_cents"] == 0 and acct["lifecycle_status"] == "DORMANT":
        _close_account(acct, sweep_date_str, 0, DEST_OWNER, "ACCOUNT_CLOSED")
        closed = True
    return assessed, cents, closed


def run_daily_sweep():
    sweep = date.fromisoformat(db.clock_date_str())
    sweep_date_str = sweep.isoformat()

    evaluated_accounts = 0
    newly_dormant = 0
    fees_assessed_count = 0
    fees_assessed_cents = 0
    auto_closed_count = 0
    escheated_count = 0
    statements_produced = 0
    statements_suppressed = 0

    accounts = sorted(db.accounts.values(), key=lambda a: a["_seq"])
    for acct in accounts:
        if acct["lifecycle_status"] == "CLOSED":
            continue
        evaluated_accounts += 1
        days = _days_inactive(acct, sweep)

        # --- dormancy_evaluation (inclusive boundaries) ---
        transitioned = False
        if acct["lifecycle_status"] == "OPEN" and days >= DORMANT_DAYS:
            acct["lifecycle_status"] = "DORMANT"
            acct["dormant_since_date"] = sweep_date_str
            # fees_assessed_count unchanged — the episode continues
            newly_dormant += 1
            transitioned = True
            touch_account(acct)
        elif acct["lifecycle_status"] == "DORMANT" and days >= ESCHEAT_DAYS:
            acct["lifecycle_status"] = "ESCHEAT_PENDING"
            transitioned = True
            touch_account(acct)
        elif acct["lifecycle_status"] == "ESCHEAT_PENDING" and days >= ESCHEAT_CLOSE_DAYS:
            # Escheat closure (PRD §3.9): settle interest, drain as payout.
            settled = settle_interest_txn(
                acct, sweep_date_str, rounding_variant_for_product(acct["product_code"])
            )
            payout = acct["balance_cents"]  # balance + settled interest
            if payout > 0:
                post_transaction(acct, "CLOSURE_PAYOUT", payout, False, sweep_date_str)
            _close_account(acct, sweep_date_str, payout, DEST_STATE_ESCHEAT,
                           "ACCOUNT_CLOSED")
            escheated_count += 1
            transitioned = True

        # --- inactivity_fee_assessment (entry fee #1 runs on the transition sweep) ---
        if acct["lifecycle_status"] == "DORMANT":
            assessed, cents, closed = _assess_fees(acct, sweep, sweep_date_str)
            if assessed or closed:
                fees_assessed_count += assessed
                fees_assessed_cents += cents
                if closed:
                    auto_closed_count += 1
                if not transitioned or closed:
                    # Entry-fee path shares the transition's version bump; a fee
                    # run on an already-dormant account is its own mutation.
                    if not transitioned:
                        touch_account(acct)

    # --- statement production / suppression for due cycles (PRD §3.6) ---
    cycles = sorted(db.statement_cycles.values(), key=lambda c: c["_seq"])
    for cyc in cycles:
        if cyc["status"] != "SCHEDULED":
            continue
        if date.fromisoformat(cyc["cycle_end"]) > sweep:
            continue  # cycle_end must fall on or before the sweep date
        acct = db.accounts.get(cyc["account_id"])
        suppression = acct["statement_suppression"] if acct else "CLOSED"
        if suppression == "NONE":
            cyc["status"] = "PRODUCED"
            cyc["produced_date"] = sweep_date_str
            statements_produced += 1
        else:
            cyc["status"] = "SUPPRESSED"
            cyc["suppression_reason"] = suppression
            cyc["produced_date"] = sweep_date_str
            statements_suppressed += 1
        cyc["version"] += 1
        cyc["updated_at"] = db.now_timestamp()

    return {
        "evaluated_accounts": evaluated_accounts,
        "newly_dormant": newly_dormant,
        "fees_assessed_count": fees_assessed_count,
        "fees_assessed_cents": fees_assessed_cents,
        "auto_closed_count": auto_closed_count,
        "escheated_count": escheated_count,
        "statements_produced": statements_produced,
        "statements_suppressed": statements_suppressed,
    }
