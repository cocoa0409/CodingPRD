"""In-memory data store.

The store starts completely empty on every boot. Nothing is seeded, preloaded or
hardcoded: every entity a client needs is built through the declared endpoints.
"""

import threading
import uuid
from datetime import datetime, timezone

# Default logical clock instant, per PRD section 2.4.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "foundries",
    "pump_models",
    "pattern_assets",
    "material_seal_configs",
    "duty_applications",
    "selections",
    "casting_lots",
    "casting_defects",
    "build_orders",
    "test_runs",
    "test_points",
    "pump_packages",
    "repair_kits",
    "kit_allocations",
    "warranty_claims",
)


class Store(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def seq_mark(self):
        """High-water creation sequence, used for clock-independent boundaries."""
        return self._seq


db = Store()


def now_utc():
    """The current instant is always the logical clock.

    PRD section 2.4: the server never falls back to real time, so audit stamps
    (`created_at`, `updated_at`, `api_request_timestamp`) are minted from the
    logical clock exactly like every date comparison.
    """
    return db.clock


def iso_millis(dt):
    """ISO 8601 UTC instant with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def iso_business(dt):
    """ISO 8601 UTC rendering for business instants supplied by the client.

    Fractional digits are emitted only when the instant actually carries them so
    that a value handed in as `2026-08-01T00:00:00Z` reads back identically.
    """
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def new_record(kind, versioned=True, **fields):
    created = now_utc()
    rec = {
        "_kind": kind,
        "_seq": db.next_seq(),
        "id": str(uuid.uuid4()),
        "_created_at": created,
    }
    if versioned:
        rec["_updated_at"] = created
        rec["version"] = 1
    rec.update(fields)
    return rec


def by_seq(records):
    """Default ordering: created_at ascending (insertion order)."""
    return sorted(records, key=lambda r: (r["_created_at"], r["_seq"]))
