"""In-memory data store and time/id helpers.

The store starts empty on every process boot. Nothing is seeded, preloaded, or
hardcoded here — every entity is created by clients through the declared API.
Because the test harness re-launches the server before each test, holding all
state in this module-level object guarantees a clean slate per boot.
"""

import itertools
import uuid
from datetime import datetime, timezone

_seq = itertools.count(1)


def new_id():
    """Bare UUID (no type prefix), per PRD 2.4."""
    return str(uuid.uuid4())


def next_seq():
    """Monotonic creation-order counter used for stable created_at ascending sort."""
    return next(_seq)


def iso_millis(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + '%03dZ' % (dt.microsecond // 1000)


def now_iso():
    """Wall-clock timestamp for created_at/updated_at/api_request_timestamp."""
    return iso_millis(datetime.now(timezone.utc))


class Store:
    def __init__(self):
        # Each collection is a dict keyed by the server-minted entity id.
        self.customers = {}
        self.products = {}
        self.crews = {}
        self.projects = {}
        self.design_revisions = {}
        self.site_measurements = {}
        self.line_items = {}
        self.permits = {}
        self.hoa_submissions = {}
        self.change_orders = {}
        self.material_orders = {}
        self.work_phases = {}
        self.draws = {}
        self.warranty_claims = {}
        # Logical clock (PRD 2.9). Startup default; never falls back to wall time.
        self.clock_dt = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.clock_raw = '2026-05-01T00:00:00Z'


db = Store()
