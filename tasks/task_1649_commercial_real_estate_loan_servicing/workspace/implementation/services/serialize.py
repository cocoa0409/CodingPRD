"""Entity -> API dict serializers. Internal *_dt helper fields are stripped."""
import db
from services import posture


def _clean(obj, extra=None):
    out = {k: v for k, v in obj.items() if not k.endswith("_dt")}
    if extra:
        out.update(extra)
    return out


def borrower(b):
    return _clean(b)


def loan(l):
    out = _clean(l)
    out["days_delinquent"] = posture.loan_days_delinquent(l)
    return out


def prop(p):
    return _clean(p)


def statement(s):
    return _clean(s)


def assessment(a):
    return _clean(a)


def reserve(r):
    out = _clean(r)
    out["available_cents"] = r["balance_cents"] - r["held_cents"]
    return out


def disbursement(d):
    return _clean(d)


def lease(l):
    return _clean(l)


def estoppel(e):
    return _clean(e)


def inspector(i):
    return _clean(i)


def inspection(i):
    return _clean(i)


def policy(p):
    return _clean(p)


def assumption(a):
    return _clean(a)


def option(o):
    return _clean(o)


def watchlist_entry(e):
    return _clean(e)
