"""In-memory data store for the genset-packaging service.

All state lives in module-level dictionaries keyed by resource id.
A fresh process start (via start.sh) resets everything to empty.
"""

import uuid
from datetime import datetime, timezone


def new_id():
    """Generate a server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


def now_iso():
    """Return current UTC time as ISO 8601 with exactly three fractional digits."""
    dt = datetime.now(timezone.utc)
    # Truncate to milliseconds
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
# Startup default: exactly 2026-08-01T00:00:00Z.  The clock NEVER falls back
# to wall-clock time; it is only advanced via POST /_clock/set_current_utc.
_logical_clock_iso = "2026-08-01T00:00:00Z"


def get_logical_clock_iso():
    return _logical_clock_iso


def set_logical_clock_iso(iso_str):
    global _logical_clock_iso
    _logical_clock_iso = iso_str


def logical_today():
    """Return the logical clock's calendar date as 'YYYY-MM-DD'."""
    return _logical_clock_iso[:10]


# ---------------------------------------------------------------------------
# Entity stores — every dict starts empty on boot; no seeding.
# ---------------------------------------------------------------------------
customers = {}
engine_models = {}
alternator_models = {}
orders = {}
sizing_studies = {}
configurations = {}
permit_cases = {}
emissions_certificates = {}
paralleling_schemes = {}
test_bays = {}
factory_tests = {}
crane_slots = {}
shipments = {}
commissioning_events = {}
service_contracts = {}


def stamp_new(record):
    """Populate common system fields on a freshly created record."""
    ts = now_iso()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1


def touch(record):
    """Refresh updated_at and bump version on mutation."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
