"""Trust accounting journal (PRD §3.8). Append-only; global running balance."""

import db
from services.common import new_id, stamp_append_only


def trust_balance():
    return sum(t["amount_cents"] for t in db.trust_transactions.values())


def post_trust(deal_id, kind, amount_cents, disbursement_leg_id=None):
    txn = {
        "id": new_id(),
        "deal_id": deal_id,
        "kind": kind,
        "amount_cents": amount_cents,
        "disbursement_leg_id": disbursement_leg_id,
        "trust_balance_after_cents": trust_balance() + amount_cents,
    }
    stamp_append_only(txn)
    db.trust_transactions[txn["id"]] = txn
    return txn
