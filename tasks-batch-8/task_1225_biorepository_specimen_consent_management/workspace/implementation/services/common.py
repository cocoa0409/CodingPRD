"""Shared service helpers: record factory, timestamp handling, lookups."""
from datetime import datetime, timezone

import db
from clock import now
from errors import raise_error


def iso_now_str():
    """created_at/updated_at strings: ISO8601 UTC with 3 fractional digits.

    Uses the logical clock so timestamps advance with the test clock; appends
    a monotonic counter-based microsecond fraction to keep ordering stable.
    """
    base = now()
    # Preserve insertion-order tie-breaks via a global sequence.
    iso_now_str.counter += 1
    micros = (iso_now_str.counter % 1000) * 1000  # 0..999000
    dt = base.replace(microsecond=micros)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{micros // 1000:03d}Z"


iso_now_str.counter = 0


def make_record(collection, fields):
    rec_id = db.new_id()
    ts = iso_now_str()
    rec = {
        "id": rec_id,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    rec.update(fields)
    collection[rec_id] = rec
    return rec


def make_audit_record(collection, fields):
    rec_id = db.new_id()
    rec = {
        "id": rec_id,
        "created_at": iso_now_str(),
    }
    rec.update(fields)
    collection[rec_id] = rec
    return rec


def touch(rec):
    """Refresh updated_at and bump version."""
    rec["updated_at"] = iso_now_str()
    rec["version"] += 1


def touch_no_version(rec):
    rec["updated_at"] = iso_now_str()


def get_or_404(collection, rec_id, label="resource"):
    rec = collection.get(rec_id)
    if rec is None:
        raise_error("ERR_NOT_FOUND", f"{label} not found: {rec_id}")
    return rec


def round3(value):
    from decimal import Decimal, ROUND_HALF_UP
    return float(Decimal(str(value)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def round2(value):
    from decimal import Decimal, ROUND_HALF_UP
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def round0(value):
    from decimal import Decimal, ROUND_HALF_UP
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
