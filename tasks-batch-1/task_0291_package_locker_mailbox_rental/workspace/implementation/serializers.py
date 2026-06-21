"""Entity serialization with computed-field derivation."""
from db import db


def _strip(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def facility_out(f):
    out = _strip(f)
    lockers = [l for l in db.locker_units.values() if l["facility_id"] == f["id"]]
    out["total_locker_count"] = len(lockers)
    out["available_locker_count"] = sum(1 for l in lockers if l["status"] == "AVAILABLE")
    return out


def locker_out(l):
    out = _strip(l)
    # current_package_id: id of the single package currently occupying it
    # (null when AVAILABLE/OUT_OF_SERVICE).
    out["current_package_id"] = l.get("current_package_id")
    return out


def mailbox_out(m):
    return _strip(m)


def customer_out(c):
    return _strip(c)


def form_out(f):
    return _strip(f)


def recipient_out(r):
    return _strip(r)


def agreement_out(a):
    return _strip(a)


def package_out(p):
    return _strip(p)


def mail_item_out(m):
    return _strip(m)


def forwarding_out(fr):
    return _strip(fr)


def invoice_out(inv):
    out = _strip(inv)
    entries = [e for e in db.ledger_entries.values() if e["invoice_id"] == inv["id"]]
    charges = sum(e["amount_cents"] for e in entries if e["kind"] == "CHARGE")
    credits = sum(e["amount_cents"] for e in entries if e["kind"] == "CREDIT")
    payments = sum(p["amount_cents"] for p in db.payments.values()
                   if p["invoice_id"] == inv["id"] and p["status"] == "CAPTURED")
    out["charges_total_cents"] = charges
    out["credits_total_cents"] = credits
    out["payments_total_cents"] = payments
    out["balance_cents"] = charges - credits - payments
    return out


def ledger_out(e):
    return _strip(e)


def payment_out(p):
    return _strip(p)
