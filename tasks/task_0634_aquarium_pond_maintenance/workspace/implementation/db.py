"""In-memory data store.

All entity data is held in plain Python dicts keyed by id. Storage is
in-memory only — no persistence. The store starts EMPTY on every boot;
nothing is seeded. Tests construct all entities via the declared API.
"""

import uuid
from datetime import datetime, timezone


# Logical clock starts at 2026-01-01T00:00:00Z (PRD §3.11). It never falls
# back to wall-clock time.
CLOCK_DEFAULT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        # one dict per entity type, keyed by id
        self.contracts = {}
        self.systems = {}
        self.livestock = {}
        self.equipment = {}
        self.technicians = {}
        self.visits = {}
        self.water_tests = {}
        self.invoices = {}
        self.installs = {}
        self.emergencies = {}
        self.repairs = {}
        self.quarantines = {}
        self.feeding_plans = {}

        # server logical clock
        self.current_utc = CLOCK_DEFAULT

    # --- id / timestamp helpers -------------------------------------------
    def new_id(self):
        # server-minted UUID with no type prefix (PRD §2.4)
        return str(uuid.uuid4())

    def now_iso(self):
        # creation/update timestamps are wall-clock ISO 8601 UTC, 3 frac digits
        now = datetime.now(timezone.utc)
        return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


# single global store instance, created fresh on every process boot
store = Store()
