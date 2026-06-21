"""In-memory data store. All state lives in process memory keyed by id.

The store starts EMPTY on every boot. No seeding, preloading, or hardcoding of
any entity. Tests build all state through the declared API surface.
"""
import threading
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        # One dict per entity type, keyed by id.
        self.personnel = {}
        self.suppliers = {}
        self.nonconformance_reports = {}
        self.capas = {}
        self.eightd_steps = {}
        self.scars = {}
        self.inspection_plans = {}
        self.inspection_lots = {}
        self.audits = {}
        self.audit_findings = {}
        self.deviations = {}
        self.control_plans = {}
        self.control_plan_revisions = {}

        # Logical server clock (PRD 3.10). Defaults to wall clock until set.
        self._clock = datetime.now(timezone.utc)
        self.lock = threading.RLock()

    # --- clock helpers ---
    def get_clock(self):
        return self._clock

    def set_clock(self, dt):
        self._clock = dt


def new_id():
    return str(uuid.uuid4())


def now_dt():
    return datetime.now(timezone.utc)


# Single global store instance. Recreated fresh on every process boot.
db = Store()
