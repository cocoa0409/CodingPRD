"""Periodic sweeps and year-rollover.

PRD §3.8: sweep walks three independent buckets:
  1. QuarterlyActivation ACTIVATED -> EXPIRED when activation_window_end <= now
  2. Account signup_bonus_state PENDING -> EXPIRED when now >= signup_bonus_deadline_at
  3. calc_points_expiration on every ACTIVE/DELINQUENT account whose
     last_qualifying_activity_at is older than EXPIRATION_INACTIVITY_DAYS.
"""
from __future__ import annotations

from constants import EXPIRATION_INACTIVITY_DAYS, SECONDS_PER_DAY
from services.ledger import append_entry, recompute_balance
from services.signup_bonus import expire_unqualified_if_past_deadline
from services.touch import touch_versioned
from store import store
from utils import parse_iso


def run_sweep() -> None:
    """Run all three independent sweep buckets in a single pass."""
    now = store.now()

    # ----- Bucket 1: activation expirations -----
    for a in store.quarterly_activations.values():
        if a["status"] != "ACTIVATED":
            continue
        end = parse_iso(a["activation_window_end"])
        if end <= now:
            a["status"] = "EXPIRED"

    # ----- Bucket 2: signup-bonus expirations -----
    for acct in store.accounts.values():
        if expire_unqualified_if_past_deadline(acct):
            touch_versioned(acct)

    # ----- Bucket 3: points expiration -----
    for acct in store.accounts.values():
        if acct["lifecycle_state"] == "CLOSED":
            continue
        last_activity = parse_iso(acct["last_qualifying_activity_at"])
        days_inactive = int((now - last_activity).total_seconds() // SECONDS_PER_DAY)
        if days_inactive >= EXPIRATION_INACTIVITY_DAYS:
            balance = int(acct["points_balance"])
            if balance > 0:
                append_entry(
                    account_id=acct["id"],
                    entry_type="EXPIRE",
                    delta_points=-balance,
                    source_entity_type="System",
                    source_entity_id=None,
                )
                recompute_balance(acct)
                touch_versioned(acct)


def run_year_rollover() -> None:
    """Reset ytd_qualifying_spend_cents and downgrade tiers to STANDARD."""
    for acct in store.accounts.values():
        changed = False
        if acct["ytd_qualifying_spend_cents"] != 0:
            acct["ytd_qualifying_spend_cents"] = 0
            changed = True
        if acct["spending_tier"] in ("GOLD", "PLATINUM"):
            acct["spending_tier"] = "STANDARD"
            changed = True
        if changed:
            touch_versioned(acct)
