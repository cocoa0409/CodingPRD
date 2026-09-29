"""The points ledger, the account aggregates, and available points (PRD 2.7)."""

from core import DB, clock_iso, new_row, ordered, store, touch

EARN_TYPES = ("EARN_BASE", "EARN_BONUS")
DEBIT_TYPES = ("REDEEM_DEBIT", "TRANSFER_DEBIT")


def account_entries(account_id):
    rows = [r for r in DB["ledger"].values() if r["account_id"] == account_id]
    return sorted(rows, key=lambda r: (r["occurred_at"], r["created_at"], r["_seq"]))


def ledger_order(rows):
    """occurred_at ASC with created_at ASC as the tie-break (PRD 2.7)."""
    return sorted(rows, key=lambda r: (r["occurred_at"], r["created_at"], r["_seq"]))


def _recompute_balances(account_id):
    running = 0
    for entry in account_entries(account_id):
        running += entry["points_delta"]
        entry["balance_after"] = running


def append_entry(account, entry_type, points_delta, source_entity_type, source_entity_id, memo):
    row = new_row(
        "ledger",
        {
            "account_id": account["id"],
            "entry_type": entry_type,
            "points_delta": int(points_delta),
            "balance_after": 0,
            "occurred_at": clock_iso(),
            "memo": memo,
            "source_entity_type": source_entity_type,
            "source_entity_id": source_entity_id,
        },
        audit=False,
    )
    store("ledger", row)
    _recompute_balances(account["id"])
    refresh_account(account)
    return row


# --------------------------------------------------------------------------
# derived account aggregates
# --------------------------------------------------------------------------
def points_balance(account_id):
    return sum(r["points_delta"] for r in DB["ledger"].values() if r["account_id"] == account_id)


def lifetime_earned(account_id):
    return sum(
        r["points_delta"]
        for r in DB["ledger"].values()
        if r["account_id"] == account_id and r["entry_type"] in EARN_TYPES
    )


def lifetime_redeemed(account_id):
    total = sum(
        r["points_delta"]
        for r in DB["ledger"].values()
        if r["account_id"] == account_id and r["entry_type"] in DEBIT_TYPES
    )
    return abs(total)


def quoted_orders(account_id):
    return [
        o
        for o in DB["orders"].values()
        if o["account_id"] == account_id and o["fulfillment_status"] == "QUOTED"
    ]


def pending_redemption(account_id):
    total = sum(o["points_debited"] for o in quoted_orders(account_id))
    total += sum(
        t["points_out"]
        for t in DB["transfer_requests"].values()
        if t["account_id"] == account_id and t["status"] in ("SUBMITTED", "HELD", "QUEUED")
    )
    return total


def refresh_account(account):
    """Recompute the four ledger aggregates in place (no version bump)."""
    account_id = account["id"]
    account["points_balance"] = points_balance(account_id)
    account["points_pending_redemption"] = pending_redemption(account_id)
    account["lifetime_points_earned"] = lifetime_earned(account_id)
    account["lifetime_points_redeemed"] = lifetime_redeemed(account_id)
    return account


def available_points(account):
    """points_balance less the points_debited of QUOTED orders, and nothing else."""
    refresh_account(account)
    reserved = sum(o["points_debited"] for o in quoted_orders(account["id"]))
    return account["points_balance"] - reserved


# --------------------------------------------------------------------------
# offer seat capacity (PRD 3.5)
# --------------------------------------------------------------------------
COMMITTING_STATUSES = ("QUOTED", "CONFIRMED", "TICKETED")


def count_committed(offer_id):
    return len(
        [
            o
            for o in DB["orders"].values()
            if o.get("inventory_offer_id") == offer_id
            and o["fulfillment_status"] in COMMITTING_STATUSES
        ]
    )


def recompute_seats(offer, release=False):
    """Recompute seats_committed and flip the capacity cycle when it crosses the line.

    Returns True when the availability status moved, so the caller can bump the
    offer's version exactly once.
    """
    offer["seats_committed"] = count_committed(offer["id"])
    if release:
        if offer["status"] == "SOLD_OUT" and offer["seats_committed"] < offer["portal_seats"]:
            offer["status"] = "OPEN"
            return True
    else:
        if offer["status"] == "OPEN" and offer["seats_committed"] >= offer["portal_seats"]:
            offer["status"] = "SOLD_OUT"
            return True
    return False


def in_flight_transfers(account_id):
    return [
        t
        for t in DB["transfer_requests"].values()
        if t["account_id"] == account_id and t["status"] in ("SUBMITTED", "QUEUED", "HELD")
    ]


def in_flight_orders(account_id):
    return [
        o
        for o in DB["orders"].values()
        if o["account_id"] == account_id and o["fulfillment_status"] in ("QUOTED", "CONFIRMED")
    ]


def account_entitlements(account_id, statuses=None):
    rows = [e for e in DB["entitlements"].values() if e["account_id"] == account_id]
    if statuses is not None:
        rows = [e for e in rows if e["status"] in statuses]
    return ordered("entitlements", rows)
