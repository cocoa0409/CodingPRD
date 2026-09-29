"""In-memory data store and the logical clock (PRD 2.4 / 2.5).

Storage is process-local Python dicts keyed by id.  Nothing is seeded at
startup: every row is created by an API call.
"""
import re
import uuid
from datetime import datetime, timedelta, timezone

# The logical clock reads exactly this instant at process startup and never
# falls back to host wall-clock time (PRD 2.5).
LOGICAL_CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "employees",
    "job_profiles",
    "essential_functions",
    "requests",
    "doc_requests",
    "function_analyses",
    "options",
    "assessments",
    "trials",
    "reviews",
    "denials",
    "appeals",
    "absences",
    "disclosures",
)

# Rows of these two entity types are append-only journal entries: no
# updated_at, no version (PRD 2.4).
JOURNAL_KINDS = {"EffectivenessReview", "MedicalDisclosure"}


def _fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"[Tt ](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6})\d*)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_datetime(value):
    """Parse an ISO 8601 instant (date-only accepted as midnight UTC)."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if _DATE_RE.match(text):
        try:
            d = datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            return None
        return d.replace(tzinfo=timezone.utc)
    m = _ISO_RE.match(text)
    if not m:
        return None
    year, month, day, hh, mm, ss, frac, tz = m.groups()
    micro = int((frac or "0").ljust(6, "0")) if frac else 0
    try:
        dt = datetime(int(year), int(month), int(day), int(hh), int(mm), int(ss), micro)
    except ValueError:
        return None
    if tz in (None, "Z", "z"):
        return dt.replace(tzinfo=timezone.utc)
    sign = 1 if tz[0] == "+" else -1
    body = tz[1:].replace(":", "")
    offset = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
    return (dt - sign * offset).replace(tzinfo=timezone.utc)


def parse_date(value):
    """Parse a strict YYYY-MM-DD calendar date, returning a date object."""
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = LOGICAL_CLOCK_DEFAULT

    # -- logical clock ---------------------------------------------------
    def now(self):
        return self.clock

    def now_iso(self):
        return _fmt(self.clock)

    def today(self):
        return self.clock.date()

    def set_clock(self, dt):
        self.clock = dt.astimezone(timezone.utc)

    # -- row lifecycle ---------------------------------------------------
    def new_row(self, kind, fields):
        row = {"id": str(uuid.uuid4())}
        row.update(fields)
        row["created_at"] = self.now_iso()
        if kind not in JOURNAL_KINDS:
            row["updated_at"] = row["created_at"]
            row["version"] = 1
        row["_kind"] = kind
        return row


store = Store()


def serialize(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def by_created(rows):
    """Stable ascending sort on created_at (insertion order breaks ties)."""
    return sorted(rows, key=lambda r: r["created_at"])
