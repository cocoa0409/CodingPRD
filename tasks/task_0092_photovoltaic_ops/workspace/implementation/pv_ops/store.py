"""In-memory data store with a global lock and a simulated clock."""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional


def utc_now_iso(dt: Optional[datetime] = None) -> str:
    """Return an ISO-8601 UTC timestamp with three fractional digits."""
    moment = dt if dt is not None else datetime.now(tz=timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    else:
        moment = moment.astimezone(timezone.utc)
    millis = int(moment.microsecond / 1000)
    return moment.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def new_uuid() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    return "req_" + uuid.uuid4().hex[:20].upper()


class Clock:
    """Logical clock that can be advanced by tests via /_clock/advance.

    When no override is set, returns the real current UTC time.
    """

    def __init__(self) -> None:
        self._override: Optional[datetime] = None

    def now(self) -> datetime:
        if self._override is not None:
            return self._override
        return datetime.now(tz=timezone.utc)

    def now_iso(self) -> str:
        return utc_now_iso(self.now())

    def set(self, dt: datetime) -> None:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        self._override = dt


class Store:
    """A simple in-memory store with a re-entrant lock for serializing mutations."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.clock = Clock()

        # Each table is a dict id -> dict (or list of dicts for append-only logs).
        self.stations: Dict[str, dict] = {}
        self.arrays: Dict[str, dict] = {}
        self.strings: Dict[str, dict] = {}
        self.modules: Dict[str, dict] = {}
        self.inverters: Dict[str, dict] = {}
        self.transformers: Dict[str, dict] = {}
        self.suppliers: Dict[str, dict] = {}

        self.generation_readings: Dict[str, dict] = {}
        self.alarm_code_maps: Dict[str, dict] = {}
        self.alarm_events: Dict[str, dict] = {}

        self.patrol_plans: Dict[str, dict] = {}
        self.patrol_records: Dict[str, dict] = {}

        self.defects: Dict[str, dict] = {}
        self.work_orders: Dict[str, dict] = {}
        self.spare_parts: Dict[str, dict] = {}

        self.metering_records: Dict[str, dict] = {}
        self.settlement_periods: Dict[str, dict] = {}
        self.investor_shares: Dict[str, dict] = {}
        self.revenue_distributions: Dict[str, dict] = {}

        self.subsidy_policies: Dict[str, dict] = {}
        self.subsidy_declarations: Dict[str, dict] = {}

        self.audit_entries: Dict[str, dict] = {}

    # ---- generic helpers ----
    def insert_common(self, row: dict) -> dict:
        """Populate id/created_at/updated_at/version on a new common-fields row."""
        now = self.clock.now_iso()
        row.setdefault("id", new_uuid())
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        row.setdefault("version", 1)
        return row

    def insert_lite(self, row: dict) -> dict:
        """Insert an append-only row carrying only id/created_at."""
        now = self.clock.now_iso()
        row.setdefault("id", new_uuid())
        row.setdefault("created_at", now)
        return row

    def bump(self, row: dict) -> dict:
        """Mark a common-fields row as mutated (version + updated_at)."""
        row["updated_at"] = self.clock.now_iso()
        row["version"] = int(row.get("version", 0)) + 1
        return row


def paginate(rows: List[dict], limit: int, offset: int) -> tuple[List[dict], int, bool]:
    total = len(rows)
    window = rows[offset : offset + limit]
    has_more = (offset + len(window)) < total
    return window, total, has_more
