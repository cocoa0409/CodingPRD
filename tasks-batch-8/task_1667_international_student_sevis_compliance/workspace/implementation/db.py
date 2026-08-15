"""In-memory data store for the International Student SEVIS Compliance API.

Storage is plain Python dicts keyed by id. The store starts empty on every
boot; no seeding, no preloading, no on-disk persistence. The logical clock
starts at exactly 2026-08-01T00:00:00Z and advances only through the
POST /_clock/set_current_utc endpoint (PRD §2.5).
"""

import itertools
import re
import uuid
from datetime import date, datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.5). Stored verbatim as last set; parsed for math.
# ---------------------------------------------------------------------------
current_utc_iso = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Entity tables (all keyed by entity id)
# ---------------------------------------------------------------------------
students = {}
financial_documents = {}
sevis_records = {}
i20_forms = {}
term_enrollments = {}
reduced_course_loads = {}
employment_authorizations = {}
employment_periods = {}
travel_endorsements = {}
transfer_requests = {}
program_extensions = {}
status_violations = {}
address_reports = {}

# Global insertion sequence for stable list ordering on created_at ties.
_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


def wall_ts():
    """Wall-clock UTC timestamp with three fractional digits (created_at /
    updated_at rendering per PRD §2.4)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Logical-clock / date helpers
# ---------------------------------------------------------------------------

def parse_clock(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Raises ValueError on malformed input."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)  # may raise ValueError
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clock_dt():
    return parse_clock(current_utc_iso)


def clock_date():
    return clock_dt().date()


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(value):
    """Strictly parse a YYYY-MM-DD calendar date. Raises ValueError."""
    if not isinstance(value, str) or not DATE_RE.match(value):
        raise ValueError("not a YYYY-MM-DD date")
    return date.fromisoformat(value)  # may raise ValueError


def is_date_string(value):
    try:
        parse_date(value)
        return True
    except ValueError:
        return False


def stamp_new(entity):
    ts = wall_ts()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = next_seq()


def touch(entity):
    """Mutation stamp: refresh updated_at and bump version (PRD §2.4)."""
    entity["updated_at"] = wall_ts()
    entity["version"] += 1


def add_months(d, months):
    """Add calendar months to a date, clamping to the target month's last day
    (PRD §2.7 month-arithmetic clamping)."""
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    if m == 12:
        last = date(y, 12, 31).day
    else:
        last = (date(y, m + 1, 1) - timedelta(days=1)).day
    return date(y, m, min(d.day, last))
