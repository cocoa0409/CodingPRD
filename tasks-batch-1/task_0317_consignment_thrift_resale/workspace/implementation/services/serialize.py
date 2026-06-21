"""Serialization of entities to public JSON, plus derived-field reconciliation.

Derived fields (PRD §2.7) are recomputed here so reads always reflect the
underlying ledgers.
"""
from db import store
from services import calc
from services.common import public, now, iso


def iso_dt(dt):
    return iso(dt)


# ---- derived balance reconciliation (PRD §2.7) -------------------------------

def recompute_store_credit(consignor_id):
    total = 0
    for txn in store.store_credit_transactions.values():
        if txn["consignor_id"] == consignor_id and txn["status"] == "POSTED":
            total += txn["amount_cents"]
    return total


def recompute_unsettled_payable(consignor_id):
    total = 0
    for e in store.payout_ledger_entries.values():
        if (
            e["consignor_id"] == consignor_id
            and e["settlement_id"] is None
            and e["entry_type"] in ("SALE_PAYOUT", "REVERSAL")
        ):
            total += e["amount_cents"]
    return total


def recompute_lifetime_payout(consignor_id):
    total = 0
    for e in store.payout_ledger_entries.values():
        if (
            e["consignor_id"] == consignor_id
            and e["settlement_id"] is not None
            and e["entry_type"] == "SALE_PAYOUT"
        ):
            total += e["amount_cents"]
    return total


def reconcile_consignor(consignor):
    consignor["store_credit_cents"] = recompute_store_credit(consignor["id"])
    consignor["unsettled_payable_cents"] = recompute_unsettled_payable(consignor["id"])
    consignor["lifetime_payout_cents"] = recompute_lifetime_payout(consignor["id"])


def recompute_item_count(batch_id):
    return sum(1 for it in store.items.values() if it["batch_id"] == batch_id)


# ---- current price recompute for items (PRD §3.4) ----------------------------

def item_current_price(item):
    if item["listing_status"] != "ON_FLOOR" or item.get("floor_date_dt") is None:
        return item.get("current_price_cents")
    agreement = store.agreements[item["agreement_id"]]
    schedule = store.markdown_schedules[agreement["markdown_schedule_id"]]
    return calc.markdown_price(
        item["list_price_cents"], item["floor_date_dt"], now(), schedule
    )


# ---- serializers -------------------------------------------------------------

def consignor_out(c):
    reconcile_consignor(c)
    return public(c)


def schedule_out(s):
    return public(s)


def agreement_out(a):
    return public(a)


def batch_out(b):
    b["item_count"] = recompute_item_count(b["id"])
    return public(b)


def item_out(it):
    # Recompute current price on read when on floor.
    if it["listing_status"] == "ON_FLOOR":
        it["current_price_cents"] = item_current_price(it)
    return public(it, hidden={"floor_date_dt"})


def review_out(r):
    return public(r)


def sale_out(s):
    return public(s)


def sale_line_out(line):
    return public(line)


def ledger_out(e):
    return public(e)


def credit_txn_out(t):
    return public(t)


def settlement_out(s):
    return public(s)


def donation_out(d):
    return public(d)
