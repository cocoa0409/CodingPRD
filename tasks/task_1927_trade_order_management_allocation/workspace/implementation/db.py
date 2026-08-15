"""In-memory data store. Module-level dicts keyed by id; a fresh process
starts completely empty (per-test-server isolation wipes all state)."""
import threading
from datetime import datetime, timezone

LOCK = threading.RLock()

# entity collections: id -> record dict (records may carry "_seq" internals)
store = {
    "accounts": {},
    "securities": {},
    "brokers": {},
    "budgets": {},
    "restrictions": {},
    "orders": {},
    "blocks": {},
    "fills": {},
    "plans": {},
    "allocations": {},
    "trade_errors": {},
    "instructions": {},
    "positions": {},
    "audit_events": {},
}

# (account_id, security_id) -> position id
position_index = {}

# global insertion sequence for deterministic created_at ordering
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


# ---- desk logical clock (never falls back to wall clock) ----
def _parse_iso(s):
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


CLOCK_DEFAULT_RAW = "2026-08-01T00:00:00Z"
clock = {"raw": CLOCK_DEFAULT_RAW, "dt": _parse_iso(CLOCK_DEFAULT_RAW)}


def clock_now():
    return clock["dt"]


def clock_raw():
    return clock["raw"]


def clock_set(raw):
    clock["raw"] = raw
    clock["dt"] = _parse_iso(raw)
