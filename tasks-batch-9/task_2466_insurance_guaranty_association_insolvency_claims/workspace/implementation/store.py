"""In-memory data store, logical clock and id/sequence minting.

The store is empty on every boot: no entity is ever seeded, preloaded or
hardcoded.  Every row is created through the declared API surface.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.4: "The clock's startup default is exactly 2026-08-01T00:00:00Z, and the
# server never falls back to real time."
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        # one dict per collection, keyed by id
        self.coverage_profiles = {}
        self.insolvencies = {}
        self.member_insurers = {}
        self.assessments = {}
        self.member_assessments = {}
        self.poc_transfers = {}
        self.policies = {}
        self.claims = {}
        self.other_insurance = {}
        self.vendor_assignments = {}
        self.refunds = {}
        self.referrals = {}
        self.now = CLOCK_DEFAULT
        self._counters = {}

    def next_sequence(self, key):
        value = self._counters.get(key, 0) + 1
        self._counters[key] = value
        return value


store = Store()


def new_id():
    """Server-minted UUID with no type prefix (PRD 2.4)."""
    return str(uuid.uuid4())


def now_dt():
    return store.now


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
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


def now_iso():
    return fmt_dt(store.now)


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,6}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_date(value):
    """Strict ISO 8601 calendar date (YYYY-MM-DD) -> datetime.date or None."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return datetime(int(value[0:4]), int(value[5:7]), int(value[8:10])).date()
    except ValueError:
        return None


def parse_datetime(value):
    """Flexible ISO 8601 instant parser -> aware datetime in UTC, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    match = _DT_RE.match(text)
    if match:
        year, month, day, hour, minute, second, frac, offset = match.groups()
        micro = 0
        if frac:
            micro = int((frac + "000000")[:6])
        try:
            base = datetime(
                int(year),
                int(month),
                int(day),
                int(hour),
                int(minute),
                int(second or 0),
                micro,
                tzinfo=timezone.utc,
            )
        except ValueError:
            return None
        if offset and offset not in ("Z", "z"):
            sign = 1 if offset[0] == "+" else -1
            digits = offset[1:].replace(":", "")
            delta = timedelta(hours=int(digits[0:2]), minutes=int(digits[2:4]))
            base = base - sign * delta
        return base
    # bare calendar date is accepted as midnight UTC
    day_only = parse_date(text)
    if day_only is not None:
        return datetime(day_only.year, day_only.month, day_only.day, tzinfo=timezone.utc)
    return None


def date_to_str(value):
    if value is None:
        return None
    return "%04d-%02d-%02d" % (value.year, value.month, value.day)


def day_count(start_date, end_date):
    """Whole calendar days from start to end."""
    return (end_date - start_date).days


def stamp_new(row):
    """Apply the common lifecycle fields (PRD 2.4) to a freshly created row."""
    ts = now_iso()
    row["id"] = new_id()
    row["created_at"] = ts
    row["updated_at"] = ts
    row["version"] = 1
    row["_seq_created"] = store.next_sequence("_global_insertion")
    return row


def touch(row):
    """Every mutation refreshes updated_at and advances version (PRD 2.4)."""
    row["updated_at"] = now_iso()
    row["version"] = row.get("version", 1) + 1
    return row


def sort_rows(rows):
    """Default list ordering: created_at ascending, insertion order as tie-break."""
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq_created", 0)))
