"""In-memory data store. Empty on every boot — no seeding."""
import threading


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.events = {}
        self.course_segments = {}
        self.role_catalog_entries = {}
        self.shifts = {}
        self.fundraising_groups = {}
        self.volunteers = {}
        self.training_records = {}
        self.signups = {}
        self.supply_inventories = {}
        self.distribution_records = {}
        self.hour_logs = {}
        self.debrief_reports = {}
        self.role_adjustments = {}
        # Logical clock: starts at 2026-08-01T00:00:00Z exactly, never wall clock.
        self.clock_now_iso = "2026-08-01T00:00:00Z"


store = Store()
