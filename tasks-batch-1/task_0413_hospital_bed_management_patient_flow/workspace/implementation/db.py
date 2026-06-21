"""In-memory data store + simulated clock for the Hospital Bed Flow API.

Everything lives in process memory and starts empty on every boot. No seeding.
"""

import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        # One dict per entity, keyed by id.
        self.units = {}
        self.beds = {}
        self.encounters = {}
        self.bed_requests = {}
        self.evs_tasks = {}
        self.discharge_barriers = {}
        self.surge_events = {}
        self.capacity_huddles = {}
        self.adt_events = {}

        # Global counters / simulated clock.
        self.ops_run_index = 0
        # Simulated UTC clock. Defaults to real "now" at boot; FlowAdmin may set it.
        self._clock = datetime.now(timezone.utc)

    # ----- id + time helpers -----
    @staticmethod
    def new_id():
        return str(uuid.uuid4())

    def clock_now(self):
        return self._clock

    def set_clock(self, dt):
        self._clock = dt


# A single module-level store instance. start.sh re-invocation wipes it.
store = Store()


def iso(dt):
    """Render a datetime as ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
