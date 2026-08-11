"""In-memory data store. Fresh per process; no seeding of any entity data."""
import threading
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.customers = {}
        self.venues = {}
        self.animals = {}
        self.health_records = {}
        self.handlers = {}
        self.bookings = {}
        self.booking_animals = {}
        self.staff_assignments = {}
        self.addon_requests = {}
        self.permits = {}
        self.waivers = {}
        self.insurance_certificates = {}
        self.weather_assessments = {}
        self.ledger_entries = {}
        # Logical clock: startup default is exactly 2026-05-01T00:00:00Z.
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.lock = threading.RLock()


store = Store()
