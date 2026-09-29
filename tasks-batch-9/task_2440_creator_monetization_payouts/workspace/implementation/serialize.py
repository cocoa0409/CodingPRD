"""Entity projections.  Derived fields are recomputed from source rows on every
read; nothing derived is trusted from a cache."""
from datetime import datetime

import calc
from store import db, iso


def _base(rec):
    out = {}
    for key, value in rec.items():
        if key.startswith("_"):
            continue
        out[key] = iso(value) if isinstance(value, datetime) else value
    return out


def creator(rec):
    out = _base(rec)
    out.update(calc.balances(rec))
    return out


def tax_profile(rec):
    return _base(rec)


def product(rec):
    return _base(rec)


def content_item(rec):
    out = _base(rec)
    out["monetization_state"] = calc.MONETIZATION_STATE[rec["suitability_rating"]]
    out["open_appeal_count"] = sum(
        1 for a in db.appeals.values()
        if a["content_item_id"] == rec["id"]
        and a["state"] in ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED"))
    return out


def revenue_event(rec):
    return _base(rec)


def appeal(rec):
    return _base(rec)


def period(rec):
    out = _base(rec)
    statements = [s for s in db.statements.values() if s["period_id"] == rec["id"]]
    out["statement_count"] = len(statements)
    out["finalized_statement_count"] = sum(
        1 for s in statements if s["status"] in ("FINALIZED", "ADJUSTED", "PAID"))
    return out


def statement(rec):
    return _base(rec)


def payout(rec):
    out = _base(rec)
    out["statement_count"] = sum(
        1 for s in db.statements.values() if s["payout_id"] == rec["id"])
    return out


def investigation(rec):
    return _base(rec)


def fund(rec):
    out = _base(rec)
    active = [a for a in db.allocations.values()
              if a["fund_id"] == rec["id"] and a["status"] == "ACTIVE"]
    allocated = sum(a["amount_cents"] for a in active)
    out["allocated_cents"] = allocated
    out["unallocated_remainder_cents"] = rec["total_pool_cents"] - allocated
    out["recipient_count"] = len(active)
    return out


def allocation(rec):
    return _base(rec)


def ledger_entry(rec):
    return _base(rec)


def many(fn, rows):
    return [fn(r) for r in rows]
