"""In-memory data store and the logical duty clock (PRD 2.4, 2.5).

Storage is process-local Python dicts keyed by id.  Nothing is persisted and
nothing is ever seeded: the store comes up completely empty on every boot.
"""

import uuid
from datetime import datetime, timedelta, timezone

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


class Store(object):
    COLLECTIONS = (
        "stations",
        "apparatus",
        "firefighters",
        "hiring_rosters",
        "duty_shifts",
        "shift_assignments",
        "leave_requests",
        "trade_requests",
        "vacancies",
        "overtime_offers",
        "work_periods",
    )

    def __init__(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0
        self._dirty = {}
        self._clock = DEFAULT_CLOCK

    # ------------------------------------------------------------------ clock
    @property
    def clock(self):
        return self._clock

    def set_clock(self, dt):
        self._clock = dt.astimezone(timezone.utc)

    def now_iso(self):
        return iso(self._clock)

    def today(self):
        return self._clock.astimezone(timezone.utc).date()

    # ----------------------------------------------------------- persistence
    def next_seq(self):
        self._seq += 1
        return self._seq

    def new(self, fields):
        stamp = self.now_iso()
        entity = {"id": str(uuid.uuid4())}
        entity.update(fields)
        entity["created_at"] = stamp
        entity["updated_at"] = stamp
        entity["version"] = 1
        entity["_seq"] = self.next_seq()
        return entity

    # --------------------------------------------------- dirty / version bump
    def begin(self):
        self._dirty = {}

    def touch(self, entity):
        if entity is not None:
            self._dirty[id(entity)] = entity

    def untouch(self, entity):
        """Drop a pending version bump — used for freshly created records."""
        if entity is not None:
            self._dirty.pop(id(entity), None)

    def discard(self):
        self._dirty = {}

    def commit(self):
        if not self._dirty:
            return
        stamp = self.now_iso()
        for entity in self._dirty.values():
            entity["version"] = int(entity.get("version", 1)) + 1
            entity["updated_at"] = stamp
        self._dirty = {}


db = Store()


def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def order_key(entity):
    """Final tie-break: created_at ascending, then insertion order."""
    return (entity.get("created_at") or "", entity.get("_seq") or 0)


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)
