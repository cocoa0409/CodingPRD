"""In-memory data store. Starts completely empty on every boot -- no seeding."""
import itertools
from datetime import datetime, timezone

CLOCK_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.stations = {}
        self.aircraft = {}
        self.dispatchers = {}
        self.captains = {}
        self.desks = {}
        self.desk_shifts = {}
        self.legs = {}
        self.plans = {}
        self.manifests = {}
        self.mel_items = {}
        self.weather_packages = {}
        self.releases = {}
        self.signatures = {}
        self.control_records = {}
        self.monitoring_events = {}
        self.clock = CLOCK_DEFAULT
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)

    def stamp_new(self, rec):
        rec['created_at'] = self.clock
        rec['updated_at'] = self.clock
        rec['version'] = 1
        rec['_seq'] = self.next_seq()
        return rec

    def touch(self, rec):
        rec['updated_at'] = self.clock
        rec['version'] = rec.get('version', 1) + 1
        return rec


store = Store()
