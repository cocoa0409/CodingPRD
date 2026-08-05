"""Append-only custody ledger writes and balance recomputation."""
from store import STORE, new_id
from common import stamp_new, touch, serialize  # noqa: F401

CREDIT_TYPES = {"REMIT_IN", "CLAWBACK_IN"}
DEBIT_TYPES = {"PAYOUT_OUT", "FEE_OUT"}


def recompute_balance(account):
    total = 0
    for e in STORE.ledger.values():
        if e["state_account_id"] != account["id"]:
            continue
        if e["entry_type"] in CREDIT_TYPES:
            total += e["amount_cents"]
        else:
            total -= e["amount_cents"]
    account["custody_balance_cents"] = total
    touch(account)


def write_entry(account, entry_type, amount_cents, property_id=None,
                ref_claim_id=None, ref_report_id=None):
    entry = {
        "id": new_id(),
        "state_account_id": account["id"],
        "property_id": property_id,
        "ref_claim_id": ref_claim_id,
        "ref_report_id": ref_report_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
    }
    stamp_new(entry, full=False)
    STORE.ledger[entry["id"]] = entry
    recompute_balance(account)
    return entry
