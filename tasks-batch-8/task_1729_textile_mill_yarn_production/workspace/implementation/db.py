"""In-memory data store for the Textile Mill API.

The store starts empty on every boot. No seeding is performed here or anywhere
else in the implementation; every entity a test needs is constructed via the
declared API surface.
"""

import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits, e.g. 2026-08-14T12:00:00.123Z."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        self.fiber_lots = {}
        self.blend_recipes = {}
        self.blend_components = {}
        self.spinning_machines = {}
        self.yarn_lots = {}
        self.machine_assignments = {}
        self.dye_lots = {}
        self.shade_bands = {}
        self.lab_dips = {}
        self.quality_tests = {}
        self.finished_rolls = {}
        self.customer_orders = {}


db = Store()
