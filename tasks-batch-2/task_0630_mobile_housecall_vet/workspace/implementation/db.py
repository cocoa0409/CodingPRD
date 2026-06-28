"""In-memory data store.

Every collection is a plain dict keyed by entity id. The store starts EMPTY on
every boot — nothing is seeded. Per-test-server isolation wipes all state on
every restart.
"""
import itertools
import uuid

import clock

# One dict per entity type, keyed by id.
service_areas = {}
clinicians = {}
rolling_clinics = {}
patients = {}
appointments = {}
route_days = {}
route_stops = {}
estimates = {}
payments = {}
controlled_med_logs = {}
specimen_pickups = {}
wellness_plans = {}
referrals = {}

# Monotonic sequence so created_at ties are deterministic / insertion-ordered.
_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def seq():
    """Monotonic insertion sequence number, used as a stable tie-break."""
    return next(_seq)


def now_iso():
    """Logical-clock instant formatted as ISO 8601 UTC with 3 fractional digits."""
    from response import iso_ts

    return iso_ts(clock.now())
