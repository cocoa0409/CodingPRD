"""In-memory data store, logical clock and record helpers.

Nothing is seeded here: every store starts empty on every boot and all state is
created by clients through the declared endpoints.
"""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

# ---------------------------------------------------------------- logical clock
# PRD 2.6: before the clock has ever been set it reads exactly
# 2026-08-01T00:00:00Z, and it never falls back to real wall-clock time.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0)

_state = {"clock": DEFAULT_CLOCK, "seq": 0}

# ---------------------------------------------------------------- stores
state_law_profiles = {}
dealers = {}
labor_rate_requests = {}
vehicles = {}
labor_operations = {}
parts = {}
claims = {}
claim_edits = {}
parts_returns = {}
audits = {}
findings = {}
appeals = {}
goodwill_auths = {}
ledger_entries = {}

ALL_STORES = (
    state_law_profiles,
    dealers,
    labor_rate_requests,
    vehicles,
    labor_operations,
    parts,
    claims,
    claim_edits,
    parts_returns,
    audits,
    findings,
    appeals,
    goodwill_auths,
    ledger_entries,
)


def reset():
    for store in ALL_STORES:
        store.clear()
    _state["clock"] = DEFAULT_CLOCK
    _state["seq"] = 0


def now():
    """The logical clock instant (a naive UTC datetime)."""
    return _state["clock"]


def set_clock(dt):
    _state["clock"] = dt
    return dt


def next_seq():
    _state["seq"] += 1
    return _state["seq"]


def new_id():
    # PRD 2.4: bare UUID, no type prefix.
    return str(uuid.uuid4())


def iso3(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if dt is None:
        return None
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


def new_record(store, versioned=True, **fields):
    """Create a record with the system fields PRD 2.4 mandates."""
    created = now()
    rec = {"id": new_id(), "created_at": iso3(created)}
    rec.update(fields)
    if versioned:
        rec["updated_at"] = iso3(created)
        rec["version"] = 1
    rec["_created_dt"] = created
    rec["_seq"] = next_seq()
    store[rec["id"]] = rec
    return rec


def touch(rec):
    """Refresh updated_at and advance version by exactly 1."""
    rec["updated_at"] = iso3(now())
    rec["version"] = rec.get("version", 0) + 1
    return rec


def sort_key(rec):
    """created_at ascending, with an internal monotonic tie-break."""
    return (rec["_created_dt"], rec["_seq"])


def ordered(store_or_iter):
    values = store_or_iter.values() if isinstance(store_or_iter, dict) else store_or_iter
    return sorted(values, key=sort_key)


def add_days(dt, days):
    return dt + timedelta(days=int(days))


def public(rec):
    """Strip internal keys and JSON-ify Decimals / datetimes."""
    out = {}
    for key, value in rec.items():
        if key.startswith("_"):
            continue
        out[key] = _jsonify(value)
    return out


def _jsonify(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return iso3(value)
    if isinstance(value, list):
        return [_jsonify(item) for item in value]
    if isinstance(value, dict):
        return {k: _jsonify(v) for k, v in value.items()}
    return value
