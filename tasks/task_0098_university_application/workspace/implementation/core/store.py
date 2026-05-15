"""In-memory data store keyed by entity type."""
from __future__ import annotations
import threading
from typing import Any

from core.clock import clock
from core.ids import new_uuid


class Store:
    def __init__(self) -> None:
        self.applicants: dict[str, dict] = {}
        self.universities: dict[str, dict] = {}
        self.programs: dict[str, dict] = {}
        self.applications: dict[str, dict] = {}
        self.essays: dict[str, dict] = {}
        self.recommendations: dict[str, dict] = {}
        self.aid_packages: dict[str, dict] = {}
        self.waitlist_entries: dict[str, dict] = {}
        self.yield_sweeps: dict[str, dict] = {}

        # University-scoped advisory locks for yield sweeps.
        self.university_sweep_locks: dict[str, threading.Lock] = {}
        # Global mutation lock (simple model — serialize mutations to avoid races).
        self.lock = threading.RLock()

    def get_sweep_lock(self, university_id: str) -> threading.Lock:
        if university_id not in self.university_sweep_locks:
            self.university_sweep_locks[university_id] = threading.Lock()
        return self.university_sweep_locks[university_id]

    # ---- Generic helpers ----
    def stamp_create(self, with_version: bool = True) -> dict:
        now = clock.iso()
        rec = {
            "id": new_uuid(),
            "created_at": now,
        }
        if with_version:
            rec["updated_at"] = now
            rec["version"] = 1
        return rec

    def bump(self, record: dict) -> None:
        if "version" in record:
            record["version"] = int(record["version"]) + 1
        if "updated_at" in record or "created_at" in record:
            record["updated_at"] = clock.iso()


store = Store()
