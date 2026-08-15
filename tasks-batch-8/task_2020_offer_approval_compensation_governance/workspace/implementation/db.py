"""In-memory data store. All state lives in module-level dicts, wiped on every
fresh process boot (per-test-server isolation). No disk persistence anywhere.
"""

import uuid
from datetime import datetime, timezone, timedelta


def new_id():
    return str(uuid.uuid4())


def iso_now_ms():
    """ISO 8601 UTC timestamp with three fractional digits (created_at/updated_at)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def _ts_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def now_ms():
    return _ts_now()


# ---------------------------------------------------------------------------
# Logical clock: startup default is exactly 2026-08-01T00:00:00Z (never wall).
# ---------------------------------------------------------------------------
_clock = {"current": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}

OFFER_EXPIRY_DAYS = 10


def clock_now():
    return _clock["current"]


def clock_set(dt):
    _clock["current"] = dt


def clock_now_iso():
    return _clock["current"].strftime("%Y-%m-%dT%H:%M:%SZ")


def request_has_body():
    from flask import request
    return bool(request.data) and request.data.strip() not in (b"", b"null")


# ---------------------------------------------------------------------------
# Entity stores, keyed by id. Start empty; nothing is seeded.
# ---------------------------------------------------------------------------
requisitions = {}
candidates = {}
snapshots = {}
policies = {}
offers = {}
approval_steps = {}
negotiation_rounds = {}
perks = {}
clearance_checks = {}
offer_letters = {}
offer_events = {}
delegation_grants = {}
