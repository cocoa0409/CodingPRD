"""In-memory data store and the test-driveable logical clock.

All state lives in module-level dicts keyed by id. The store starts EMPTY on
every process boot — nothing is seeded. Every restart wipes all state, which is
exactly what the per-test-server harness wants.
"""
import itertools
import uuid
from datetime import datetime, timezone

# One dict per entity collection, keyed by id.
jurisdictions = {}
drivers = {}
citations = {}
charges = {}
installment_plans = {}
installments = {}
payments = {}
contest_requests = {}
enrollments = {}
license_holds = {}
collections_referrals = {}
warrants = {}
point_ledger = {}

# Monotonic creation counter to give every row a strict, total created_at order
# even when wall-clock timestamps collide (rows minted in the same millisecond).
_seq = itertools.count(1)

# --- Logical clock ---------------------------------------------------------
# The server's notion of "now" for deadline-gated checks. Settable via
# POST /_clock/set_current_utc. Defaults to real wall-clock UTC.
_clock_override = None  # datetime (aware) or None


def now():
    """Return the current logical UTC time as an aware datetime."""
    if _clock_override is not None:
        return _clock_override
    return datetime.now(timezone.utc)


def set_clock(dt):
    global _clock_override
    _clock_override = dt


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def iso_now_ms():
    """ISO 8601 UTC with three fractional digits and trailing Z, at logical now."""
    return iso(now())


def iso(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"
