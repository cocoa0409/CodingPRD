"""In-memory data store. Empty on every boot; no seeding."""
import uuid
from datetime import datetime, timezone, date

# Logical clock: default 2026-05-01T00:00:00Z; advanced only via _clock/set_current_utc.
_logical_clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


def get_clock():
    return _logical_clock


def set_clock(dt):
    global _logical_clock
    _logical_clock = dt


def new_id():
    return str(uuid.uuid4())


def now_iso():
    return iso_of(get_clock())


def iso_of(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse an ISO 8601 datetime (with optional Z) into an aware datetime."""
    if s is None:
        return None
    if isinstance(s, datetime):
        return s
    txt = str(s).strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_date(s):
    if isinstance(s, date) and not isinstance(s, datetime):
        return s
    txt = str(s).strip()
    return date.fromisoformat(txt[:10])


# Entity tables
utility_companies = {}
events = {}
billing_rate_schedules = {}
assistance_requests = {}
crews = {}
safety_briefings = {}
timesheets = {}
lodging_blocks = {}
lodging_assignments = {}
per_diem_claims = {}
invoices = {}
after_action_reports = {}


def reset_all():
    """Full wipe (not used in production path; available for defensive reset)."""
    utility_companies.clear()
    events.clear()
    billing_rate_schedules.clear()
    assistance_requests.clear()
    crews.clear()
    safety_briefings.clear()
    timesheets.clear()
    lodging_blocks.clear()
    lodging_assignments.clear()
    per_diem_claims.clear()
    invoices.clear()
    after_action_reports.clear()
    global _logical_clock
    _logical_clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
