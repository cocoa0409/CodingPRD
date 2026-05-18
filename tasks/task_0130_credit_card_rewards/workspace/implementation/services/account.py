"""Account creation and lifecycle transitions."""
from __future__ import annotations

from constants import SIGNUP_WINDOW_DAYS
from errors import err
from services.ledger import append_entry, recompute_balance
from services.touch import touch_versioned
from store import store
from utils import add_days, fmt_iso


def create_account(cardholder_id: str) -> dict:
    """Open an Account; sets opened_at, signup deadline, primes other fields."""
    now = store.now()
    aid = store.new_id()
    iso = fmt_iso(now)
    deadline_iso = fmt_iso(add_days(now, SIGNUP_WINDOW_DAYS))

    acct = {
        "id": aid,
        "cardholder_id": cardholder_id,
        "opened_at": iso,
        "lifecycle_state": "ACTIVE",
        "spending_tier": "STANDARD",
        "ytd_qualifying_spend_cents": 0,
        "points_balance": 0,
        "signup_bonus_state": "PENDING",
        "signup_bonus_qualifying_spend_cents": 0,
        "signup_bonus_deadline_at": deadline_iso,
        "last_qualifying_activity_at": iso,
        "created_at": iso,
        "updated_at": iso,
        "version": 1,
    }
    store.accounts[aid] = acct
    return acct


def mark_delinquent(account: dict) -> dict:
    """ACTIVE -> DELINQUENT; cascade-reverse PENDING transfers."""
    if account["lifecycle_state"] != "ACTIVE":
        raise err(
            "ERR_INVALID_STATE",
            f"Account not in ACTIVE state: {account['lifecycle_state']}",
        )

    aid = account["id"]
    account["lifecycle_state"] = "DELINQUENT"

    # Cascade: reverse all PENDING transfers belonging to this account.
    for t in store.points_transfers.values():
        if t["account_id"] != aid:
            continue
        if t["status"] != "PENDING":
            continue
        t["status"] = "REVERSED"
        append_entry(
            account_id=aid,
            entry_type="TRANSFER_REVERSE",
            delta_points=+int(t["points_debited"]),
            source_entity_type="PointsTransfer",
            source_entity_id=t["id"],
        )

    recompute_balance(account)
    touch_versioned(account)
    return account


def clear_delinquency(account: dict) -> dict:
    """DELINQUENT -> ACTIVE. No retroactive backfill."""
    if account["lifecycle_state"] != "DELINQUENT":
        raise err(
            "ERR_INVALID_STATE",
            f"Account not in DELINQUENT state: {account['lifecycle_state']}",
        )
    account["lifecycle_state"] = "ACTIVE"
    touch_versioned(account)
    return account


def close_account(account: dict) -> dict:
    """ACTIVE|DELINQUENT -> CLOSED.

    Preconditions:
      - lifecycle_state != CLOSED  (else ERR_ACCOUNT_CLOSED per scaffold)
      - No PENDING PointsTransfer for this account (else ERR_INVALID_STATE)

    Side effects:
      - FORFEIT ledger entry of -points_balance
      - points_balance := 0
      - signup_bonus_state := FORFEITED if not AWARDED
    """
    if account["lifecycle_state"] == "CLOSED":
        raise err("ERR_ACCOUNT_CLOSED", "Account is already closed")

    aid = account["id"]
    for t in store.points_transfers.values():
        if t["account_id"] == aid and t["status"] == "PENDING":
            raise err(
                "ERR_INVALID_STATE",
                "Cannot close account with PENDING points transfers",
            )

    # Forfeit any positive balance.
    balance = int(account["points_balance"])
    account["lifecycle_state"] = "CLOSED"
    if balance != 0:
        append_entry(
            account_id=aid,
            entry_type="FORFEIT",
            delta_points=-balance,
            source_entity_type="Account",
            source_entity_id=aid,
        )
    recompute_balance(account)

    if account["signup_bonus_state"] != "AWARDED":
        account["signup_bonus_state"] = "FORFEITED"

    touch_versioned(account)
    return account


def upgrade_tier_if_needed(account: dict) -> None:
    """Check tier-upgrade thresholds against ytd_qualifying_spend_cents and
    fire the upgrade transition + backfill cascade if a threshold is crossed.

    Per PRD §3.5:
      - STANDARD -> GOLD when ytd >= 600_000 and pre-post tier == STANDARD
      - GOLD     -> PLATINUM when ytd >= 1_500_000 and pre-post tier == GOLD

    Both require lifecycle_state == ACTIVE.

    A single post that pushes ytd across both thresholds (STANDARD->GOLD then
    GOLD->PLATINUM) fires both transitions in order; each runs its own
    backfill cascade so the final `points_final` on each affected transaction
    reflects the highest tier reached.
    """
    from services.earn import rerate_same_month_transactions

    from constants import TIER_GOLD_THRESHOLD_CENTS, TIER_PLATINUM_THRESHOLD_CENTS

    if account["lifecycle_state"] != "ACTIVE":
        return

    while True:
        ytd = int(account["ytd_qualifying_spend_cents"])
        pre_tier = account["spending_tier"]
        new_tier = None
        if pre_tier == "STANDARD" and ytd >= TIER_GOLD_THRESHOLD_CENTS:
            new_tier = "GOLD"
        elif pre_tier == "GOLD" and ytd >= TIER_PLATINUM_THRESHOLD_CENTS:
            new_tier = "PLATINUM"
        if new_tier is None:
            break
        account["spending_tier"] = new_tier
        rerate_same_month_transactions(account, new_tier)
        recompute_balance(account)
    # The transition wrapper (route handler) is responsible for the outer
    # version bump; we do NOT touch_versioned here because the originating
    # transaction post will perform a single overall touch_versioned at the end.


def ownership_check(account: dict, cardholder_id: str) -> None:
    """If a Cardholder is acting, ensure they own this account.

    Used by all Cardholder-restricted writes that target a specific account.
    Raises ERR_FORBIDDEN on mismatch.
    """
    if account["cardholder_id"] != cardholder_id:
        raise err("ERR_FORBIDDEN", "Cardholder does not own this account")
