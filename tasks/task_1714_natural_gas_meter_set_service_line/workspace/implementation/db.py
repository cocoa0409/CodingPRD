"""In-memory data store. All state lives in module-level dicts keyed by id.

The store starts completely empty on every boot — no seeding, no disk
persistence. The test harness restarts the server before every test, so
module-level dicts are the entire database.

The logical clock also lives here; it never falls back to wall-clock time.
"""

import datetime as _dt

# --- Entity stores (keyed by id) ---
builders = {}
service_applications = {}
appliance_loads = {}
main_extensions = {}
ciac_invoices = {}
ciac_payments = {}
permits = {}
field_crews = {}
crew_bookings = {}
inspectors = {}
inspections = {}
meter_sets = {}
purge_leak_tests = {}
turn_on_events = {}
timeline_commitments = {}
gis_as_builts = {}

# --- Logical clock ---
# Before any administrator sets it, the logical clock reads exactly
# 2026-08-01T00:00:00Z. It NEVER falls back to wall-clock time.
_CLOCK_DEFAULT = _dt.datetime(2026, 8, 1, 0, 0, 0, tzinfo=_dt.timezone.utc)
_current_utc = _CLOCK_DEFAULT


def get_current_utc() -> _dt.datetime:
    return _current_utc


def set_current_utc(value: _dt.datetime):
    global _current_utc
    _current_utc = value


def now_iso() -> str:
    """Current logical time as ISO 8601 UTC with three fractional digits."""
    return format_ts(_current_utc)


def format_ts(dt: _dt.datetime) -> str:
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    dt = dt.astimezone(_dt.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def today_date() -> _dt.date:
    return _current_utc.date()
