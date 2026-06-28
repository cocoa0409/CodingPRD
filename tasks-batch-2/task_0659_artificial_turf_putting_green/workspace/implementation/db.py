"""In-memory data store.

All state lives in process-local dicts keyed by id. The store starts EMPTY on
every boot — no seeding, no preload, no hardcoded entities. Tests build every
entity via the declared API surface.
"""

import itertools
import uuid
from datetime import timezone


class Store:
    def __init__(self):
        # One dict per entity collection, keyed by id.
        self.projects = {}
        self.customers = {}
        self.site_measures = {}
        self.turf_products = {}
        self.infill_products = {}
        self.design_layouts = {}
        self.base_prep_scopes = {}
        self.quotes = {}
        self.crews = {}
        self.install_jobs = {}
        self.warranty_plans = {}
        self.callbacks = {}
        self.payments = {}
        # Monotonic sequence: stable creation-order tiebreaker for created_at
        # sorting (pagination) and for the project ledger's chronological replay
        # (PRD 3.7: ties broken by an internal monotonically increasing sequence
        # captured at create time, NOT by id).
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def iso_now():
    """Wall-clock-based ISO 8601 UTC timestamp with three fractional digits for
    created_at / updated_at audit fields (PRD 2.4)."""
    from datetime import datetime

    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
