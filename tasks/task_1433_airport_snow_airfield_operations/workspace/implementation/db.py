"""In-memory data store. Everything resets on process start."""

from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.snow_events = {}
        self.airfield_surfaces = {}
        self.condition_reports = {}
        self.friction_assessments = {}
        self.notams = {}
        self.chemical_products = {}
        self.chemical_applications = {}
        self.equipment_units = {}
        self.operator_shifts = {}
        # Logical clock — default 2026-08-01T00:00:00Z
        self.logical_clock = datetime(2026, 8, 1, tzinfo=timezone.utc)


db = Store()
