"""In-memory data store."""

import uuid
from threading import RLock


def new_id() -> str:
    return str(uuid.uuid4())


class DB:
    def __init__(self):
        self.lock = RLock()
        self.distributors = {}
        self.films = {}
        self.cinemas = {}
        self.screens = {}
        self.showtimes = {}
        self.tickets = {}
        self.settlements = {}
        self.schedule_adjustments = {}
        self.anomaly_alerts = {}
        self.external_events = {}
        self.audit_logs = {}

    def reset(self):
        with self.lock:
            self.distributors.clear()
            self.films.clear()
            self.cinemas.clear()
            self.screens.clear()
            self.showtimes.clear()
            self.tickets.clear()
            self.settlements.clear()
            self.schedule_adjustments.clear()
            self.anomaly_alerts.clear()
            self.external_events.clear()
            self.audit_logs.clear()


db = DB()
