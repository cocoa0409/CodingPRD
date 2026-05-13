"""In-memory data store for the EV charging operations API."""

from __future__ import annotations

import threading
import uuid

from clock import now_iso


# Single shared lock guarding mutations to keep state machine transitions
# observable and serialized for the test suite.
LOCK = threading.RLock()


# Resource tables — each maps id -> resource dict.
operators: dict[str, dict] = {}
stations: dict[str, dict] = {}
piles: dict[str, dict] = {}
members: dict[str, dict] = {}
pricing_versions: dict[str, dict] = {}
promo_activities: dict[str, dict] = {}
reservations: dict[str, dict] = {}
queue_entries: dict[str, dict] = {}
sessions: dict[str, dict] = {}
curve_points: dict[str, dict] = {}
fault_reports: dict[str, dict] = {}
repair_tickets: dict[str, dict] = {}
ledger_entries: dict[str, dict] = {}
payouts: dict[str, dict] = {}
audit_logs: dict[str, dict] = {}
external_events: dict[str, dict] = {}


# Insertion-order tracking so callers can list entities in creation order
# regardless of whether they carry a created_at field.
_insertion_seq = 0


def next_seq() -> int:
    global _insertion_seq
    _insertion_seq += 1
    return _insertion_seq


def new_id() -> str:
    return str(uuid.uuid4())


def with_common_fields(record: dict) -> dict:
    """Initialize common envelope fields on a new resource."""
    record.setdefault("id", new_id())
    ts = now_iso()
    record.setdefault("created_at", ts)
    record.setdefault("updated_at", ts)
    record.setdefault("version", 1)
    record["_seq"] = next_seq()
    return record


def append_only_record(record: dict) -> dict:
    """Initialize an append-only resource: id + created_at, no version."""
    record.setdefault("id", new_id())
    record.setdefault("created_at", now_iso())
    record["_seq"] = next_seq()
    return record


def bump(record: dict) -> dict:
    """Update updated_at and version on a mutation."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
    return record


def public(record: dict) -> dict:
    """Strip internal fields (those starting with underscore) for output."""
    if record is None:
        return None
    return {k: v for k, v in record.items() if not k.startswith("_")}


def public_list(records: list) -> list:
    return [public(r) for r in records]
