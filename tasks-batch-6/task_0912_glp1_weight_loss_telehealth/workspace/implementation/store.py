"""In-memory store, logical clock and common-field bookkeeping.

Storage is process-local Python dictionaries only.  Nothing is persisted, no
file or database is touched, and the store starts completely empty on every
boot: every entity a caller needs is created through the declared endpoints.
"""

import itertools
import re
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.4 -- the logical clock reads exactly this before any client moves it.
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_iso(value):
    """Parse an ISO-8601 instant into an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso(dt):
    """Render an instant as ISO-8601 UTC with exactly three fractional digits.

    PRD 2.5: created_at / updated_at (and every other server-written stamp)
    carry three fractional digits and a trailing Z.
    """
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def _has_fraction(value):
    m = _ISO_RE.match(value.strip()) if isinstance(value, str) else None
    return bool(m and m.group(7))


def shift_preserving_style(iso_value, days):
    """Add `days` to an ISO instant, rendering it the way its source was written.

    Used for the billing-cycle window: `period_end_at` is `period_start_at`
    plus thirty days, and the next cycle's `period_start_at` is that exact
    string, so an anchor supplied without fractional digits keeps that shape
    all the way down the chain (PRD 3.9).
    """
    dt = parse_iso(iso_value)
    if dt is None:
        return None
    moved = dt + timedelta(days=days)
    if _has_fraction(iso_value):
        return format_iso(moved)
    return "%04d-%02d-%02dT%02d:%02d:%02dZ" % (
        moved.year, moved.month, moved.day, moved.hour, moved.minute, moved.second,
    )


def whole_days_between(start_dt, end_dt):
    """PRD 2.4: seconds difference divided by 86,400 with the remainder dropped."""
    if start_dt is None or end_dt is None:
        return 0
    seconds = (end_dt - start_dt).total_seconds()
    return int(seconds // 86400)


class Store:
    """Every collection in the system, keyed by id."""

    COLLECTIONS = (
        "patients",
        "providers",
        "pharmacies",
        "supply_lots",
        "screenings",
        "consults",
        "prescriptions",
        "titration_steps",
        "prior_authorizations",
        "pharmacy_orders",
        "subscriptions",
        "billing_cycles",
        "check_ins",
        "coaching_sessions",
    )

    def __init__(self):
        self.reset()

    def reset(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self._seq = itertools.count(1)
        self.clock_raw = DEFAULT_CLOCK_ISO
        self.clock_dt = parse_iso(DEFAULT_CLOCK_ISO)

    # -- clock ------------------------------------------------------------
    def set_clock(self, raw, dt):
        self.clock_raw = raw
        self.clock_dt = dt

    def now_dt(self):
        return self.clock_dt

    def now_iso(self):
        return format_iso(self.clock_dt)

    # -- identity ---------------------------------------------------------
    def next_seq(self):
        return next(self._seq)

    def new_id(self):
        return str(uuid.uuid4())


store = Store()


def new_record(collection, fields):
    """Create a row with the four common fields of PRD 2.5."""
    now = store.now_iso()
    record = {"id": store.new_id()}
    record.update(fields)
    record["created_at"] = now
    record["updated_at"] = now
    record["version"] = 1
    record["_seq"] = store.next_seq()
    collection[record["id"]] = record
    mark_touched(record)
    return record


# -- per-request mutation bookkeeping --------------------------------------
_TOUCHED_KEY = "_glp1_touched"


def _touched_set():
    try:
        from flask import g, has_request_context
    except Exception:  # pragma: no cover - flask is always present
        return None
    if not has_request_context():
        return None
    bucket = getattr(g, _TOUCHED_KEY, None)
    if bucket is None:
        bucket = set()
        setattr(g, _TOUCHED_KEY, bucket)
    return bucket


def mark_touched(record):
    bucket = _touched_set()
    if bucket is not None:
        bucket.add(id(record))


def touch(record):
    """Refresh updated_at and bump version once per row per request (PRD 2.5)."""
    if record is None:
        return record
    bucket = _touched_set()
    if bucket is not None and id(record) in bucket:
        record["updated_at"] = store.now_iso()
        return record
    record["updated_at"] = store.now_iso()
    record["version"] = record.get("version", 1) + 1
    if bucket is not None:
        bucket.add(id(record))
    return record


def ordered(records):
    """PRD 2.3 default ordering: creation timestamp ascending (stable)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
