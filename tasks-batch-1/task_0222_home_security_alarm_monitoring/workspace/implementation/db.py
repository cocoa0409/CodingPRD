"""In-memory data store. Starts EMPTY on every boot — no seeding.

Keyed dicts by entity id, preserving insertion order (Python 3.7+ dicts are
ordered) so that created_at-ascending iteration is the natural insertion order.
A monotonic sequence counter provides a stable created_at tie-break and overall
ordering even when many rows share the same logical clock timestamp.
"""
import uuid

import clock


class Store:
    def __init__(self):
        self.monitoring_plans = {}
        self.accounts = {}
        self.systems = {}
        self.sensors = {}
        self.alarm_events = {}
        self.dispatches = {}
        self.permits = {}
        self.fines = {}
        # Proration segment boundaries per account:
        #   account_id -> list of {at: datetime, tier: str}
        # The first segment is implicitly current_tier at cycle_anchor_utc.
        self.plan_change_segments = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def new_common():
    """System-managed common fields at creation: created_at, updated_at, version."""
    ts = clock.now()
    return {
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(entity):
    """Refresh updated_at and bump version on mutation."""
    entity["updated_at"] = clock.now()
    entity["version"] = entity.get("version", 1) + 1
