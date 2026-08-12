"""In-memory data store. The store starts empty on every boot — no seeding."""
import threading


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.customers = {}
        self.staff = {}
        self.bays = {}
        self.lesson_packages = {}
        self.fitting_sessions = {}
        self.component_items = {}
        self.build_specs = {}
        self.component_orders = {}
        self.repair_tickets = {}
        self.trade_in_appraisals = {}
        self.used_club_listings = {}
        self.warranty_claims = {}
        self.credit_ledger_entries = []  # append-only list preserving insertion order

        # Logical clock: startup default is exactly 2026-05-01T00:00:00Z
        # Stored as a datetime (UTC).
        from datetime import datetime, timezone
        self.logical_now = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


db = Store()
