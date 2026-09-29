"""Row -> JSON conversion.

Rows are stored with exactly the fields the scaffold declares; anything
internal is prefixed with ``_`` and stripped here.  Decimals become JSON
numbers (money is already whole-cent ``int``).
"""
from decimal import Decimal


def _value(value):
    if isinstance(value, Decimal):
        as_int = int(value)
        if value == as_int:
            return as_int if value.as_tuple().exponent == 0 else float(value)
        return float(value)
    if isinstance(value, dict):
        return {k: _value(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [_value(v) for v in value]
    return value


def row(record):
    if record is None:
        return None
    return {k: _value(v) for k, v in record.items() if not k.startswith("_")}


def rows(records):
    return [row(r) for r in records]
