"""In-memory data store and logical clock.

The store starts completely empty on every boot. All entities are built by the
test suite through the declared API surface.
"""
from __future__ import annotations

import re
import threading
import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def _parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 timestamp string (accepts trailing Z)."""
    if s is None:
        raise ValueError("timestamp is None")
    txt = str(s).strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_ts(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


class LogicalClock:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._now = _parse_iso(_DEFAULT_CLOCK)

    def now(self) -> datetime:
        with self._lock:
            return self._now

    def now_str(self) -> str:
        return fmt_ts(self.now())

    def set(self, iso: str) -> datetime:
        dt = _parse_iso(iso)
        with self._lock:
            self._now = dt
        return dt


CLOCK = LogicalClock()


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    return "req_" + uuid.uuid4().hex[:20]


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class Store:
    """Simple in-memory store. Every dict maps id -> entity dict."""

    def __init__(self) -> None:
        self.customers: dict[str, dict] = {}
        self.assets: dict[str, dict] = {}
        self.repair_orders: dict[str, dict] = {}
        self.inspection_reports: dict[str, dict] = {}
        self.quotes: dict[str, dict] = {}
        self.parts: dict[str, dict] = {}
        self.pool_units: dict[str, dict] = {}
        self.test_runs: dict[str, dict] = {}
        self.certifications: dict[str, dict] = {}
        self.capacity_windows: dict[str, dict] = {}
        self.cert_tag_seq = 0
        self.lock = threading.RLock()


DB = Store()


def stamp_new(entity: dict) -> dict:
    """Attach the common system fields to a freshly built entity."""
    now = CLOCK.now_str()
    entity["id"] = new_id()
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    return entity


def touch(entity: dict) -> None:
    """Refresh updated_at and increment version for a mutation."""
    entity["updated_at"] = CLOCK.now_str()
    entity["version"] = int(entity.get("version", 1)) + 1
