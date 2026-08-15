"""In-memory data store. All state lives in process memory only.

The store starts empty on every boot. No seeding, preloading, or
hardcoding of any entity data at startup.
"""

import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Entity tables (dicts keyed by id)
# ---------------------------------------------------------------------------

students = {}
vaccine_requirements = {}
immunization_records = {}
exemption_requests = {}
compliance_notices = {}
outbreak_events = {}
clinic_sessions = {}
clinic_appointments = {}
registry_sync_runs = {}
compliance_snapshots = {}

# Test-driving side store: doses planted in the "external" state registry.
# Each entry: {seed_id, student_id, vaccine_code, dose_number, administered_date}
registry_seeds = {}


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_START_CLOCK_ISO = "2026-08-01T00:00:00Z"


def parse_iso(value):
    """Parse an ISO 8601 datetime string to an aware datetime in UTC.

    Accepts trailing 'Z' and fractional seconds.
    """
    if value is None:
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso(dt):
    """Format an aware UTC datetime with three fractional digits and 'Z'."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = f"{dt.microsecond // 1000:03d}"
    return f"{base}.{ms}Z"


class LogicalClock:
    def __init__(self):
        self._now = parse_iso(_START_CLOCK_ISO)

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt.astimezone(timezone.utc)


clock = LogicalClock()


def new_id():
    return str(uuid.uuid4())


def touch(resource):
    """Refresh updated_at and bump version by one."""
    resource["updated_at"] = format_iso(clock.now())
    resource["version"] = int(resource.get("version", 0)) + 1


def stamp_new(resource):
    """Populate the common system fields on a freshly created resource."""
    now = format_iso(clock.now())
    resource.setdefault("id", new_id())
    resource["created_at"] = now
    resource["updated_at"] = now
    resource["version"] = 1
    return resource
