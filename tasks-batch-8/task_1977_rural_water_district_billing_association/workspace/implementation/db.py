"""In-memory data store and logical clock.

Storage is in-memory only: plain dicts keyed by id. The store starts empty on
every boot; no seeding of any kind. All timestamps read from a server-side
logical clock (never wall-clock time).
"""
import threading
import uuid
from datetime import datetime, timezone

_lock = threading.Lock()

# Entity stores (dicts keyed by id). All start empty.
districts = {}
service_areas = {}
members = {}
taps = {}
readings = {}            # MeterReading
master_readings = {}     # MasterMeterReading
rate_schedules = {}
billing_cycles = {}
invoices = {}
payments = {}
reserve_entries = {}
boil_orders = {}
notifications = {}       # NotificationReceipt
samples = {}             # ComplianceSample
resolutions = {}         # BoardResolution
petitions = {}           # AnnexationPetition

_seq = 0  # monotone insertion sequence for stable created_at tie-breaking

# Logical clock state. Before any clock call it reads exactly
# 2026-08-01T00:00:00Z and never falls back to wall-clock time.
_clock_dt = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock_raw = "2026-08-01T00:00:00Z"


def new_id():
    return str(uuid.uuid4())


def next_seq():
    global _seq
    with _lock:
        _seq += 1
        return _seq


def fmt_dt(dt):
    """ISO 8601 UTC with three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_dt():
    return _clock_dt


def now_iso():
    return fmt_dt(_clock_dt)


def set_clock(dt, raw):
    global _clock_dt, _clock_raw
    _clock_dt = dt
    _clock_raw = raw


def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware datetime (UTC default)."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
