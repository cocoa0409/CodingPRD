"""In-memory store. Starts completely empty on every boot: nothing is seeded."""
import uuid

from flask import g

import clock
from errors import ApiError, NOT_FOUND

TABLES = [
    "stores",
    "store_stocks",
    "delivery_trucks",
    "pro_accounts",
    "credit_lines",
    "tax_exempt_certificates",
    "job_quotes",
    "quote_lines",
    "pro_orders",
    "order_lines",
    "reservations",
    "will_call_stagings",
    "delivery_appointments",
    "rebate_accruals",
    "return_requests",
]

data = {t: {} for t in TABLES}
_counter = {"n": 0}


def next_seq():
    _counter["n"] += 1
    return _counter["n"]


def _seen():
    try:
        seen = getattr(g, "_touched_ids", None)
        if seen is None:
            seen = set()
            g._touched_ids = seen
        return seen
    except RuntimeError:
        return set()


def new_record(table, fields):
    rec = dict(fields)
    rec["id"] = str(uuid.uuid4())
    rec["created_at"] = clock.now_iso()
    rec["updated_at"] = rec["created_at"]
    rec["version"] = 1
    rec["_seq"] = next_seq()
    data[table][rec["id"]] = rec
    # A record created in this request is already "fresh"; later cascade touches
    # inside the same request must not push its version past 1.
    _seen().add(rec["id"])
    return rec


def touch(rec):
    """Register a mutation: refresh updated_at and bump version once per request."""
    if rec is None:
        return rec
    seen = _seen()
    rec["updated_at"] = clock.now_iso()
    if rec["id"] not in seen:
        seen.add(rec["id"])
        rec["version"] += 1
    return rec


def get(table, rec_id):
    if not isinstance(rec_id, str):
        return None
    return data[table].get(rec_id)


def require(table, rec_id):
    rec = get(table, rec_id)
    if rec is None:
        raise ApiError(NOT_FOUND[table], 404)
    return rec


def all_of(table):
    return sorted(data[table].values(), key=lambda r: r["_seq"])


def where(table, **filters):
    out = []
    for rec in all_of(table):
        ok = True
        for key, value in filters.items():
            if rec.get(key) != value:
                ok = False
                break
        if ok:
            out.append(rec)
    return out


def public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}
