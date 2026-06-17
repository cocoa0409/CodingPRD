"""In-memory data store. Wiped on every process start — no seeding, no persistence.

All collections are plain dicts keyed by entity id. The logical test-driving
clock (PRD §3.5, §4 /_clock/set_current_utc) is held here too. Nothing is
pre-populated; tests build every entity via the API surface.
"""
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.employees = {}
        self.grades = {}
        self.cost_centers = {}
        self.positions = {}
        self.incumbents = {}
        self.freeze_orders = {}
        self.requisitions = {}
        self.reclass_requests = {}
        self.forecast_periods = {}
        self.budget_adjustments = {}
        # Logical test-driving clock (PRD §3.5). Defaults to real now until set
        # via POST /_clock/set_current_utc; drives FreezeOrder window posture.
        self.current_utc = datetime.now(timezone.utc)
        # Monotonic insertion sequence so created_at-ascending ordering is stable
        # even when two records share an identical millisecond timestamp.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


# Single global store instance, fresh per process boot.
db = Store()
