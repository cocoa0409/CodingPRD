"""Record -> public JSON serialization.

Datetimes render as ISO 8601 UTC with three fractional digits; Decimals
render as JSON numbers; internal bookkeeping keys (leading underscore) are
stripped.
"""

from datetime import datetime
from decimal import Decimal

from util import iso_z


def serialize(rec):
    out = {}
    for key, value in rec.items():
        if key.startswith("_"):
            continue
        if isinstance(value, datetime):
            out[key] = iso_z(value)
        elif isinstance(value, Decimal):
            out[key] = float(value)
        else:
            out[key] = value
    return out


def serialize_many(recs):
    return [serialize(r) for r in recs]
