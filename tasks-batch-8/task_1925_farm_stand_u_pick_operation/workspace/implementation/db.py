"""In-memory data store. Starts EMPTY on every boot — no seeding whatsoever.

All state lives in module-level dicts keyed by server-minted UUID. The test
harness kills and re-launches the server before every test, so every boot is a
fresh process with empty stores.
"""

import uuid
from datetime import datetime, timezone

# --- Entity stores (empty at startup; tests build all state via the API) ---
seasons = {}
crops = {}
fields = {}
windows = {}           # FieldDayWindow
pricing_policies = {}
waivers = {}
visit_sessions = {}
harvest_lines = {}
addon_products = {}
addon_bookings = {}
payments = {}
sales_days = {}
offline_batches = {}

# Monotonic insertion sequence (created_at ASC tie-break stability).
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    return str(uuid.uuid4())


# --- Logical clock (PRD §2.4) ---
# Startup default is exactly 2026-08-01T00:00:00Z; never falls back to
# wall-clock time; advances only via POST /farm/_clock/set_current_utc.
_logical_now = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def logical_now():
    return _logical_now


def set_logical_now(dt):
    global _logical_now
    _logical_now = dt


def logical_date_str():
    return _logical_now.strftime("%Y-%m-%d")


def logical_hhmm_str():
    return _logical_now.strftime("%H:%M")


# --- Monotonic wall-clock timestamps for created_at / updated_at ---
# Business rules read the logical clock; entity timestamps are ISO 8601 UTC
# with three fractional digits and are kept strictly increasing so that
# created_at ASC ordering and created_at tie-breaks are always well-defined.
_last_ts = None


def wall_ts():
    """ISO 8601 UTC timestamp with 3 fractional digits, strictly increasing."""
    global _last_ts
    now = datetime.now(timezone.utc)
    if _last_ts is not None and now <= _last_ts:
        from datetime import timedelta
        now = _last_ts + timedelta(milliseconds=1)
    _last_ts = now
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
