"""In-memory data store. Empty on every boot — no seeding."""

import uuid
from datetime import datetime, timezone, timedelta

# Entity stores (keyed by id)
membership_levels = {}   # MembershipLevel keyed by id
membership_levels_by_code = {}  # code -> id
premiums = {}
premiums_by_sku = {}
lots = {}
donors = {}
donors_by_email = {}  # lowercased email -> id
memberships = {}
drives = {}
breaks = {}
pledges = {}
reservations = {}
challenges = {}
credits = {}
nffs_reports = {}

# Logical clock — default per PRD 2.8
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_current_utc = CLOCK_DEFAULT


def now():
    return _current_utc


def set_now(dt):
    global _current_utc
    _current_utc = dt


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """Format datetime as ISO 8601 UTC with three fractional digits, e.g. 2026-08-01T00:00:00.000Z"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    s = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    return f"{s}.{ms:03d}Z"


def parse_dt(s):
    """Parse an ISO 8601 datetime string. Returns None on failure."""
    if not isinstance(s, str):
        return None
    try:
        t = s.strip()
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def touch(entity):
    """Bump version + refresh updated_at on a mutated entity."""
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = iso(now())


def new_entity():
    """Common fields for a freshly created entity."""
    ts = iso(now())
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}
