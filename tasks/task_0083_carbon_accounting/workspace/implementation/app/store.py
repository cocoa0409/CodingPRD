"""In-memory data store with UUID/timestamp helpers and a global lock."""
from __future__ import annotations

import threading
import uuid
from datetime import datetime
from typing import Dict, List

from .clock import clock


def new_id() -> str:
    return str(uuid.uuid4())


def fmt_ts(dt: datetime) -> str:
    """ISO 8601 UTC, millisecond precision, Z suffix."""
    ms = f"{dt.microsecond // 1000:03d}"
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ms + "Z"


def now_ts() -> str:
    return fmt_ts(clock.now())


class Store:
    """Top-level in-memory store with one dict per entity kind."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.organizations: Dict[str, dict] = {}
        self.facilities: Dict[str, dict] = {}
        self.boundary_changes: Dict[str, dict] = {}
        self.reporting_periods: Dict[str, dict] = {}
        self.emission_sources: Dict[str, dict] = {}
        self.emission_factors: Dict[str, dict] = {}
        self.activity_data: Dict[str, dict] = {}
        self.emission_records: Dict[str, dict] = {}
        self.reduction_projects: Dict[str, dict] = {}
        self.carbon_credits: Dict[str, dict] = {}
        self.reports: Dict[str, dict] = {}
        self.audit_logs: List[dict] = []
        # Global serial-number registry for credits (across all orgs)
        self.credit_serials: Dict[str, str] = {}  # serial_number -> credit_id

    def stamp_create(self, payload: dict) -> dict:
        ts = now_ts()
        payload.setdefault("id", new_id())
        payload["created_at"] = ts
        payload["updated_at"] = ts
        payload["version"] = 1
        return payload

    def stamp_update(self, payload: dict) -> dict:
        payload["updated_at"] = now_ts()
        payload["version"] = payload.get("version", 0) + 1
        return payload

    def stamp_event(self, payload: dict) -> dict:
        """For write-once event records: only id + created_at."""
        payload.setdefault("id", new_id())
        payload["created_at"] = now_ts()
        return payload

    def append_audit(
        self,
        organization_id: str,
        actor_user_id: str,
        actor_role: str,
        event_type: str,
        target_entity: str,
        target_id: str,
        payload_json: dict | None = None,
    ) -> dict:
        row = {
            "organization_id": organization_id,
            "actor_user_id": actor_user_id,
            "actor_role": actor_role,
            "event_type": event_type,
            "target_entity": target_entity,
            "target_id": target_id,
            "payload_json": payload_json or {},
        }
        self.stamp_event(row)
        self.audit_logs.append(row)
        return row


# Singleton store
store = Store()
