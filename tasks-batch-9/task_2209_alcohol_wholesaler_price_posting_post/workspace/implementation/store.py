"""In-memory store, the logical posting clock and record revision discipline.

Everything lives in process memory only (PRD section 2.4 / 2.5); nothing is ever
written to disk, so a fresh process starts with an empty store and the logical
clock at 2026-08-01T00:00:00.000Z.
"""

import re
import threading
import uuid
from datetime import datetime, timedelta, timezone

from flask import g

SECONDS_PER_DAY = 86400
INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=timezone.utc)

# Serialise request handling so cascades are atomic with respect to each other.
request_lock = threading.RLock()


class Store:
    """Plain dict storage, keyed by record id, in insertion order."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = INITIAL_CLOCK
        self.seq_counter = 0
        self.seq = {}
        self.state_programs = {}
        self.wholesalers = {}
        self.licensee_users = {}
        self.brands = {}
        self.price_schedules = {}
        self.price_schedule_items = {}
        self.quantity_discount_tiers = {}
        self.combination_sales = {}
        self.hold_amendments = {}
        self.error_corrections = {}
        self.retailer_invoices = {}
        self.invoice_lines = {}
        self.compliance_audits = {}
        self.audit_findings = {}


db = Store()


# ---------------------------------------------------------------------------
# datetime helpers -- every emitted instant carries three fractional digits.
# ---------------------------------------------------------------------------
_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:[.,](\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?)?$"
)

MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def parse_iso(value):
    """Parse an ISO-8601 instant. Returns a tz-aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    m = _DT_RE.match(text)
    if not m:
        return None
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hour = int(m.group(4) or 0)
    minute = int(m.group(5) or 0)
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    offset = m.group(8)
    if hour > 23 or minute > 59 or second > 59:
        return None
    micro = 0
    if frac:
        micro = int((frac + "000000")[:6])
    try:
        naive = datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        return None
    if offset in (None, "Z", "z"):
        tz = timezone.utc
    else:
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        tz = timezone(sign * timedelta(hours=int(body[:2]), minutes=int(body[2:4])))
    aware = naive.replace(tzinfo=tz).astimezone(timezone.utc)
    # normalise to millisecond precision (truncating, never rounding)
    return aware.replace(microsecond=(aware.microsecond // 1000) * 1000)


def fmt_iso(dt):
    """Render a datetime as an ISO-8601 UTC instant with three fractional digits."""
    if dt is None:
        return None
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


def now_dt():
    return db.clock


def now_iso():
    return fmt_iso(db.clock)


def set_clock(dt):
    db.clock = dt


def dt_of(value):
    """Parse a stored instant string (already normalised) into a datetime."""
    if value is None:
        return None
    return parse_iso(value)


def month_of(instant_string):
    """The YYYY-MM UTC month of a stored instant string."""
    dt = dt_of(instant_string)
    if dt is None:
        return None
    return "%04d-%02d" % (dt.year, dt.month)


# ---------------------------------------------------------------------------
# record creation and the section 2.5 revision rule
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def register_seq(record_id):
    db.seq_counter += 1
    db.seq[record_id] = db.seq_counter


def seq_of(record):
    return db.seq.get(record["id"], 0)


def new_record(fields, versioned=True):
    """Create a record dict carrying the common fields plus the supplied payload."""
    stamp = now_iso()
    record = {"id": new_id(), "created_at": stamp}
    if versioned:
        record["updated_at"] = stamp
        record["version"] = 1
    record.update(fields)
    register_seq(record["id"])
    return record


def _bumped():
    marks = getattr(g, "_bumped_records", None)
    if marks is None:
        marks = set()
        g._bumped_records = marks
    return marks


def bump(record):
    """Refresh updated_at and increment version -- at most once per request."""
    if record is None:
        return
    marks = _bumped()
    key = id(record)
    if key in marks:
        return
    marks.add(key)
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 0) + 1


def snapshot(record, keys=None):
    """Copy the stored fields of a record for later change detection."""
    if keys is None:
        keys = [k for k in record if k not in ("updated_at", "version")]
    out = {}
    for k in keys:
        v = record.get(k)
        out[k] = list(v) if isinstance(v, list) else v
    return out


def bump_if_changed(record, before):
    """Apply the revision rule only when a stored field actually changed."""
    for key, old in before.items():
        new = record.get(key)
        if isinstance(old, list) or isinstance(new, list):
            if list(old or []) != list(new or []):
                bump(record)
                return True
        elif old != new:
            bump(record)
            return True
    return False


def sorted_records(records):
    """Sort by created_at ascending, insertion order breaking ties."""
    return sorted(records, key=lambda r: (dt_of(r["created_at"]), seq_of(r)))
