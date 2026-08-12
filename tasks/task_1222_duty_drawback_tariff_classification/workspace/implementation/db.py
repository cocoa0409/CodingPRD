"""In-memory data store. The store starts empty on every boot — no seeding.

The logical clock reads exactly 2026-05-01T00:00:00Z before any
POST /customs/_clock/set_current_utc call, and never falls back to wall-clock.
"""
from datetime import datetime, timezone

STORE = {
    "clients": {},
    "classifications": {},
    "binding_rulings": {},
    "import_entries": {},
    "export_shipments": {},
    "claims": {},
    "claim_lines": {},
    "tariff_measures": {},
    "invoices": {},
    "audit_cases": {},
    "compliance_records": {},
}

CLOCK = {"current": datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)}

_SEQ = {"n": 0}


def next_seq():
    """Monotonic insertion sequence — deterministic created_at tie-break."""
    _SEQ["n"] += 1
    return _SEQ["n"]


def logical_now():
    return CLOCK["current"]


def set_logical_clock(dt):
    CLOCK["current"] = dt
