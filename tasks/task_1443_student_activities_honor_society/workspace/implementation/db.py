"""In-memory data store, logical clock, and id/timestamp helpers.

Storage is in-memory only: plain dicts keyed by id. The store starts empty on
every boot; nothing is seeded. All temporal decisions use the logical clock,
which defaults to 2026-08-01T00:00:00Z and never falls back to wall-clock time.
"""

import uuid
from datetime import datetime, timezone

from errors import ERR_INVALID_REQUEST, ApiError

# --- entity stores (all empty at boot; no seeding) ---
chapters = {}
members = {}
cycles = {}
applications = {}
service_entries = {}
elections = {}
votes = {}
officer_roles = {}
meeting_minutes = {}
fundraisers = {}
ledger_entries = {}
dues_payments = {}
probation_cases = {}
athletics_blocks = {}

# monotonic insertion sequence for stable created_at ordering
_seq = [0]

# logical clock; default per PRD section 2.4
_clock = [datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)]


def next_seq():
    _seq[0] += 1
    return _seq[0]


def now():
    return _clock[0]


def set_clock(dt):
    _clock[0] = dt


def iso(dt):
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return iso(_clock[0])


def parse_dt(value, field="timestamp"):
    """Parse an ISO8601 date or datetime string into an aware UTC datetime."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} is not a valid ISO8601 timestamp")
    else:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} must be an ISO8601 string")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def new_id():
    return str(uuid.uuid4())


def academic_year_of(dt):
    """Academic year label for a date: July-December start a new year.

    e.g. 2026-08-01 -> '2026-2027'; 2027-02-15 -> '2026-2027'.
    """
    if dt.month >= 7:
        return f"{dt.year}-{dt.year + 1}"
    return f"{dt.year - 1}-{dt.year}"


def semester_of(dt):
    """FALL covers July-December; SPRING covers January-June."""
    return "FALL" if dt.month >= 7 else "SPRING"
