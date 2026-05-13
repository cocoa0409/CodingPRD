"""In-memory data store for the cold-chain-logistics API."""

from __future__ import annotations

import uuid
from threading import RLock


class Store:
    """Generic keyed-by-id collection with helper indexes."""

    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.lock = RLock()

    def put(self, row: dict) -> dict:
        self.rows[row["id"]] = row
        return row

    def get(self, row_id):
        if row_id is None:
            return None
        return self.rows.get(row_id)

    def exists(self, row_id) -> bool:
        return row_id is not None and row_id in self.rows

    def all(self) -> list[dict]:
        return list(self.rows.values())


class DB:
    def __init__(self):
        self.vehicles = Store()
        self.drivers = Store()
        self.tasks = Store()
        self.stops = Store()  # TaskStop rows
        self.handovers = Store()
        self.readings = Store()
        self.alerts = Store()
        self.responses = Store()  # ResponseAction
        self.assessments = Store()
        self.decisions = Store()
        self.claims = Store()
        self.reports = Store()
        self.audit = Store()
        # Cross-cut: track which X-User-IDs have accepted each decision
        self.decision_acceptors: dict[str, set] = {}
        # Track vehicle_no, license_no uniqueness
        self.vehicle_no_index: dict[str, str] = {}
        self.license_no_index: dict[str, str] = {}
        # Idempotency map: (task_id, idempotency_key) -> reading_id
        self.reading_idempotency: dict[tuple, str] = {}
        # Global mutation lock for concurrency-sensitive transitions
        self.global_lock = RLock()

    def stops_for_task(self, task_id: str) -> list[dict]:
        return sorted(
            [s for s in self.stops.all() if s["task_id"] == task_id],
            key=lambda s: s["sequence"],
        )

    def alerts_for_task(self, task_id: str) -> list[dict]:
        return [a for a in self.alerts.all() if a["task_id"] == task_id]

    def readings_for_task(self, task_id: str) -> list[dict]:
        return [r for r in self.readings.all() if r["task_id"] == task_id]

    def handovers_for_task(self, task_id: str) -> list[dict]:
        return sorted(
            [h for h in self.handovers.all() if h["task_id"] == task_id],
            key=lambda h: h["handed_over_at"],
        )

    def handovers_for_stop(self, stop_id: str) -> list[dict]:
        return [h for h in self.handovers.all() if h["stop_id"] == stop_id]

    def responses_for_alert(self, alert_id: str) -> list[dict]:
        return [r for r in self.responses.all() if r["alert_id"] == alert_id]


db = DB()


def new_id() -> str:
    return str(uuid.uuid4())
