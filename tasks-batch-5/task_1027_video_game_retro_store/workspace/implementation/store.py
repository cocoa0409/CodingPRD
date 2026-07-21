"""In-memory data store. Every dict is keyed by entity id. All state is created
by tests via the declared endpoints — nothing is seeded at startup. A fresh
process (start.sh) wipes everything.
"""
import uuid

from timeutil import now_iso, parse_dt

# --- Entity tables --------------------------------------------------------
members = {}
products = {}
product_stocks = {}
inventory_items = {}
pre_orders = {}
allocations = {}
trade_ins = {}
rentals = {}
sales = {}
stations = {}
tournaments = {}
store_credit_entries = {}

# --- Logical clock (PRD 2.10) --------------------------------------------
_CLOCK_DEFAULT = "2026-07-01T00:00:00Z"
_clock = {"raw": _CLOCK_DEFAULT, "dt": parse_dt(_CLOCK_DEFAULT)}

_seq_counter = {"n": 0}


def next_seq():
    _seq_counter["n"] += 1
    return _seq_counter["n"]


def new_id():
    return str(uuid.uuid4())


def clock_dt():
    return _clock["dt"]


def clock_raw():
    return _clock["raw"]


def set_clock(raw):
    _clock["dt"] = parse_dt(raw)
    _clock["raw"] = raw


def make_record(fields):
    """Create a record with the standard system-managed fields (id, created_at,
    updated_at, version) plus the supplied domain fields."""
    ts = now_iso()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    rec.update(fields)
    return rec


def make_ledger_entry(fields):
    """StoreCreditEntry is an append-only event: only id + created_at, no
    updated_at / version (PRD 2.4)."""
    rec = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": next_seq(),
    }
    rec.update(fields)
    return rec


def touch(rec):
    """Mark a resource mutated: refresh updated_at and bump version by one."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec["version"] + 1


def serialize(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}
