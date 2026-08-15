"""In-memory data store. Everything lives in module-level dicts keyed by id.

The store starts EMPTY on every boot: no seeding, no preloading, no disk
persistence. All state is built through the API.
"""

import threading
import uuid
from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------------------
# Logical clock (PRD section 2.5). Startup default: exactly 2026-08-01T00:00:00Z.
# Never falls back to wall-clock time.
# ---------------------------------------------------------------------------
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

customers = {}
engineers = {}
jobs = {}
designs = {}
cut_lists = {}
cut_list_lines = {}
jig_setups = {}
inventory_lots = {}
material_reservations = {}
cranes = {}
crane_slots = {}
production_batches = {}
delivery_loads = {}
bundles = {}
damage_claims = {}
design_change_orders = {}

_lock = threading.Lock()
_logical_clock = CLOCK_START
_seq = 0          # monotonic creation sequence (== created_at ASC ordering)
_last_wall = None  # guarantees strictly increasing created_at/updated_at


def get_clock():
    with _lock:
        return _logical_clock


def set_clock(dt):
    global _logical_clock
    with _lock:
        _logical_clock = dt


def new_id():
    return str(uuid.uuid4())


def next_seq():
    global _seq
    with _lock:
        _seq += 1
        return _seq


def now_wall():
    """Strictly-increasing wall timestamp for created_at/updated_at."""
    global _last_wall
    with _lock:
        t = datetime.now(timezone.utc)
        if _last_wall is not None and t <= _last_wall:
            t = _last_wall + timedelta(milliseconds=1)
        _last_wall = t
        return t


def new_record(fields, common=True):
    """Create a record dict with system-managed common fields."""
    rec = dict(fields)
    rec["id"] = new_id()
    rec["_seq"] = next_seq()
    rec["created_at"] = now_wall()
    if common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Mutation of a resource: version += 1 and updated_at refreshes."""
    rec["version"] += 1
    rec["updated_at"] = now_wall()
