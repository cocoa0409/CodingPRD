"""In-memory data store.

Every collection is a plain dict keyed by the resource's UUID string. The store
starts EMPTY on every process boot — there is no seeding, preloading, or
hardcoded data anywhere. The test harness restarts the server before each test
(per-test-server isolation), so a fresh module import gives a clean slate.

The only non-empty initial state is the SystemClock singleton, whose current_utc
defaults to the real wall clock until a test sets it via /_clock/set_current_utc
(PRD §2.6). That is server-managed configuration, not domain entity data.
"""

import uuid

from timeutil import now_utc


class Store:
    def __init__(self):
        # One dict per entity collection, keyed by id.
        self.controllers = {}
        self.data_subjects = {}
        self.processors = {}
        self.consent_records = {}
        self.legal_holds = {}
        self.dsar_requests = {}
        self.discovery_findings = {}
        self.exemption_claims = {}
        self.fulfillment_items = {}
        self.processor_notifications = {}
        self.audit_events = {}

        # Monotonic sequence so created_at-tied ordering is stable even when two
        # rows share a millisecond timestamp (PRD §2.3 lists by created_at asc).
        self._seq = 0

        # SystemClock singleton: server's notion of "now". Defaults to wall clock.
        self.clock_current_utc = now_utc()
        self.clock_explicitly_set = False

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        """The server's current notion of 'now' (the SystemClock)."""
        if self.clock_explicitly_set:
            return self.clock_current_utc
        return now_utc()


# Module-level singleton. Re-imported fresh on every process boot.
store = Store()
