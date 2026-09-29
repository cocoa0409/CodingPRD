"""Append-only reserve ledger and the ReserveAccount state machine."""
from db import db, new_row
from services.metrics import mirror_reserve_balance, recompute_reserve_totals
from util import ceil_div  # noqa: F401  (kept for symmetry with other services)


def append_entry(account, entry_type, reason_code, amount_cents, effective_date,
                 settlement_batch_id=None, tranche_start_date=None,
                 tranche_end_date=None, recorded_by_user_id=None):
    """Append one immutable ReserveLedgerEntry and recompute the account totals."""
    entry = new_row(versioned=False)
    entry.update({
        "reserve_account_id": account["id"],
        "settlement_batch_id": settlement_batch_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "effective_date": effective_date,
        "tranche_start_date": tranche_start_date,
        "tranche_end_date": tranche_end_date,
        "reason_code": reason_code,
        "recorded_by_user_id": recorded_by_user_id,
    })
    db.ledger_entries[entry["id"]] = entry
    recompute_reserve_totals(account)
    apply_state_after_entry(account, entry_type)
    return entry


def apply_state_after_entry(account, entry_type):
    """PRD 3.9 / 3.10 reserve-account state transitions triggered by an append."""
    held = account["held_balance_cents"]
    cap = account["reserve_cap_cents"]
    released = account["released_to_date_cents"]
    state = account["state"]
    if state == "CLOSED":
        return account

    if entry_type == "HOLD":
        if state == "RELEASING":
            account["state"] = "ACCRUING"
            state = "ACCRUING"
        if state == "ACCRUING" and account["reserve_type"] == "CAPPED" and held >= cap:
            account["state"] = "CAP_REACHED"
        return account

    # RELEASE or OFFSET_LOSS
    if state == "ACCRUING":
        if entry_type == "RELEASE" and held > 0 and released > 0:
            account["state"] = "RELEASING"
        return account
    if state == "CAP_REACHED":
        if entry_type == "RELEASE" and 0 < held < cap and released > 0:
            account["state"] = "RELEASING"
        elif held < cap and (released == 0 or held == 0):
            account["state"] = "ACCRUING"
        return account
    return account


def sync_merchant_balance(merchant, account):
    mirror_reserve_balance(merchant, account)
