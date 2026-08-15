"""In-memory data store and logical clock. The store starts EMPTY on every boot."""

from __future__ import annotations

import threading
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_START_ISO = "2026-08-01T00:00:00Z"


def _parse_iso(s: str) -> datetime:
    """Parse ISO 8601 like 2026-08-01T00:00:00Z or with fractional seconds/offset."""
    if s is None:
        raise ValueError("None iso")
    if isinstance(s, datetime):
        return s
    s2 = s.strip()
    if s2.endswith("Z"):
        s2 = s2[:-1] + "+00:00"
    dt = datetime.fromisoformat(s2)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_utc(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with three fractional digits, ending in Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


class Clock:
    def __init__(self) -> None:
        self._now = _parse_iso(_START_ISO)
        self._lock = threading.Lock()

    def now(self) -> datetime:
        with self._lock:
            return self._now

    def set(self, dt: datetime) -> datetime:
        with self._lock:
            self._now = dt
            return self._now


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class Store:
    def __init__(self) -> None:
        self.sites = {}              # id -> GeneratorSite dict
        self.streams = {}            # id -> WasteStream
        self.areas = {}              # id -> AccumulationArea
        self.containers = {}         # id -> Container
        self.inspections = {}        # id -> ContainerInspection
        self.partners = {}           # id -> WastePartner
        self.audits = {}             # id -> ComplianceAudit
        self.manifests = {}          # id -> Manifest
        self.ldr_notifications = {}  # id -> LDRNotification
        self.reports = {}            # id -> BiennialReport


store = Store()
clock = Clock()
