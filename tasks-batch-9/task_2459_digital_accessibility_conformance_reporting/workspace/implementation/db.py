"""In-memory data store and time helpers.

Storage is process-local Python dicts keyed by id.  The store is EMPTY on every
boot: nothing is seeded, preloaded or hardcoded.
"""
import re
import uuid
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal

# PRD 2.4: "The clock begins at 2026-08-01T00:00:00Z"
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.standards = {}
        self.criteria = {}
        self.products = {}
        self.components = {}
        self.environments = {}
        self.runs = {}
        self.assessments = {}
        self.reports = {}
        self.trains = {}
        self.issues = {}
        self.questionnaires = {}
        self.complaints = {}
        self.clock = DEFAULT_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# --------------------------------------------------------------------------- #
# time helpers — every temporal rule runs against the logical clock (PRD 2.4)
# --------------------------------------------------------------------------- #
def clock_now():
    return db.clock


def clock_date():
    return db.clock.astimezone(timezone.utc).date()


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return fmt_dt(db.clock)


def dt_plus_days(days):
    return db.clock + timedelta(days=days)


def iso_plus_days(days):
    return fmt_dt(db.clock + timedelta(days=days))


_DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?"
                    r"([Zz]|[+-]\d{2}:?\d{2})?$")


def parse_datetime(value):
    """Parse an ISO 8601 instant.  Returns an aware datetime or None."""
    if not isinstance(value, str) or not _DT_RE.match(value.strip()):
        return None
    raw = value.strip().replace(" ", "T").replace("t", "T")
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(value):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# row helpers
# --------------------------------------------------------------------------- #
def new_row(fields, versioned=True):
    row = {"id": str(uuid.uuid4())}
    row.update(fields)
    row["created_at"] = now_iso()
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    row["_seq"] = db.next_seq()
    row["_created_dt"] = db.clock
    return row


def touch(row):
    """Refresh updated_at and bump version by exactly 1 (PRD 2.4 / 2.9)."""
    row["updated_at"] = now_iso()
    row["version"] = row.get("version", 0) + 1


def stamp(row):
    """Refresh updated_at without bumping version (used where the version
    contract of PRD 2.9 does not list a bump)."""
    row["updated_at"] = now_iso()


def sort_key(row):
    """Default list ordering: created_at ascending, insertion order as tie-break."""
    return (row.get("created_at") or "", row.get("_seq") or 0)


def public(row, extra=None):
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        out[key] = float(value) if isinstance(value, Decimal) else value
    if extra:
        for key, value in extra.items():
            out[key] = float(value) if isinstance(value, Decimal) else value
    return out
