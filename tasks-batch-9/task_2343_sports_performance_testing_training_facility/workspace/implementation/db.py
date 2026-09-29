"""In-memory data store, logical UTC clock and shared time helpers.

The store starts completely empty on every boot.  Nothing is ever seeded,
preloaded or hardcoded here: every entity is created exclusively through the
public API surface.
"""

import itertools
import re
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.4 - the logical clock starts at exactly this instant on every boot.
INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "athletes",
    "injury_records",
    "test_sessions",
    "training_programs",
    "program_blocks",
    "group_sessions",
    "enrollments",
    "staff_members",
    "certifications",
    "membership_packages",
    "team_contracts",
    "rts_plans",
    "clearance_documents",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = INITIAL_CLOCK
        self._seq = itertools.count(1)
        for name in COLLECTIONS:
            setattr(self, name, {})

    def next_seq(self):
        return next(self._seq)


store = Store()


# ---------------------------------------------------------------- clock ----
def now():
    """Current logical UTC instant.  Wall-clock time is never consulted."""
    return store.clock


def today():
    return store.clock.date()


def fmt_instant(dt):
    """ISO 8601 UTC with exactly three fractional-second digits (PRD 2.5)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return fmt_instant(store.clock)


# ------------------------------------------------------------- records ----
def new_id():
    return str(uuid.uuid4())


def create(collection, fields):
    rec = {
        "id": new_id(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "_seq": store.next_seq(),
    }
    rec.update(fields)
    collection[rec["id"]] = rec
    return rec


def touch(rec):
    """Every mutation - client driven or server initiated - bumps version."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 0) + 1
    return rec


def sort_key(rec):
    # created_at ASC, with the insertion sequence as a deterministic tiebreak
    # for records created within the same logical millisecond.
    return (rec["created_at"], rec["_seq"])


def ordered(collection):
    if isinstance(collection, dict):
        collection = collection.values()
    return sorted(collection, key=sort_key)


# ---------------------------------------------------------------- time ----
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(value):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_instant(value):
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s[-1] in ("Z", "z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_days(d, n):
    return d + timedelta(days=n)
