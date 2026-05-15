"""In-memory data store.

A single global store keyed by entity name; helper functions for generating ids,
timestamps, and version bumps live here.
"""
import threading
import uuid
from typing import Any

from .clock import now_iso


_LOCK = threading.RLock()

# Per-entity tables. Each table is a dict keyed by id.
_TABLES: dict[str, dict[str, dict]] = {
    "Advertiser": {},
    "QualificationDoc": {},
    "AccountUser": {},
    "Campaign": {},
    "AdGroup": {},
    "Creative": {},
    "AuctionEvent": {},
    "BillingEvent": {},
    "ConversionEvent": {},
    "WalletTransaction": {},
    "ReviewDecision": {},
    "AuditLog": {},
}

# Monotonic counters.
_advertiser_seq = 0
_campaign_seq_by_advertiser: dict[str, int] = {}


def lock():
    """Return the global re-entrant store lock — used to serialize mutations."""
    return _LOCK


def gen_uuid() -> str:
    return str(uuid.uuid4())


def next_advertiser_seq() -> int:
    global _advertiser_seq
    _advertiser_seq += 1
    return _advertiser_seq


def next_campaign_seq(advertiser_id: str) -> int:
    n = _campaign_seq_by_advertiser.get(advertiser_id, 0) + 1
    _campaign_seq_by_advertiser[advertiser_id] = n
    return n


def table(name: str) -> dict[str, dict]:
    return _TABLES[name]


def insert(name: str, record: dict) -> dict:
    _TABLES[name][record["id"]] = record
    return record


def get(name: str, record_id: str) -> dict | None:
    return _TABLES[name].get(record_id)


def list_all(name: str) -> list[dict]:
    return list(_TABLES[name].values())


def touch(record: dict) -> dict:
    """Bump updated_at and version on a record that carries those fields."""
    if "version" in record:
        record["version"] = int(record.get("version", 0)) + 1
    if "updated_at" in record:
        record["updated_at"] = now_iso()
    return record


def stamp_common(record: dict, with_version: bool) -> dict:
    """Add created_at + (optional) updated_at/version to a freshly created record."""
    ts = now_iso()
    record.setdefault("id", gen_uuid())
    record.setdefault("created_at", ts)
    if with_version:
        record.setdefault("updated_at", ts)
        record.setdefault("version", 1)
    return record
