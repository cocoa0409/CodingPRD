"""In-memory data store for the Vinyl Pressing API.

Everything lives in plain Python dicts keyed by id. The store starts empty on
every boot — no seeding, no disk persistence. All entity state is built via
API calls only.
"""

import threading
import uuid
from datetime import datetime, timezone

_lock = threading.RLock()

# Entity collections (all start empty)
customers = {}
releases = {}
press_orders = {}
tooling_jobs = {}
test_pressings = {}
print_jobs = {}
press_lines = {}
press_slots = {}
plating_baths = {}
qc_reports = {}
inventory_lots = {}
shipments = {}
delay_notices = {}
invoices = {}

# Monotonic counters
intake_seq_counter = 0          # plant-wide press-order intake sequence
receipt_seq_by_release = {}     # release_id -> next receipt_seq


# --- Logical clock -----------------------------------------------------------
# Server startup default is exactly 2026-08-01T00:00:00Z and never falls back
# to wall-clock time.
_logical_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def now_logical():
    """Return the current logical clock as a timezone-aware datetime (UTC)."""
    with _lock:
        return _logical_clock


def set_logical_clock(dt):
    global _logical_clock
    with _lock:
        _logical_clock = dt


def today_logical():
    """Return the logical clock's calendar date."""
    return now_logical().date()


def new_id():
    return str(uuid.uuid4())


def next_intake_seq():
    global intake_seq_counter
    with _lock:
        intake_seq_counter += 1
        return intake_seq_counter


def next_receipt_seq(release_id):
    with _lock:
        nxt = receipt_seq_by_release.get(release_id, 0) + 1
        receipt_seq_by_release[release_id] = nxt
        return nxt


def timestamp_now():
    """ISO 8601 UTC timestamp with three fractional digits (wall clock for
    created_at/updated_at fields — the logical clock governs business dates,
    not record metadata timestamps)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
