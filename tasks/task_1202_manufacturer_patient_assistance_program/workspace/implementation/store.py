"""In-memory data store. Empty at every boot."""

from datetime import datetime, timezone


class Store:
    def __init__(self):
        # entity maps keyed by id
        self.programs = {}
        self.budget_periods = {}
        self.patients = {}
        self.prescribers = {}
        self.screenings = {}
        self.documents = {}
        self.applications = {}
        self.enrollments = {}
        self.circumstances = {}
        self.appeals = {}
        self.copay_cards = {}
        self.inventory_lots = {}
        self.shipments = {}
        self.shipment_lines = {}
        self.dispense_events = {}
        self.reconciliation_runs = {}
        # idempotency registry: key -> {"body": <canonical>, "response": <obj>, "status": int}
        self.idempotency_keys = {}
        # logical clock; startup default 2026-05-01T00:00:00Z
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        # creation-order counters for deterministic ordering / FEFO tiebreaks
        self.seq = 0

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq


db = Store()
