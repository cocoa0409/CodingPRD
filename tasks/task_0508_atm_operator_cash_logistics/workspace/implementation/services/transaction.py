"""Transaction posting: cassette selection, surcharge snapshot, monthly_seq,
low-watermark transition (PRD §3.6).

Cassette charging (Transaction.cassette_id):
  1. smallest-position cassette whose (loaded - dispensed) >= amount
  2. else smallest-position cassette with (loaded - dispensed) > 0
  3. else null (and for BALANCE_INQUIRY: always null)
"""
from constants import LOW_WATERMARK_CENTS
from db import store
import services.atm as atm_svc


def select_cassette(store, atm_id, amount_cents):
    """Pick the cassette to charge for a WITHDRAWAL, or None."""
    cassettes = atm_svc.cassettes_for(store, atm_id)  # ordered C1<C2<C3<C4
    # 1. smallest position that can fully cover the amount.
    for c in cassettes:
        if (c["loaded_cents"] - c["dispensed_cents"]) >= amount_cents:
            return c
    # 2. smallest position with any positive remaining.
    for c in cassettes:
        if (c["loaded_cents"] - c["dispensed_cents"]) > 0:
            return c
    # 3. nothing available.
    return None


def post(store, atm, kind, amount_cents):
    """Create + persist a Transaction and apply all side effects."""
    txn = {
        "atm_id": atm["id"],
        "kind": kind,
        "amount_cents": amount_cents if kind == "WITHDRAWAL" else 0,
        "cassette_id": None,
        "surcharge_cents": 0,
        "settlement_run_id": None,
        "monthly_seq": None,
    }

    if kind == "WITHDRAWAL":
        # Surcharge snapshot.
        txn["surcharge_cents"] = atm["surcharge_cents"]
        # monthly_seq = current monthly_wd_count + 1; then increment.
        txn["monthly_seq"] = atm["monthly_wd_count"] + 1
        atm["monthly_wd_count"] = atm["monthly_wd_count"] + 1
        # Charge a cassette.
        cassette = select_cassette(store, atm["id"], amount_cents)
        if cassette is not None:
            txn["cassette_id"] = cassette["id"]
            cassette["dispensed_cents"] = cassette["dispensed_cents"] + amount_cents
            store.touch(cassette)
        # Running cash figure on the ATM.
        atm["dispensed_cents_since_load"] = atm["dispensed_cents_since_load"] + amount_cents
        # Low-watermark transition: only from cash_status LOADED.
        if atm["cash_status"] == "LOADED":
            remaining = atm_svc.remaining_cents(store, atm)
            if remaining <= LOW_WATERMARK_CENTS:
                atm["cash_status"] = "LOW"
        store.touch(atm)

    store.stamp_new(txn, common_fields=False)
    store.transactions[txn["id"]] = txn
    return txn
