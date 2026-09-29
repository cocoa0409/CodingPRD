"""Entity serialization: datetimes to canonical strings, Decimals to numbers."""

from datetime import datetime
from decimal import Decimal

from db import fmt_dt


def _conv(value):
    if isinstance(value, datetime):
        return fmt_dt(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _conv(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, list):
        return [_conv(v) for v in value]
    return value


def public(row):
    return {k: _conv(v) for k, v in row.items() if not k.startswith("_")}


def public_list(rows):
    return [public(r) for r in rows]
