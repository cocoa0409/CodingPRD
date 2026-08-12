"""In-memory data store and logical clock.

Storage is in-memory only: plain dicts keyed by id. The store starts empty on
every boot; no entities are seeded at startup. The logical clock starts at
exactly 2026-05-01T00:00:00Z (PRD §2.5) and is only moved by
POST /_clock/set_current_utc.
"""
import itertools
import uuid
from datetime import datetime, timezone, date

stores = {
    "contractors": {},
    "homeowners": {},
    "subcontractors": {},
    "projects": {},
    "assessments": {},
    "designs": {},
    "permits": {},
    "allowance_lines": {},
    "change_orders": {},
    "work_phases": {},
    "site_logs": {},
    "inspections": {},
    "certificates": {},
    "warranty_claims": {},
}

_seq = itertools.count(1)

# Logical clock default: exactly 2026-05-01T00:00:00Z, never wall-clock.
_clock = {"now": datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)}


def new_id():
    return str(uuid.uuid4())


def next_seq():
    """Monotonic insertion counter; stable tiebreak for created_at ordering."""
    return next(_seq)


def clock_now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


def clock_date():
    return _clock["now"].date()


def fmt_ts(dt):
    """ISO 8601 UTC with three fractional digits and Z suffix (PRD §2.4)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_ts():
    return fmt_ts(clock_now())


def parse_iso(s):
    """Parse an ISO 8601 datetime string to an aware UTC datetime, else None."""
    if not isinstance(s, str):
        return None
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    """Parse a strict ISO date (YYYY-MM-DD) to a date, else None."""
    if not isinstance(s, str) or len(s) != 10:
        return None
    try:
        y = int(s[0:4])
        m = int(s[5:7])
        d = int(s[8:10])
        if s[4] != "-" or s[7] != "-":
            return None
        return date(y, m, d)
    except ValueError:
        return None
