"""In-memory data store. The store starts empty on every boot; no seeding."""
import uuid
from datetime import datetime, timezone

DB = {
    "license_types": {},
    "role_requirements": {},
    "employees": {},
    "licenses": {},
    "verification_events": {},
    "ce_activities": {},
    "renewal_requests": {},
    "disciplinary_events": {},
    "exclusion_screenings": {},
    "audit_packages": {},
}

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# The logical clock (PRD section 2.5). Starts at the fixed instant and is only
# advanced via POST /licensing/_clock/set_current_utc; never wall-clock based.
CLOCK = {"current_utc": DEFAULT_CLOCK}


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Wall-clock UTC timestamp, ISO 8601 with three fractional digits."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def current_dt():
    """The logical clock instant as an aware datetime (UTC)."""
    text = CLOCK["current_utc"]
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def current_date():
    """The calendar date (UTC) of the logical clock's current instant."""
    return current_dt().date()


def current_timestamp_iso():
    """Logical clock instant rendered with three fractional digits, Z suffix."""
    n = current_dt()
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"
