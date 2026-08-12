"""In-memory data store, id/timestamp minting and the logical clock.

No entity is ever seeded here: every table starts empty on every boot and
every row a test needs is built through the declared endpoints.
"""

import itertools
import random
import string
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.4 -- the logical clock begins its life at exactly this instant and
# there is no fallback to real time.
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"

TABLES = (
    "operating_periods",
    "fee_scale_bands",
    "participants",
    "caregivers",
    "support_assessments",
    "consents",
    "activity_programs",
    "program_sessions",
    "enrollments",
    "enrollment_charges",
    "staff_members",
    "staff_certifications",
    "staff_assignments",
    "equipment_items",
    "equipment_reservations",
    "transport_runs",
    "transport_bookings",
    "funding_sources",
    "scholarship_awards",
    "goals",
    "goal_ratings",
)

# Entities that carry only id + created_at (PRD 2.6).
NO_COMMON_FIELDS = ("fee_scale_bands", "goal_ratings")


class Store(object):
    def __init__(self):
        self.tables = {}
        self._seq = None
        self.clock_raw = DEFAULT_CLOCK_UTC
        self.reset()

    def reset(self):
        self.tables = dict((name, {}) for name in TABLES)
        self._seq = itertools.count(1)
        self.clock_raw = DEFAULT_CLOCK_UTC

    # -- logical clock ----------------------------------------------------
    @property
    def clock_dt(self):
        return parse_instant(self.clock_raw)

    @property
    def clock_date(self):
        return self.clock_dt.date()

    def next_seq(self):
        return next(self._seq)

    def rows(self, table):
        """All rows of a table in deterministic insertion order."""
        return sorted(self.tables[table].values(), key=lambda r: r["_seq"])

    def get(self, table, ident):
        if not isinstance(ident, str):
            return None
        return self.tables[table].get(ident)


db = Store()


# ---------------------------------------------------------------------------
# identifiers and timestamps
# ---------------------------------------------------------------------------

_REQ_ALPHABET = string.ascii_uppercase + string.digits


def new_id():
    """Server-minted UUID string with no type prefix (PRD 2.6)."""
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choice(_REQ_ALPHABET) for _ in range(20))


def server_now():
    """created_at / updated_at: the server's own UTC clock, 3 fractional digits."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (now.microsecond // 1000)) + "Z"


# ---------------------------------------------------------------------------
# instant / date parsing.  Comparisons are made on the instants denoted, never
# on the strings (PRD 2.6), so two spellings of the same moment compare equal.
# ---------------------------------------------------------------------------


def parse_instant(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text[-1] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_date(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) != 10:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def render_date(value):
    return value.strftime("%Y-%m-%d")


def date_of_instant(value):
    parsed = parse_instant(value)
    return parsed.date() if parsed is not None else None


def add_days(day, count):
    return day + timedelta(days=count)


def whole_years_between(birth, today):
    years = today.year - birth.year
    if (today.month, today.day) < (birth.month, birth.day):
        years -= 1
    return years


# ---------------------------------------------------------------------------
# row lifecycle
# ---------------------------------------------------------------------------

# Per-request set of row ids already version-bumped.  PRD 2.6: "a request bumps
# each affected row once, by one, no matter how many cascade hops touch it."
_touched = set()


def begin_request():
    _touched.clear()


def insert(table, fields):
    row = dict(fields)
    row["id"] = new_id()
    row["created_at"] = server_now()
    row["_seq"] = db.next_seq()
    row["_table"] = table
    if table not in NO_COMMON_FIELDS:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    db.tables[table][row["id"]] = row
    # A freshly created row must not be bumped again later in the same request.
    _touched.add(row["id"])
    return row


def touch(row):
    """Raise version by one and refresh updated_at -- at most once per request."""
    if row is None:
        return row
    if row.get("_table") in NO_COMMON_FIELDS:
        return row
    if row["id"] in _touched:
        return row
    _touched.add(row["id"])
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = server_now()
    return row


def sort_rows(rows):
    """Default ordering: created_at ascending, earlier-inserted row first."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
