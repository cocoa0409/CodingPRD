"""In-memory storage, the logical plant clock, and row helpers.

Everything lives in module-level dicts; nothing is ever written to disk, so all
state vanishes with the process. No entity data is ever seeded here.
"""
import itertools
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import g

# ---------------------------------------------------------------------------
# Logical clock — a fresh process reads 2026-08-01T00:00:00.000Z
# ---------------------------------------------------------------------------
_CLOCK = {"now": datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=timezone.utc)}


def now():
    return _CLOCK["now"]


def set_now(dt):
    _CLOCK["now"] = dt
    return _CLOCK["now"]


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------
suppliers = {}
documents = {}
lots = {}
tests = {}
units = {}
charges = {}
windows = {}
contracts = {}
nominations = {}
runs = {}
allocations = {}
batches = {}
pathways = {}
blocks = {}
hedges = {}

_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_iso(value):
    """Parse an ISO-8601 instant. Returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def start_of_day(d):
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def end_of_day(d):
    return start_of_day(d) + timedelta(days=1) - timedelta(microseconds=1)


def date_range(first, last):
    """Inclusive list of UTC dates from first..last (both date objects)."""
    out = []
    cur = first
    while cur <= last:
        out.append(cur)
        cur = cur + timedelta(days=1)
    return out


# ---------------------------------------------------------------------------
# Row helpers
# ---------------------------------------------------------------------------
def new_row(versioned=True):
    stamp = now()
    row = {"id": new_id(), "_seq": next(_seq), "_created": stamp}
    if versioned:
        row["_updated"] = stamp
        row["version"] = 1
    return row


def _touched():
    try:
        bucket = g._touched_rows
    except Exception:
        return None
    return bucket


def bump(row):
    """Increment version / refresh updated_at at most once per request per row."""
    if row is None or "version" not in row:
        return row
    bucket = _touched()
    key = row["id"]
    if bucket is not None:
        if key in bucket:
            return row
        bucket.add(key)
    row["version"] = row["version"] + 1
    row["_updated"] = now()
    return row


def sort_rows(rows):
    return sorted(rows, key=lambda r: (r["_created"], r["_seq"]))


def table_rows(table):
    return sort_rows(list(table.values()))


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------
_EXP = {n: Decimal(1).scaleb(-n) for n in range(0, 8)}


def q(value, places):
    return Decimal(value).quantize(_EXP[places], rounding=ROUND_HALF_UP)


def trunc(value):
    return int(Decimal(value).to_integral_value(rounding="ROUND_DOWN"))
