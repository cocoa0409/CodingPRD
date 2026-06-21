"""In-memory data store.

All state lives in module-level dicts keyed by id. Every byte is wiped when the
process restarts (per-test-server isolation re-launches start.sh before each
test). NOTHING is seeded here — tests build all state via the API.

Common (full) entities carry: id, created_at, updated_at, version.
Append-only audit records (LedgerEntry, LoyaltyAccrual) carry only id, created_at.
"""
import uuid
from datetime import datetime, timezone

# ---- entity tables -------------------------------------------------------
locations = {}
vehicle_classes = {}
rate_plans = {}
vehicles = {}
members = {}
reservations = {}
agreements = {}
incidents = {}
ledger_entries = {}
loyalty_accruals = {}

# ---- server clock (test-driving) -----------------------------------------
# When None, the real wall clock is used. /_clock/set_current_utc overrides it.
_current_utc_override = None

# Monotonic creation sequence so created_at ties are still deterministically
# ordered (timestamps have ms resolution; rapid creates can collide).
_seq = 0


def reset():
    """Wipe all state. Used at process start (defensive — process is fresh)."""
    global _current_utc_override, _seq
    for table in (
        locations,
        vehicle_classes,
        rate_plans,
        vehicles,
        members,
        reservations,
        agreements,
        incidents,
        ledger_entries,
        loyalty_accruals,
    ):
        table.clear()
    _current_utc_override = None
    _seq = 0


def new_id():
    return str(uuid.uuid4())


def next_seq():
    global _seq
    _seq += 1
    return _seq


def _now_dt():
    if _current_utc_override is not None:
        return _current_utc_override
    return datetime.now(timezone.utc)


def now_iso():
    dt = _now_dt()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def current_utc():
    """The server's notion of 'now' as a tz-aware datetime (for grace checks)."""
    return _now_dt()


def set_current_utc(dt):
    global _current_utc_override
    _current_utc_override = dt
