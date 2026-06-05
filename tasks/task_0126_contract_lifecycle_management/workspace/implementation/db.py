"""In-memory data store.

Every collection is a plain dict keyed by the entity's UUID id. The store starts
EMPTY on every boot — nothing is seeded, preloaded, or hardcoded. Tests build all
state through the declared API surface.

A logical clock (PRD §2.10) is also held here; it is advanced explicitly by a
PlatformAdmin via POST /_clock/set_current_utc. Its initial value is simply the
real wall-clock time at boot (only relevant before the test sets it).
"""

import threading
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.organizations = {}
        self.clause_templates = {}
        self.contract_templates = {}
        self.contracts = {}
        self.contract_versions = {}
        self.approval_workflows = {}
        self.approval_steps = {}
        self.signature_requests = {}
        self.obligations = {}
        self.deviation_approvals = {}
        self.renewal_alerts = {}
        self.audit_events = {}
        # Logical clock, a timezone-aware datetime.
        self.clock = datetime.now(timezone.utc)

    def reset(self):
        self.__init__()


db = Store()


def new_id():
    return str(uuid.uuid4())
