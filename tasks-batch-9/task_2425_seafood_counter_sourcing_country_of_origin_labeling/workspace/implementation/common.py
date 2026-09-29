"""Shared primitives: rounding discipline, timestamp rendering, record touch."""

from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone

from flask import g

from store import db, new_id

ZERO3 = Decimal("0.000")
ZERO2 = Decimal("0.00")


def rhu(value, places):
    """Round half up to `places` decimal places (PRD 2.7)."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quant = Decimal(1).scaleb(-places)
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def cents(value):
    """Round half up to whole cents, as an int."""
    return int(rhu(value, 0))


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def parse_iso(value):
    """Parse an ISO 8601 instant; returns None when unparseable."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    candidate = raw
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(raw, fmt)
                break
            except ValueError:
                parsed = None
        if parsed is None:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def num(value, places):
    """Render a Decimal quantity as a JSON number at the declared precision."""
    if value is None:
        return None
    return float(rhu(value, places))


# --------------------------------------------------------------------------
# record bookkeeping
# --------------------------------------------------------------------------

def base_record(kind, versioned=True):
    record = {
        "id": new_id(),
        "created_at": db.clock,
        "_kind": kind,
        "_seq": db.next_seq(),
        "_versioned": versioned,
    }
    if versioned:
        record["updated_at"] = db.clock
        record["version"] = 1
    created = getattr(g, "created", None)
    if created is None:
        created = set()
        g.created = created
    created.add(record["id"])
    return record


def touch(record):
    """Mark a record mutated.  PRD 2.4: updated_at is refreshed and version
    incremented once for the record per mutating request (including cascades and
    refreshes of purely derived fields)."""
    if record is None or not record.get("_versioned"):
        return
    dirty = getattr(g, "dirty", None)
    if dirty is None:
        dirty = {}
        g.dirty = dirty
    dirty[record["id"]] = record


def commit():
    dirty = getattr(g, "dirty", None) or {}
    created = getattr(g, "created", None) or set()
    for record_id, record in dirty.items():
        if record_id in created:
            continue
        record["updated_at"] = db.clock
        record["version"] = record.get("version", 1) + 1


def sort_records(items):
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
