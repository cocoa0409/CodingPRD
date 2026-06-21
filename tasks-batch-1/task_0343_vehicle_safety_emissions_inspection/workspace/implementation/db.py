"""In-memory data store (PRD §2.4). Starts empty on every boot — no seeding."""
import itertools
import uuid
from datetime import datetime, timezone

# One dict per entity type, keyed by id.
stations = {}
vehicle_class_profiles = {}
lanes = {}
analyzer_reservations = {}
appointments = {}
inspection_records = {}
checklist_results = {}
emissions_tests = {}
repair_orders = {}
waiver_requests = {}
certificates = {}
state_report_batches = {}
state_report_lines = {}

# Monotonic insertion sequence to give every entity a stable created order
# (used for created_at ASC sorting; the logical clock can be set arbitrarily
# so created_at alone is not a reliable tiebreaker).
_seq = itertools.count(1)

# Logical clock (PRD §2.11). None until a test sets it.
_clock = {"current": None}


def set_clock(dt):
    _clock["current"] = dt


def now():
    """Logical-clock-aware 'real' wall time used for system timestamps.

    created_at/updated_at use real UTC wall time (server-minted). The logical
    clock (set via /_clock) only governs no-show and reinspection-window
    comparisons, per PRD §2.11.
    """
    return datetime.now(timezone.utc)


def current_clock():
    """The logical current clock (PRD §2.11). None if never set."""
    return _clock["current"]


def now_iso_ms():
    n = now()
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (n.microsecond // 1000)) + "Z"


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def stamp_create(rec, with_version=True):
    """Attach common system fields at create time (PRD §2.4)."""
    rec["id"] = new_id()
    ts = now_iso_ms()
    rec["created_at"] = ts
    rec["_seq"] = next_seq()
    if with_version:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and bump version on mutation (PRD §2.4 / §2.5)."""
    rec["updated_at"] = now_iso_ms()
    rec["version"] = rec.get("version", 1) + 1
