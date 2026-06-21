"""Entity record construction, mutation bookkeeping, and serialization.

Common fields (PRD §2.4):
  - id: server UUID (no prefix)
  - created_at: ISO 8601 UTC, 3 fractional digits
  - updated_at: refreshed on every mutation (same format)
  - version: integer, starts at 1, +1 on each mutation
Underwriter is the exception: only id + created_at (immutable; no updated_at/version).
"""
from decimal import Decimal

from db import db, new_id, now_ts


def base_record(common_fields=True):
    rec = {"id": new_id(), "created_at": now_ts(), "_seq": db.next_seq()}
    if common_fields:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Mark a record mutated: bump updated_at + version (PRD §2.4)."""
    if "version" in rec:
        rec["version"] += 1
        rec["updated_at"] = now_ts()


def _jsonable(value):
    if isinstance(value, Decimal):
        # Emit Decimals as JSON numbers (floats). 2500 -> 2500.0; both compare
        # equal numerically to an int/float expectation in test assertions.
        return float(value)
    return value


def serialize(rec):
    """Public view of a record: drop private keys, coerce Decimals to numbers."""
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        out[k] = _jsonable(v)
    return out


def number_out(value):
    return _jsonable(value)
