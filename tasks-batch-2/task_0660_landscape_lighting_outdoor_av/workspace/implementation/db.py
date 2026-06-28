"""In-memory data store.

All state lives in process-local dicts keyed by id. The store starts EMPTY on
every boot — no seeding, no preload, no hardcoded entities. Tests build every
entity via the declared API surface.
"""

import itertools
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        # One dict per entity collection, keyed by id.
        self.customers = {}
        self.projects = {}
        self.transformers = {}
        self.zones = {}
        self.fixtures = {}
        self.quotes = {}
        self.quote_lines = {}
        self.install_jobs = {}
        self.schedule_programs = {}
        self.service_plans = {}
        self.service_visits = {}
        self.crew_routes = {}
        self.warranty_claims = {}
        self.add_ons = {}
        # Monotonic sequence: stable creation-order tiebreaker for created_at
        # sorting (pagination sorts by created_at ASC, ties by _seq).
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def iso_now():
    """Wall-clock-based ISO 8601 UTC timestamp with three fractional digits for
    created_at / updated_at audit fields (PRD 2.4)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
