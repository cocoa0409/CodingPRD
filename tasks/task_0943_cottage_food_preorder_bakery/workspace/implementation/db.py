"""In-memory store, id minting and the logical clock.

G4: plain Python dicts only.  No sqlite, no file writes, no pickle, no /tmp.
The store is EMPTY on every boot -- nothing is seeded, preloaded or hardcoded.

G5: ids are valid UUID-4 strings whose leading 48 bits are a monotonic
counter, so lexicographic id order == creation order.  PRD ordering rules that
tie-break on `id` are therefore deterministic even though the logical clock is
coarse (many entities share one `created_at`).
"""

import random
import threading
import uuid

import config
from tsutil import ts_canonical, ts_input


class _Ids:
    """48-bit monotonic counter in the high bits of a version-4 UUID."""

    def __init__(self):
        self._n = 0
        self._lock = threading.Lock()
        self._rand = random.Random(0x9A43BEEF)

    def reset(self):
        with self._lock:
            self._n = 0
            self._rand = random.Random(0x9A43BEEF)

    def new(self):
        with self._lock:
            self._n += 1
            n = self._n & ((1 << 48) - 1)
            low = self._rand.getrandbits(80)
        # version/variant bits live in the low 80 bits, so forcing them cannot
        # disturb the counter that occupies the high 48.
        return str(uuid.UUID(int=((n << 80) | low), version=4))

    def request_id(self):
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        with self._lock:
            body = "".join(self._rand.choice(alphabet) for _ in range(20))
        return "req_" + body


IDS = _Ids()

COLLECTIONS = (
    "bakers",
    "customers",
    "recipes",
    "recipe_components",
    "ingredient_lots",
    "menu_items",
    "offer_windows",
    "orders",
    "order_lines",
    "batches",
    "labels",
    "subscriptions",
    "subscription_cycles",
    "payments",
    "money_movements",
    "delivery_routes",
    "reviews",
)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        # The logical clock.  Case B: it carries the caller's own string, and
        # before any client sets it, exactly CLOCK_DEFAULT_UTC.
        self.clock = ts_input(config.CLOCK_DEFAULT_UTC)
        IDS.reset()

    # -- clock ------------------------------------------------------------
    def now(self):
        return self.clock

    def now_dt(self):
        return self.clock.dt

    # -- generic access ---------------------------------------------------
    def coll(self, name):
        return getattr(self, name)

    def get(self, name, ident):
        if not isinstance(ident, str) or not ident:
            return None
        return getattr(self, name).get(ident)

    def values(self, name):
        """All records of a collection in ascending (created_at, id) order."""
        return sorted(
            getattr(self, name).values(),
            key=lambda r: (r["created_at"].dt, r["id"]),
        )


DB = Store()


def new_id():
    return IDS.new()


def base_record(now):
    """The three common fields every entity except MoneyMovement carries.

    `created_at` / `updated_at` are case A instants: PRD 2.4 mandates "ISO 8601
    UTC with three fractional digits" for them specifically, so they render
    canonically rather than echoing the logical clock's own string."""
    stamp = ts_canonical(now.dt)
    return {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
    }


def touch(record, now):
    """Bump `version` by exactly one and refresh `updated_at`."""
    record["version"] = record.get("version", 1) + 1
    record["updated_at"] = ts_canonical(now.dt)
    return record
