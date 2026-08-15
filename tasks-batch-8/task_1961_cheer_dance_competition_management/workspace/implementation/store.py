"""In-memory data store, logical clock, and timestamp/identity helpers.

The store starts completely empty on every boot — no seeding. Every entity a
test needs is built through the declared API surface.

All time-dependent rules are evaluated against a logical clock (never the
wall clock). Startup default: 2026-08-01T00:00:00Z.
"""
import itertools
import re
import uuid
from datetime import date, datetime, timedelta, timezone

from errors import ApiError

CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.seq = itertools.count(1)
        self.clock = CLOCK_DEFAULT
        self.events = {}
        self.divisions = {}
        self.teams = {}
        self.athletes = {}
        self.roster_entries = {}
        self.judges = {}
        self.performances = {}
        self.score_sheets = {}
        self.deductions = {}
        self.appeals = {}
        self.bids = {}
        self.music_submissions = {}
        self.sessions = {}
        self.ticket_orders = {}
        self.warmup_assignments = {}


db = Store()


# ---------------------------------------------------------------------------
# Clock / timestamps
# ---------------------------------------------------------------------------

def now():
    return db.clock


def iso(dt):
    """ISO 8601 UTC; fractional seconds (3 digits) only when nonzero."""
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        base += ".%03d" % (dt.microsecond // 1000)
    return base + "Z"


def now_iso():
    return iso(db.clock)


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(value, field):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise ApiError("ERR_INVALID_INPUT", 400,
                       f"Field '{field}' must be a date string YYYY-MM-DD")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise ApiError("ERR_INVALID_INPUT", 400,
                       f"Field '{field}' is not a valid calendar date")


def parse_datetime(value, field):
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_INPUT", 400,
                       f"Field '{field}' must be an ISO 8601 datetime string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise ApiError("ERR_INVALID_INPUT", 400,
                       f"Field '{field}' is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def full_years(dob: date, ref: date) -> int:
    """Full years elapsed between date_of_birth and the reference date."""
    return ref.year - dob.year - ((ref.month, ref.day) < (dob.month, dob.day))


# ---------------------------------------------------------------------------
# Identity / stamping / mutation
# ---------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def stamp(rec):
    """Attach the standard system-managed fields to a new record."""
    rec["id"] = new_id()
    rec["created_at"] = now()
    rec["updated_at"] = now()
    rec["version"] = 1
    rec["_seq"] = next(db.seq)
    return rec


def touch(rec):
    """One mutation event on a resource: refresh updated_at, version += 1."""
    rec["updated_at"] = now()
    rec["version"] += 1


def set_fields(rec, **fields):
    """Apply field changes; bump version exactly once if anything changed."""
    changed = False
    for key, value in fields.items():
        if rec.get(key) != value:
            rec[key] = value
            changed = True
    if changed:
        touch(rec)
    return changed


def by_created(items):
    """Deterministic created_at ASC ordering (oldest first)."""
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
