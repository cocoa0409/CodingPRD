"""In-memory data store and logical clock.

The store starts empty on every boot. No entity is ever seeded, preloaded,
or hardcoded; all data is created via API calls. A fresh process yields a
pristine server (the test harness re-launches start.sh before every test).
"""

import itertools
from datetime import datetime, timezone

# PRD section 2.5: the logical clock initializes to exactly
# 2026-08-01T00:00:00Z and never falls back to wall-clock time.
INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.customers = {}
        self.jobs = {}
        self.panels = {}
        self.components = {}
        self.panel_components = {}
        self.substitution_requests = {}
        self.test_points = {}
        self.test_sessions = {}
        self.program_versions = {}
        self.startup_sessions = {}
        self.change_orders = {}
        self.warranty_claims = {}
        self.as_built_packages = {}
        # Logical clock (PRD 2.5). Advanced only via POST /_clock/set_current_utc.
        self.clock = INITIAL_CLOCK
        # Insertion counter, used as a stable tiebreak for created_at sorting.
        self.seq = itertools.count(1)


db = Store()
