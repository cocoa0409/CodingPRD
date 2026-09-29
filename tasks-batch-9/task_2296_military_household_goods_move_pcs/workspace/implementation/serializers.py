"""Record -> JSON conversion."""

from datetime import datetime
from decimal import Decimal

from response import fmt_dt, fmt_ts

# The two common properties rendered with exactly three fractional digits (PRD §2.4).
THREE_DIGIT_FIELDS = ("created_at", "updated_at")


def _scalar(value, three_digits=False):
    if isinstance(value, datetime):
        return fmt_ts(value) if three_digits else fmt_dt(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_scalar(item) for item in value]
    if isinstance(value, dict):
        return {k: _scalar(v) for k, v in value.items()}
    return value


def serialize(record):
    if record is None:
        return None
    out = {}
    for key, value in record.items():
        if key.startswith("_"):
            continue
        out[key] = _scalar(value, three_digits=(key in THREE_DIGIT_FIELDS))
    return out


def serialize_all(records):
    return [serialize(record) for record in records]
