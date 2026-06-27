"""In-memory data store and common-field management (PRD §2.4).

The store starts EMPTY on every boot. Nothing is seeded, preloaded, or
hardcoded; tests build every entity through the declared API surface.

Common fields (agencies, stations, units, premise alerts, incidents,
assignments, dispositions): id (UUID, no prefix), created_at, updated_at,
version (int starting at 1, +1 per mutation). CfsReport is append-only and
carries only id + created_at.
"""
import uuid
from datetime import timezone

from clock import clock


def iso_ts(dt):
    """ISO 8601 UTC timestamp with exactly three fractional digits (PRD §2.4)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        self.agencies = {}
        self.stations = {}
        self.units = {}
        self.premise_alerts = {}
        self.incidents = {}
        self.assignments = {}
        self.dispositions = {}
        self.reports = {}
        # monotonic CFS sequence; format CFS-YYYY-NNNNNN
        self._cfs_seq = 0

    def new_id(self):
        return str(uuid.uuid4())

    def next_cfs_number(self, year):
        self._cfs_seq += 1
        return f"CFS-{year}-{self._cfs_seq:06d}"


db = Store()


def stamp_create(entity, with_version=True):
    """Populate common system fields at creation time.

    created_at/updated_at are *audit* recording timestamps; per PRD §2.4 they
    read the logical clock (the platform never falls back to wall-clock time).
    """
    now = iso_ts(clock.now())
    entity.setdefault("id", db.new_id())
    entity["created_at"] = now
    if with_version:
        entity["updated_at"] = now
        entity["version"] = 1
    return entity


def touch(entity, bump_version=True):
    """Record a mutation: refresh updated_at and (optionally) bump version."""
    entity["updated_at"] = iso_ts(clock.now())
    if bump_version:
        entity["version"] = entity.get("version", 1) + 1
    return entity
