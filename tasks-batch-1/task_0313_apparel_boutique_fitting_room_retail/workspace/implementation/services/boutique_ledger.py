"""Boutique-level store-credit conservation anchor (PRD §3.1)."""
from db import db, touch


def recompute_store_credit_outstanding(boutique_id):
    """store_credit_outstanding_cents = sum of store_credit_cents over the
    boutique's customers."""
    boutique = db.boutiques.get(boutique_id)
    if boutique is None:
        return
    total = 0
    for c in db.customers.values():
        if c["boutique_id"] == boutique_id:
            total += c["store_credit_cents"]
    boutique["store_credit_outstanding_cents"] = total
    touch(boutique)
