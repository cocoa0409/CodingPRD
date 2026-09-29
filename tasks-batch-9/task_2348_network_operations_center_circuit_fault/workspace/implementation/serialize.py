"""Record -> JSON projection. Internal keys (leading underscore) are hidden."""

from datetime import datetime
from decimal import Decimal

from timeutil import fmt


def _conv(value):
    if isinstance(value, datetime):
        return fmt(value)
    if isinstance(value, Decimal):
        if value == value.to_integral_value() and value.as_tuple().exponent == 0:
            return int(value)
        return float(value)
    if isinstance(value, dict):
        return {k: _conv(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_conv(v) for v in value]
    return value


def jsonable(value):
    return _conv(value)


def public(rec):
    if rec is None:
        return None
    return {k: _conv(v) for k, v in rec.items() if not k.startswith("_")}


def public_list(records):
    return [public(r) for r in records]
