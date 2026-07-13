"""In-memory store, logical clock, and common resource properties (PRD §2.4).

The store starts EMPTY on every boot. Nothing is seeded, preloaded or hardcoded.
"""

import itertools
import uuid
from datetime import datetime, timezone

# PRD §2.4: "The server keeps a single logical clock whose value at startup is
# exactly 2026-05-01T00:00:00Z". Time is logical, never wall-clock.
CLOCK_STARTUP_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO 8601 instant. Returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class Store:
    def __init__(self):
        self.plans = {}
        self.subscribers = {}
        self.family_members = {}
        self.bureau_profiles = {}
        self.thaw_windows = {}
        self.alerts = {}
        self.specialists = {}
        self.cases = {}
        self.engagements = {}
        self.claims = {}
        self.wallet_items = {}
        self.clock = CLOCK_STARTUP_DEFAULT
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def now():
    """The logical clock."""
    return db.clock


def now_iso():
    return fmt_dt(db.clock)


def new_row(**fields):
    """Every persisted resource carries id / created_at / updated_at / version."""
    stamp = now_iso()
    row = {
        "id": str(uuid.uuid4()),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
    }
    row.update(fields)
    row["_seq"] = db.next_seq()
    return row


def touch(row):
    """Every mutation rewrites updated_at and increments version by exactly one."""
    row["updated_at"] = now_iso()
    row["version"] = row["version"] + 1
    return row


def serialize(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def by_seq(rows):
    return sorted(rows, key=lambda r: r["_seq"])
