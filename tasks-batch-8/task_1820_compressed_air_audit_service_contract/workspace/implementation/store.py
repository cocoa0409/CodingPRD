"""In-memory data store + logical clock.

Pure module-level dicts: every fresh process boots a fully empty system.
No seeding, no disk persistence, no /tmp caches.
"""

import threading
import uuid
from datetime import datetime, timezone, timedelta

# Big request lock: the Flask dev server is threaded; serialize requests so
# every multi-step cascade is atomic within the triggering request.
STATE_LOCK = threading.RLock()

# --- entity tables (all start empty; tests build everything via the API) ---
facilities = {}
compressors = {}
demand_profiles = {}
leak_surveys = {}
leak_tags = {}
maintenance_schedules = {}
retrofit_projects = {}
savings_cases = {}
service_contracts = {}
service_tickets = {}
rental_assets = {}
rental_reservations = {}
guarantee_certificates = {}
service_credits = {}

# --- logical clock ---
# Startup default is exactly 2026-08-01T00:00:00Z; never falls back to
# wall-clock time. Second granularity, UTC.
_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def get_clock():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt.astimezone(timezone.utc).replace(microsecond=0)
    return _clock


def fmt_clock(dt):
    """Second-granularity ISO 8601 UTC, e.g. 2026-08-01T00:00:00Z."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clock_now_iso():
    return fmt_clock(_clock)


def clock_today():
    return _clock.astimezone(timezone.utc).date()


# --- wall-clock timestamps for created_at/updated_at/meta (ms precision) ---
# Monotonic guard so successive creates never share or invert timestamps;
# created_at ordering backs the spec'd tie-breaks (created_at ASC).
_last_ts = None


def now_ts():
    global _last_ts
    now = datetime.now(timezone.utc)
    now = now.replace(microsecond=(now.microsecond // 1000) * 1000)
    if _last_ts is not None and now <= _last_ts:
        now = _last_ts + timedelta(milliseconds=1)
    _last_ts = now
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


def new_resource():
    """Return the common-field scaffold for a fresh resource."""
    ts = now_ts()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def touch(res):
    """Record a mutation: bump version and refresh updated_at."""
    res["version"] += 1
    res["updated_at"] = now_ts()
