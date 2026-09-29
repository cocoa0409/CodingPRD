"""In-memory data store.  Every collection starts EMPTY on every boot -- no
seeding, no preloading, no persistence of any kind."""

import itertools
from datetime import datetime, timezone

# PRD 2.5: at startup the logical clock reads exactly this instant and never
# falls back to real wall-clock time.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.courses = {}
        self.turf_areas = {}
        self.plans = {}
        self.plan_tasks = {}
        self.applicators = {}
        self.products = {}
        self.applications = {}
        self.pump_stations = {}
        self.irrigation_runs = {}
        self.windows = {}
        self.play_events = {}
        self.equipment = {}
        self.readings = {}
        self.weather_events = {}
        self.clock = CLOCK_DEFAULT
        self._counter = itertools.count(1)

    def next_seq(self):
        return next(self._counter)


store = Store()


def clock():
    return store.clock


def set_clock(instant):
    store.clock = instant
