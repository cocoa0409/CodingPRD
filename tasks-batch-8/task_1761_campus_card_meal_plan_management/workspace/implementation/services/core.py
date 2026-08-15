"""Core row helpers: creation, mutation bookkeeping, clock access."""

import uuid
from datetime import datetime, timezone

from db import store
from middleware import fmt_dt, parse_dt_value
from response import now_iso


def clock():
    return store.clock


def clock_date():
    return store.clock.date()


def new_row(immutable=False):
    row = {
        "id": str(uuid.uuid4()),
        "created_at": now_iso(),
        "_seq": store.next_seq(),
    }
    if not immutable:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def touch(row):
    """PRD 2.12: every mutation refreshes updated_at and bumps version by 1."""
    if "version" in row:
        row["updated_at"] = now_iso()
        row["version"] += 1


def dt_of(row, field):
    val = row.get(field)
    if val is None:
        return None
    return parse_dt_value(val, field)


def lazy_expire_card(card):
    """Cards flip ACTIVE -> EXPIRED lazily on first transaction/access touch
    at or after expires_at (PRD 3.2)."""
    if card["lifecycle_status"] == "ACTIVE":
        exp = dt_of(card, "expires_at")
        if exp is not None and clock() >= exp:
            card["lifecycle_status"] = "EXPIRED"
            touch(card)
            return True
    return False


def lazy_expire_grant(grant):
    """Grants flip to EXPIRED lazily when touched at/past valid_until (PRD 3.8)."""
    if grant["status"] in ("ACTIVE", "SUSPENDED"):
        vu = dt_of(grant, "valid_until")
        if vu is not None and clock() >= vu:
            grant["status"] = "EXPIRED"
            touch(grant)
            return True
    return False


def holder_of_card(card):
    return store.holders.get(card["holder_id"])


def get_or_create_campus_cash(holder_id):
    """Holder's termless CAMPUS_CASH account; auto-created OPEN when absent."""
    for a in store.accounts.values():
        if (a["holder_id"] == holder_id and a["account_type"] == "CAMPUS_CASH"
                and a["status"] in ("OPEN", "FROZEN", "CLOSE_PENDING")):
            return a
    acct = new_row()
    acct.update({
        "holder_id": holder_id,
        "account_type": "CAMPUS_CASH",
        "term_id": None,
        "balance_cents": 0,
        "status": "OPEN",
        "frozen_reason": None,
        "last_adjusted_by": None,
    })
    store.accounts[acct["id"]] = acct
    return acct


def get_or_create_dining_account(holder_id, term_id):
    for a in store.accounts.values():
        if (a["holder_id"] == holder_id and a["account_type"] == "DINING_DOLLARS"
                and a.get("term_id") == term_id
                and a["status"] in ("OPEN", "FROZEN", "CLOSE_PENDING")):
            return a
    acct = new_row()
    acct.update({
        "holder_id": holder_id,
        "account_type": "DINING_DOLLARS",
        "term_id": term_id,
        "balance_cents": 0,
        "status": "OPEN",
        "frozen_reason": None,
        "last_adjusted_by": None,
    })
    store.accounts[acct["id"]] = acct
    return acct


def find_dining_account(holder_id, term_id):
    for a in store.accounts.values():
        if (a["holder_id"] == holder_id and a["account_type"] == "DINING_DOLLARS"
                and a.get("term_id") == term_id):
            return a
    return None


def find_campus_cash_account(holder_id):
    for a in store.accounts.values():
        if (a["holder_id"] == holder_id and a["account_type"] == "CAMPUS_CASH"):
            return a
    return None


def mint_card_number():
    import random
    while True:
        num = "".join(random.choices("0123456789", k=16))
        if num not in store.used_card_numbers:
            store.used_card_numbers.add(num)
            return num
