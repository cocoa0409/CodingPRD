"""In-memory data store, logical clock, and id/timestamp generation.

Storage is process-local only: plain Python dicts keyed by id. No disk
persistence of any kind. Every fresh process boots with an empty store and
the logical clock at exactly 2026-08-01T00:00:00Z.
"""

import uuid
import random
import string
from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------------------
# Entity tables: dict keyed by id. Insertion order preserved by seq counter.
# ---------------------------------------------------------------------------

TABLES = {
    "suppliers": {},
    "customers": {},
    "warehouses": {},
    "products": {},
    "yield_specs": {},
    "price_sheets": {},
    "price_sheet_lines": {},
    "purchase_orders": {},
    "inventory_lots": {},
    "fabrication_batches": {},
    "forward_contracts": {},
    "allocations": {},
    "shipments": {},
    "temperature_readings": {},
    "claims": {},
    "inspection_certificates": {},
}

# Monotonic creation sequence: deterministic created_at ASC ordering.
_seq = [0]


def next_seq():
    _seq[0] += 1
    return _seq[0]


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


# ---------------------------------------------------------------------------
# Wall-clock timestamps (created_at / updated_at / meta.api_request_timestamp)
# Kept strictly monotonic so created_at ASC ordering always matches insertion
# order even when several resources are created within the same millisecond.
# ---------------------------------------------------------------------------

_last_wall = [None]


def wall_now_iso():
    now = datetime.now(timezone.utc)
    last = _last_wall[0]
    if last is not None and now <= last:
        now = last + timedelta(milliseconds=1)
    _last_wall[0] = now
    millis = now.microsecond // 1000
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


# ---------------------------------------------------------------------------
# Logical trading clock. Starts exactly at 2026-08-01T00:00:00Z and never
# falls back to wall-clock time; only POST /api/_clock/set_current_utc moves
# it.
# ---------------------------------------------------------------------------

_CLOCK = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}


def clock_now():
    return _CLOCK["now"]


def clock_set(dt):
    _CLOCK["now"] = dt


def clock_iso(dt=None):
    dt = dt if dt is not None else _CLOCK["now"]
    if dt.microsecond:
        millis = dt.microsecond // 1000
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
