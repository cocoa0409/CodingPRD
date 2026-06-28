"""Derived-field reconciliation + mutation bookkeeping (PRD 2.4, 3.4, 3.6, 3.7).

Whenever a derived total on a resource changes, that is itself a mutation of the
owning resource: its updated_at is refreshed and its version is incremented.
"""
from clock import clock
from calculations import window_start
from db import db


def touch(record):
    """Mark a resource mutated: refresh updated_at and bump version by one.
    CapTableEntry is immutable (no updated_at / version) and is never touched."""
    if "updated_at" in record:
        record["updated_at"] = clock.now_iso()
    if "version" in record:
        record["version"] = record["version"] + 1


def credit_wallet(investor_id, amount_cents):
    db.investor_wallets[investor_id] = db.investor_wallets.get(investor_id, 0) + amount_cents


def offering_investments(offering_id):
    return [i for i in db.investments.values() if i["offering_id"] == offering_id]


def recompute_offering_committed(offering):
    """committed_amount_cents = sum amount over investments in COMMITTED/RECONFIRMED."""
    total = sum(
        i["amount_cents"]
        for i in db.investments.values()
        if i["offering_id"] == offering["id"] and i["status"] in ("COMMITTED", "RECONFIRMED")
    )
    offering["committed_amount_cents"] = total


def recompute_offering_swept(offering):
    """swept_amount_cents = sum amount over investments in ISSUED."""
    total = sum(
        i["amount_cents"]
        for i in db.investments.values()
        if i["offering_id"] == offering["id"] and i["status"] == "ISSUED"
    )
    offering["swept_amount_cents"] = total


def recompute_escrow_held(escrow):
    """held_amount_cents = sum amount over investments in COMMITTED/RECONFIRMED
    (escrow conservation: held always equals offering committed)."""
    total = sum(
        i["amount_cents"]
        for i in db.investments.values()
        if i["offering_id"] == escrow["offering_id"] and i["status"] in ("COMMITTED", "RECONFIRMED")
    )
    escrow["held_amount_cents"] = total


def get_escrow_for_offering(offering_id):
    eid = db.escrow_by_offering.get(offering_id)
    if eid is None:
        return None
    return db.escrow_accounts.get(eid)


def recompute_issuer_trailing(issuer):
    """total_raised_trailing_12mo_cents = sum swept_amount over the issuer's
    REG_CF offerings whose close_at is non-null and within trailing 365 days."""
    ws = window_start(clock.now())
    from clock import parse_iso
    total = 0
    for off in db.offerings.values():
        if off["issuer_id"] != issuer["id"]:
            continue
        if off["regulation"] != "REG_CF":
            continue
        if off.get("close_at") is None:
            continue
        close_dt = parse_iso(off["close_at"])
        if close_dt >= ws:
            total += off["swept_amount_cents"]
    issuer["total_raised_trailing_12mo_cents"] = total
