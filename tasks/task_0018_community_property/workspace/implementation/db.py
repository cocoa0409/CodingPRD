"""In-memory data store for the community property API.

Holds the full set of entity tables, the logical clock, and a few uniqueness indexes
that the validation layer consults. Every entity lives in a dict keyed by its UUID.

The logical clock (`_clock`) is the system's source of `now()`. It is initialized
to real wall-clock UTC at process start, but every successful POST /_clock/advance
overrides it. Auto-transitions (overdue, dunning, work-order auto-confirm,
reservation no-show) read this clock.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
_clock_lock = threading.Lock()
_clock: datetime = datetime.now(timezone.utc)


def now() -> datetime:
    """Returns the system's current logical instant (UTC-aware)."""
    with _clock_lock:
        return _clock


def set_clock(t: datetime) -> None:
    """Overrides the logical clock. Called only by the clock-advance handler."""
    global _clock
    with _clock_lock:
        _clock = t


# ---------------------------------------------------------------------------
# IDs and timestamps
# ---------------------------------------------------------------------------
def new_id() -> str:
    """UUID4 with no prefix, per PRD §2.4."""
    return str(uuid.uuid4())


def iso_ts(t: datetime | None = None) -> str:
    """ISO 8601 UTC with three fractional digits."""
    if t is None:
        t = now()
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    else:
        t = t.astimezone(timezone.utc)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Entity tables
# ---------------------------------------------------------------------------
owners: dict[str, dict] = {}
properties: dict[str, dict] = {}
residents: dict[str, dict] = {}
work_orders: dict[str, dict] = {}
fee_billing_rules: dict[str, dict] = {}
fee_bills: dict[str, dict] = {}
payment_records: dict[str, dict] = {}
facilities: dict[str, dict] = {}
reservations: dict[str, dict] = {}
proposals: dict[str, dict] = {}
votes: dict[str, dict] = {}
parking_spaces: dict[str, dict] = {}
parking_applications: dict[str, dict] = {}
access_logs: dict[str, dict] = {}
audit_entries: dict[str, dict] = {}

# Per-proposal eligible-voter snapshot:
# proposal_id -> { (owner_id, property_id) -> weight }
proposal_eligibility: dict[str, dict] = {}

# A coarse global mutation lock — these benchmarks are single-process and
# tests don't require fine-grained concurrency, but we serialize critical
# writes (parking-space approval, vote insert, payment idempotency check,
# reservation slot insert) under this lock.
mutation_lock = threading.RLock()


def reset_all() -> None:
    """Wipe the store — useful for tests."""
    for d in (
        owners, properties, residents, work_orders, fee_billing_rules,
        fee_bills, payment_records, facilities, reservations, proposals,
        votes, parking_spaces, parking_applications, access_logs,
        audit_entries, proposal_eligibility,
    ):
        d.clear()
    set_clock(datetime.now(timezone.utc))
