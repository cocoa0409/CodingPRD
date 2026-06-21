"""In-memory data store. Starts empty on every boot — no seeding."""

import uuid
from datetime import datetime, timezone

# Each collection: id -> record dict.
regions = {}
payment_standards = {}
households = {}
vouchers = {}
units = {}
landlords = {}
hap_contracts = {}
inspections = {}
rent_reasonableness = {}
portability_moves = {}
annual_reviews = {}
special_mobility_grants = {}

# Monotonic counter to provide a stable creation order for sorting (the
# wall-clock created_at can collide at sub-millisecond resolution).
_seq = {"n": 0}

# Server clock used for time-gated transitions. None => use real UTC.
_clock = {"current_utc": None}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_id():
    return str(uuid.uuid4())


def now_dt():
    return datetime.now(timezone.utc)


def iso_now():
    dt = now_dt()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def current_utc():
    """The server's notion of 'now' for expiration / cure-deadline checks."""
    if _clock["current_utc"] is not None:
        return _clock["current_utc"]
    return now_dt()


def set_current_utc(dt):
    _clock["current_utc"] = dt
