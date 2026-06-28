"""In-memory data store.

All entities live in plain dicts keyed by their server-minted UUID. The store
is constructed fresh on every process boot — there is NO seeding, preloading,
or hardcoding of any entity. Every entity a test needs is created via the API.
"""
import itertools
import uuid


class Store:
    def __init__(self):
        self.studios = {}
        self.service_types = {}
        self.membership_plans = {}
        self.lash_techs = {}
        self.members = {}
        self.memberships = {}
        self.consent_patch_tests = {}
        self.appointments = {}
        self.retail_orders = {}
        self.recurring_schedules = {}
        self.sanitation_logs = {}
        self.credit_ledger_entries = {}
        # Monotonic sequence to order creations deterministically (tie-breaks /
        # created_at ASC list sort) independent of timestamp collisions.
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)

    @staticmethod
    def new_id():
        # Server-minted UUID, no prefix; identity only.
        return str(uuid.uuid4())


# Process-global store. Recreated on every process boot (fresh state).
store = Store()
