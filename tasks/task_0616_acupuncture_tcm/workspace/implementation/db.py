"""In-memory data store.

All state lives in process-local dicts keyed by id. The store starts EMPTY on
every boot — no seeding, no preload, no hardcoded entities. Tests build every
entity via the declared API surface.
"""

import itertools
import uuid
from datetime import timezone

from clock import clock


class Store:
    def __init__(self):
        # One dict per entity collection, keyed by id.
        self.patients = {}
        self.intakes = {}
        self.treatment_plans = {}
        self.package_series = {}
        self.practitioners = {}
        self.rooms = {}
        self.appointments = {}
        self.addons = {}
        self.herbal_formulas = {}
        self.herb_items = {}
        self.dispenses = {}
        self.charges = {}
        self.superbills = {}
        # Monotonic sequence to provide a stable creation order tiebreaker for
        # sorting by created_at when multiple entities share the same logical
        # timestamp (created_at is wall-clock based and may collide).
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
