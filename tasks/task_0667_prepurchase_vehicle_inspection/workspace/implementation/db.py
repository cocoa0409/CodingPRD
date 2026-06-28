"""In-memory data store.

Every collection starts EMPTY on each process boot. No seeding, no preload.
Tests build all required state through the declared API surface.

Common fields (PRD §2.4):
  - id: server-minted UUID, no type prefix
  - created_at: ISO8601 UTC ms, fixed at creation
  - updated_at: ISO8601 UTC ms, refreshed on every mutation
  - version: integer starting at 1, +1 each mutation
These four are present on: Account, FeeSchedule, Inspector, InspectionOrder,
DispatchAssignment, InspectionReport, VinReport, RecallRecord, Dispute.

Lightweight immutable records carry only id + created_at (no updated_at/version):
  Vehicle, ReportPhoto, VinHistoryRecord.
"""
import uuid

from clock import clock as _logical_clock  # noqa: F401 (kept for clarity)


def new_id():
    return str(uuid.uuid4())


def _iso_now_wall():
    # created_at/updated_at use real ISO8601 UTC ms timestamps (PRD §2.4 ties
    # these to creation/mutation moments, distinct from the logical clock that
    # governs SLA/late/daily-cap business behavior).
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        self.accounts = {}
        self.vehicles = {}
        self.fee_schedules = {}
        self.inspectors = {}
        self.orders = {}
        self.assignments = {}
        self.reports = {}
        self.photos = {}
        self.vin_history_records = {}
        self.vin_reports = {}
        self.recall_records = {}
        self.disputes = {}
        # monotonic sequence to break created_at ties deterministically
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def stamp_create(entity, full=True):
    """Attach common system fields at creation.

    full=True  -> id, created_at, updated_at, version (mutable resources)
    full=False -> id, created_at only (immutable lightweight records)
    """
    entity["id"] = new_id()
    entity["created_at"] = _iso_now_wall()
    entity["_seq"] = db.next_seq()
    if full:
        entity["updated_at"] = entity["created_at"]
        entity["version"] = 1
    return entity


def touch(entity):
    """Refresh updated_at and bump version on a mutable resource."""
    entity["updated_at"] = _iso_now_wall()
    entity["version"] = entity.get("version", 1) + 1
    return entity
