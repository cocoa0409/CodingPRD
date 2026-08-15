"""Entity serialization — strip internal helper fields (prefixed with _)
and recompute derived storage-fee fields on lot reads."""

import db
from services.pricing import storage_fees


def _clean(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def customer(c):
    return _clean(c)


def release(r):
    return _clean(r)


def press_order(o):
    return _clean(o)


def tooling_job(j):
    return _clean(j)


def test_pressing(t):
    return _clean(t)


def print_job(p):
    return _clean(p)


def press_line(l):
    return _clean(l)


def press_slot(s):
    return _clean(s)


def plating_bath(b):
    return _clean(b)


def qc_report(q):
    return _clean(q)


def inventory_lot(lot):
    out = _clean(lot)
    release = db.releases.get(lot["release_id"])
    if release:
        daily, monthly = storage_fees(lot, release)
        out["storage_daily_accrual_cents"] = daily
        out["storage_monthly_statement_cents"] = monthly
    return out


def shipment(s):
    return _clean(s)


def delay_notice(n):
    return _clean(n)


def invoice(i):
    return _clean(i)
