"""Record -> JSON payload conversion.

Keys beginning with '_' are internal bookkeeping and never leave the server.
"""
from datetime import date, datetime
from decimal import Decimal

from timeutil import fmt_dt


def to_json(value):
    if isinstance(value, datetime):
        return fmt_dt(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: to_json(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [to_json(v) for v in value]
    return value


def public(rec):
    return to_json(rec)


def public_list(recs):
    return [to_json(r) for r in recs]
