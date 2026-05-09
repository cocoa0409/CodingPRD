"""In-memory data store for the Flight Delay Claims API.

All entities live in dictionaries keyed by id. The store is single-process
and serialised by a global RLock (Flask before/teardown_request hooks).
"""

from __future__ import annotations

import datetime as dt
import threading
import uuid
from typing import Any


def gen_id() -> str:
    """Server-minted UUID without prefix."""
    return str(uuid.uuid4())


def now_iso_z() -> str:
    now = dt.datetime.now(dt.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class DB:
    def __init__(self):
        self.lock = threading.RLock()

        # Top-level collections, keyed by id.
        self.insurers: dict[str, dict] = {}
        self.policies: dict[str, dict] = {}
        self.tickets: dict[str, dict] = {}
        self.flights: dict[str, dict] = {}
        self.flight_status_events: dict[str, dict] = {}
        self.claims: dict[str, dict] = {}
        self.claim_segments: dict[str, dict] = {}
        self.payout_batches: dict[str, dict] = {}
        self.manual_review_cases: dict[str, dict] = {}
        self.reinsurance_allocations: dict[str, dict] = {}
        self.reserve_adjustments: dict[str, dict] = {}
        self.audit_logs: dict[str, dict] = {}
        self.outbox_events: dict[str, dict] = {}

    # ---------- helpers used by all routes ----------

    def stamp_create(self, obj: dict, *, with_version: bool = True):
        ts = now_iso_z()
        if "id" not in obj:
            obj["id"] = gen_id()
        obj["created_at"] = ts
        if with_version:
            obj["updated_at"] = ts
            obj["version"] = 1
        return obj

    def stamp_update(self, obj: dict):
        obj["updated_at"] = now_iso_z()
        obj["version"] = obj.get("version", 1) + 1


db = DB()
