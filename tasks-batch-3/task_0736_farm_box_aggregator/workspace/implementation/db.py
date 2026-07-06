"""In-memory data store and primitives.

Storage is process-local Python dicts ONLY. There is no disk / SQLite / cache.
Every re-launch of start.sh starts from a completely empty store. NOTHING is
seeded, preloaded or hardcoded here — tests build all state via the API.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Entity tables (keyed by id)
# ---------------------------------------------------------------------------
farms = {}
products = {}
market_cycles = {}
offerings = {}
pickup_hubs = {}
customers = {}
subscriptions = {}
orders = {}
order_lines = {}
settlements = {}

# ---------------------------------------------------------------------------
# Constants (verbatim from PRD / SCAFFOLD calculations)
# ---------------------------------------------------------------------------
DOUBLEUP_CAP_CENTS = 2000                      # PRD 3.6 / calc order_benefit_application
BOX_TARGET_CENTS = {"SMALL": 1500, "MEDIUM": 3000, "LARGE": 6000}  # PRD 3.4
CYCLE_BUFFER = timedelta(hours=24)             # PRD 3.2 window buffer
ROLES = {"PlatformAdmin", "Farm", "Customer"}  # PRD 2.1

# ---------------------------------------------------------------------------
# Monotonic system clock for created_at / updated_at.
# created_at is the sole deterministic ordering key (PRD 2.3, 3.4). We keep it
# strictly increasing so list order == creation order without ever using id.
# ---------------------------------------------------------------------------
_seq_counter = itertools.count(1)
_last_ts = None


def _fmt(dt):
    # ISO 8601 UTC with exactly three fractional digits + Z (PRD 2.2 / 2.4)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def sys_now_iso():
    """Strictly-increasing system timestamp (ms precision)."""
    global _last_ts
    now = datetime.now(timezone.utc)
    if _last_ts is not None and now <= _last_ts:
        now = _last_ts + timedelta(milliseconds=1)
    _last_ts = now
    return _fmt(now)


def wall_now_iso():
    """Non-monotonic wall clock for api_request_timestamp."""
    return _fmt(datetime.now(timezone.utc))


def next_seq():
    return next(_seq_counter)


def new_id():
    return str(uuid.uuid4())   # UUID, no type prefix (PRD 2.4)


# ---------------------------------------------------------------------------
# Logical clock (test-driving, PRD 2.10). Defaults to a fixed instant and never
# reads wall-clock.
# ---------------------------------------------------------------------------
logical_clock = {"value": "2026-03-01T00:00:00Z"}


def new_entity(kind, common=True, **fields):
    """Create a base entity record with system-managed fields."""
    now = sys_now_iso()
    ent = {"id": new_id(), "_kind": kind, "_seq": next_seq()}
    ent["created_at"] = now
    if common:
        ent["updated_at"] = now
        ent["version"] = 1
    ent.update(fields)
    return ent


def touch(entity):
    """Register a mutation: bump version + refresh updated_at (PRD 2.4)."""
    entity["version"] += 1
    entity["updated_at"] = sys_now_iso()
