"""In-memory store. Starts completely empty on every boot -- nothing is seeded."""
import threading

from flask import g

import common
from common import parse_dt, DEFAULT_CLOCK

LOCK = threading.RLock()

# Every collection is a plain dict keyed by entity id.  No file, no database.
accounts = {}
contracts = {}
lines = {}
technicians = {}
chemical_lots = {}
parts = {}
programs = {}
visits = {}
cycles = {}
balance_records = {}
inspections = {}
complaints = {}
glycol_loops = {}
cooler_readings = {}

COLLECTIONS = {
    "accounts": accounts,
    "contracts": contracts,
    "lines": lines,
    "technicians": technicians,
    "chemical_lots": chemical_lots,
    "parts": parts,
    "programs": programs,
    "visits": visits,
    "cycles": cycles,
    "balance_records": balance_records,
    "inspections": inspections,
    "complaints": complaints,
    "glycol_loops": glycol_loops,
    "cooler_readings": cooler_readings,
}

_state = {
    "clock": parse_dt(DEFAULT_CLOCK),
    "seq": 0,
}


# ------------------------------------------------------------------ logical clock

def now():
    """The logical clock. Nothing in this system reads real wall-clock time."""
    return _state["clock"]


def set_clock(dt):
    _state["clock"] = dt


def today():
    return now().date()


def next_seq():
    _state["seq"] += 1
    return _state["seq"]


# ------------------------------------------------------------------- row helpers

def new_row(extra=None, mutable=True):
    """Mint a row with the system-managed common fields."""
    row = {
        "id": common.new_id(),
        "created_at": now(),
        "_seq": next_seq(),
    }
    if mutable:
        row["updated_at"] = now()
        row["version"] = 1
    if extra:
        row.update(extra)
    return row


def touched_set():
    if not hasattr(g, "_touched"):
        g._touched = set()
    return g._touched


def touch(row):
    """Refresh updated_at and bump version -- at most once per row per request.

    Callers must only invoke this when the row actually changed: a record a
    cascade evaluates but leaves unchanged is not touched.
    """
    if row is None or "version" not in row:
        return row
    marker = id(row)
    seen = touched_set()
    if marker in seen:
        return row
    seen.add(marker)
    row["updated_at"] = now()
    row["version"] = row["version"] + 1
    return row


def set_field(row, field, value, mutated=None):
    """Assign only when the value differs; returns True when a change happened."""
    if row.get(field) == value:
        return False
    row[field] = value
    if mutated is not None:
        mutated.append(field)
    return True


# ---------------------------------------------------------------- query helpers

def sort_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def newest_first(rows, field):
    """Newest by `field` DESC, then created_at DESC, then insertion order DESC."""
    return sorted(rows, key=lambda r: (r[field], r["created_at"], r["_seq"]), reverse=True)


def by_created_desc(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]), reverse=True)


def account_lines(account_id):
    return [r for r in lines.values() if r["account_id"] == account_id]


def account_contracts(account_id):
    return sort_created([r for r in contracts.values() if r["account_id"] == account_id])


def active_contract(account_id):
    found = [r for r in account_contracts(account_id) if r["status"] == "ACTIVE"]
    return found[0] if found else None


def account_visits(account_id):
    return [r for r in visits.values() if r["account_id"] == account_id]


def visit_cycles(visit_id):
    return [r for r in cycles.values() if r["visit_id"] == visit_id]


def line_cycles(line_id):
    return [r for r in cycles.values() if r["line_id"] == line_id]


def visit_inspections(visit_id):
    return [r for r in inspections.values() if r["visit_id"] == visit_id]


def line_balance_records(line_id):
    return [r for r in balance_records.values() if r["line_id"] == line_id]


def account_loop(account_id):
    found = sort_created([r for r in glycol_loops.values() if r["account_id"] == account_id])
    return found[0] if found else None


def loop_readings(loop_id):
    return [r for r in cooler_readings.values() if r["glycol_loop_id"] == loop_id]


def account_complaints(account_id):
    return [r for r in complaints.values() if r["account_id"] == account_id]
