"""In-memory data store. Starts empty on every process boot."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone


def gen_id() -> str:
    return uuid.uuid4().hex


def now_iso(clock_dt: datetime | None = None) -> str:
    dt = clock_dt if clock_dt is not None else datetime.now(timezone.utc)
    # ISO 8601 UTC with three fractional digits
    s = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return s


def parse_iso(s: str) -> datetime:
    """Parse ISO 8601 timestamp; accept trailing Z."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class DB:
    def __init__(self):
        # Logical clock — default per PRD §2.13
        self.clock = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
        # Monotonic insertion counter for deterministic pagination tiebreak
        # when multiple entities are stamped at the same logical-clock instant.
        # PRD §2.3 requires ordering by created_at ASC; when created_at ties
        # (identical logical-clock stamp), fall back to insertion order.
        self._seq = 0

        # Primary tables
        self.skus: dict[str, dict] = {}
        self.bundles: dict[str, dict] = {}
        self.bundle_lines: dict[str, dict] = {}
        self.orders: dict[str, dict] = {}
        self.order_lines: dict[str, dict] = {}
        self.helium_orders: dict[str, dict] = {}
        self.helium_tanks: dict[str, dict] = {}
        self.delivery_slots: dict[str, dict] = {}
        self.rental_contracts: dict[str, dict] = {}
        self.custom_print_orders: dict[str, dict] = {}
        self.event_packages: dict[str, dict] = {}
        self.event_bookings: dict[str, dict] = {}
        self.customers: dict[str, dict] = {}

        # Track PICKED_UP transition timestamps per order (for 14-day return window)
        self.order_picked_up_at: dict[str, datetime] = {}


db = DB()


def reset_for_tests():
    """Not called by API — safety helper only."""
    global db
    db = DB()


def now_clock() -> datetime:
    return db.clock


def stamp_common(entity: dict) -> None:
    """Populate id/created_at/updated_at/version on first write."""
    ts = now_iso(db.clock)
    if "id" not in entity:
        entity["id"] = gen_id()
    if "created_at" not in entity:
        entity["created_at"] = ts
    entity["updated_at"] = ts
    if "version" not in entity:
        entity["version"] = 1
    # Insertion-order tiebreak for created_at ties (see DB._seq).
    if "_seq" not in entity:
        db._seq += 1
        entity["_seq"] = db._seq


def bump(entity: dict) -> None:
    """Increment version and refresh updated_at."""
    entity["updated_at"] = now_iso(db.clock)
    entity["version"] = int(entity.get("version", 1)) + 1
