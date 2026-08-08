"""Generic row serializer: strips private keys and converts Decimals to floats."""
from decimal import Decimal


def _conv(v):
    if isinstance(v, Decimal):
        return float(v)
    return v


def dump(row):
    return {k: _conv(v) for k, v in row.items() if not k.startswith("_")}
