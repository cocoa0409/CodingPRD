"""In-memory data store. All state lives in module-level dicts keyed by id.

The store starts EMPTY on every boot. Nothing is seeded or preloaded — every
entity is created by tests via the declared API surface.
"""
import uuid
from datetime import datetime, timezone


# One dict per entity type, keyed by the entity's UUID id.
policyholders = {}
bundles = {}
policies = {}
coverage_lines = {}
scheduled_items = {}
additional_insureds = {}
premium_invoices = {}
payments = {}
claims = {}
claim_items = {}

# Monotonic sequence used to break created_at ties deterministically so that
# "ascending created_at order" is stable even when two records share the same
# millisecond timestamp. Never exposed; purely an internal ordering aid.
_seq = 0

# Server clock for lapse/grace/expiry/reinstatement/refund timing.
# Defaults to real wall-clock UTC until a test sets it via /_clock/set_current_utc.
_current_utc = None


def reset():
    """Clear all state. Not called at startup; provided for completeness."""
    global _seq, _current_utc
    policyholders.clear()
    bundles.clear()
    policies.clear()
    coverage_lines.clear()
    scheduled_items.clear()
    additional_insureds.clear()
    premium_invoices.clear()
    payments.clear()
    claims.clear()
    claim_items.clear()
    _seq = 0
    _current_utc = None


def new_id():
    return str(uuid.uuid4())


def next_seq():
    global _seq
    _seq += 1
    return _seq


def now_iso():
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    return _format_iso(datetime.now(timezone.utc))


def _format_iso(dt):
    # Render with milliseconds and a trailing Z.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def get_current_utc():
    """Return the server's current UTC instant as a timezone-aware datetime."""
    if _current_utc is not None:
        return _current_utc
    return datetime.now(timezone.utc)


def set_current_utc(dt):
    global _current_utc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _current_utc = dt.astimezone(timezone.utc)
    return _current_utc


def now_iso_clock():
    """ISO 8601 rendering of the server's current UTC clock (3 fractional digits)."""
    return _format_iso(get_current_utc())
