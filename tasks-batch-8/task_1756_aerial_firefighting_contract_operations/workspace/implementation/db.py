"""In-memory data store and the logical clock.

Storage is in-memory only (Python dicts keyed by id). Nothing is seeded,
preloaded, or persisted; every entity is built via the API surface.
"""
import uuid
from datetime import datetime, timezone

# --- logical clock (PRD §2.7) ---
# Startup default before any set is exactly 2026-08-01T00:00:00Z; the clock
# NEVER falls back to wall-clock time.
_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def clock_now():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


def new_id():
    return str(uuid.uuid4())


_seq = [0]


def next_seq():
    """Monotonic creation counter so entities created within the same
    millisecond still sort deterministically in created_at order."""
    _seq[0] += 1
    return _seq[0]


def stamp_new(entity):
    """Attach created_at metadata and the deterministic creation sequence."""
    entity.setdefault("created_at", iso_now_ms())
    entity["_seq"] = next_seq()
    return entity


def iso_now_ms():
    """ISO 8601 UTC timestamp with three fractional digits, from the wall clock.

    Used only for created_at/updated_at resource metadata stamps (PRD §2.4);
    business deadlines read the logical clock instead.
    """
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def iso_clock_ms():
    """Logical-clock instant formatted with three fractional digits."""
    now = _clock
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


# --- entity stores (empty at boot; nothing is seeded) ---
contracts = {}
aircraft = {}
crew_members = {}
carding_inspections = {}
availability_periods = {}
incidents = {}
dispatch_orders = {}
assignments = {}
flight_logs = {}
retardant_loads = {}
crew_duty_days = {}
invoices = {}
invoice_line_items = {}
agency_records = {}
