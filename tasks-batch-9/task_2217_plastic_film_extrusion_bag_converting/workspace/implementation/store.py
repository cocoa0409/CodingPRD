"""In-memory data store.

Everything lives in plain dicts keyed by id.  The store is EMPTY on every boot —
no entity is ever seeded, preloaded or hardcoded; clients build all state through
the declared endpoints.
"""

import itertools
import threading
import uuid
from datetime import datetime, timedelta, timezone

DEFAULT_LOGICAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "products",
    "resin_grades",
    "blend_recipes",
    "extrusion_lines",
    "extrusion_runs",
    "film_rolls",
    "regrind_pools",
    "regrind_transactions",
    "print_presses",
    "plate_sets",
    "print_jobs",
    "bag_lots",
    "compliance_dossiers",
)


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


class Store:
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_LOGICAL_CLOCK
        self.lock = threading.RLock()
        self._seq = itertools.count(1)
        self._last_wall = None

    # -- identity / timestamps -------------------------------------------
    def next_seq(self):
        return next(self._seq)

    def wall_now(self):
        """Strictly increasing (at millisecond resolution) wall-clock instant.

        created_at / updated_at read real time; the logical clock is reserved for
        window gates and the recorded_at / issued_at / revoked_at stamps.
        """
        raw = datetime.now(timezone.utc)
        now = raw.replace(microsecond=(raw.microsecond // 1000) * 1000)
        if self._last_wall is not None and now <= self._last_wall:
            now = self._last_wall + timedelta(milliseconds=1)
        self._last_wall = now
        return now

    def wall_iso(self):
        return fmt_ts(self.wall_now())

    def clock_iso(self):
        return fmt_ts(self.clock)

    # -- entity lifecycle -------------------------------------------------
    def new_common(self, ledger_row=False):
        ts = self.wall_iso()
        if ledger_row:
            return {"id": str(uuid.uuid4()), "created_at": ts, "_seq": self.next_seq()}
        return {
            "id": str(uuid.uuid4()),
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "_seq": self.next_seq(),
        }

    def touch(self, entity):
        """Record a mutation: refresh updated_at and bump version (PRD §2.4)."""
        if entity is None or "version" not in entity:
            return entity
        entity["updated_at"] = self.wall_iso()
        entity["version"] = entity["version"] + 1
        return entity

    def sorted_values(self, collection):
        return sorted(collection.values(), key=lambda e: (e["created_at"], e["_seq"]))


store = Store()


def serialize(entity):
    if entity is None:
        return None
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def serialize_all(entities):
    return [serialize(e) for e in entities]
