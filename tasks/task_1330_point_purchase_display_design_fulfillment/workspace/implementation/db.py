"""In-memory data store. Empty at every boot — no seeding."""

import uuid
from datetime import datetime, timezone


# Logical clock — starts exactly at 2026-08-01T00:00:00Z, never wall-clock.
_logical_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def get_clock():
    return _logical_clock


def set_clock(dt):
    global _logical_clock
    _logical_clock = dt


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Current logical timestamp, ISO 8601 UTC with three fractional digits."""
    dt = get_clock()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def iso_utc(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# Entity stores — keyed by id
clients = {}
programs = {}
compliance_rules = {}
designs = {}
production_runs = {}
stores = {}
kits = {}
shipments = {}
damage_claims = {}
field_service_requests = {}
recaps = {}
