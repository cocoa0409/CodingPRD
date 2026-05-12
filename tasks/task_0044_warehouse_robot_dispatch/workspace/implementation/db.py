"""In-memory data store."""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone, timedelta

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


def parse_iso(ts: str) -> datetime:
    """Parse ISO 8601 timestamp ending in Z."""
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def fmt_iso(dt: datetime) -> str:
    """Format datetime to ISO 8601 UTC with millisecond precision."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def clock_at(seconds_from_epoch: int) -> datetime:
    return EPOCH + timedelta(seconds=seconds_from_epoch)


def to_unix(dt: datetime) -> int:
    return int((dt - EPOCH).total_seconds())


class Database:
    def __init__(self):
        self.lock = threading.RLock()
        self.fleets: dict[str, dict] = {}
        self.map_nodes: dict[str, dict] = {}
        self.map_edges: dict[str, dict] = {}
        self.charging_stations: dict[str, dict] = {}
        self.robots: dict[str, dict] = {}
        self.tasks: dict[str, dict] = {}
        self.slot_reservations: dict[str, dict] = {}
        self.charging_sessions: dict[str, dict] = {}
        self.fault_incidents: dict[str, dict] = {}
        self.trajectory_records: dict[str, dict] = {}
        self.audit_events: dict[str, dict] = {}
        # Track when robots last transitioned into WAITING_RIGHT_OF_WAY for deadlock detection.
        self.robot_wait_transition_at: dict[str, datetime] = {}
        # Audit-event insertion order (id-list keyed by fleet_id)
        # Charging sessions need to be retained until cancelled by the fleet's clock advances
        # No special index — we filter when needed.


db = Database()
