"""In-memory data store.

All state is kept in plain Python dicts keyed by id. There is NO persistence:
no SQLite, no JSON dump, no /tmp cache. Every process boot starts empty; the test
harness re-launches start.sh before each test which wipes all state.

The store is deliberately NOT seeded — no entity is created at import/startup.
Tests build every precondition through the declared API surface.
"""
import uuid

from clock import clock


class Store:
    def __init__(self):
        # one dict per entity type, keyed by id
        self.monitoring_plans = {}
        self.subscribers = {}
        self.contracts = {}
        self.devices = {}
        self.emergency_contacts = {}
        self.alarm_events = {}
        self.dispatch_actions = {}
        self.device_tests = {}
        self.equipment_returns = {}
        self.agent_shifts = {}
        self.monitoring_holds = {}
        # monotonic sequence to provide a stable creation order tiebreaker
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """ISO 8601 UTC timestamp with three fractional digits (PRD 2.4)."""
    if dt is None:
        return None
    # dt is timezone-aware UTC
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
