"""In-memory data store, logical clock, and id/timestamp helpers.

The store starts completely empty on every boot: no seeding, no preloading.
"""
import itertools
import uuid
from datetime import datetime, date, timezone, timedelta

# --- entity tables (keyed by id) -----------------------------------------
facilities = {}
seasons = {}
pass_holders = {}
season_passes = {}
admissions = {}
lesson_levels = {}
lesson_sessions = {}
enrollments = {}
lifeguards = {}
shifts = {}
chemistry_logs = {}
lane_allocations = {}
rentals = {}
incident_reports = {}
closures = {}

# --- logical clock ---------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = DEFAULT_CLOCK

_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


def now():
    return _clock


def today():
    return _clock.date()


def set_clock(dt):
    global _clock
    _clock = dt


def iso(dt):
    """Serialize a datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def iso_date(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        d = d.date()
    return d.isoformat()


def now_iso():
    return iso(_clock)


def touch(entity):
    """Refresh updated_at and bump version on a mutated resource."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


def base_fields():
    """Common system fields for a newly created resource."""
    ts = now_iso()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def parse_datetime(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse an ISO date (or datetime) string into a date, or None."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10]) if len(s) >= 10 else date.fromisoformat(s)
    except ValueError:
        return None


def date_or_datetime_to_date(value):
    """Accept an ISO date or datetime string; return a date or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    try:
        if "T" in s or " " in s:
            dt = parse_datetime(s)
            return dt.date() if dt else None
        return date.fromisoformat(s)
    except ValueError:
        return None


def day_start(d):
    """datetime at 00:00:00 UTC for a date."""
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def age_years(dob, on_date):
    """Floor age in years of a person born on `dob` observed on `on_date`."""
    years = on_date.year - dob.year
    if (on_date.month, on_date.day) < (dob.month, dob.day):
        years -= 1
    return years
