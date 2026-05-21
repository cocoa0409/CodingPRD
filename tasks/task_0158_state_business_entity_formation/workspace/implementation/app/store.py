"""In-memory data store for every benchmark entity."""
from __future__ import annotations

import threading
from typing import Any


class _Store:
    """Single mutable container for every collection plus a global lock."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.business_entities: dict[str, dict[str, Any]] = {}
        self.registered_agents: dict[str, dict[str, Any]] = {}
        self.operating_agreements: dict[str, dict[str, Any]] = {}
        self.ein_applications: dict[str, dict[str, Any]] = {}
        self.annual_reports: dict[str, dict[str, Any]] = {}
        self.tax_assessments: dict[str, dict[str, Any]] = {}
        self.foreign_qualifications: dict[str, dict[str, Any]] = {}
        self.boi_reports: dict[str, dict[str, Any]] = {}
        self.beneficial_owners: dict[str, dict[str, Any]] = {}
        self.boi_ownerships: dict[str, dict[str, Any]] = {}
        self.compliance_events: dict[str, dict[str, Any]] = {}

        # Monotonic counters
        self._ein_counter = 0
        # Sentinels / per-entity caches
        self.delinquent_since: dict[str, Any] = {}  # entity_id -> datetime when entity entered DELINQUENT
        self.ownership_change_at: dict[str, Any] = {}  # entity_id -> last ownership change timestamp triggering stale timer
        # Track which TaxOfficer X-User-IDs accepted which (entity_id, tax_year) annual reports
        # so the segregation rule on /pay can be enforced.
        self.tax_accept_actor: dict[tuple[str, int], set[str]] = {}

    def next_ein(self) -> str:
        with self.lock:
            self._ein_counter += 1
            n = self._ein_counter
            # Format XX-XXXXXXX. 9-digit space; we just zero-pad.
            digits = f"{n:09d}"
            return f"{digits[:2]}-{digits[2:]}"


store = _Store()
