"""In-memory data store, ID/timestamp utilities, and platform-clock helpers."""

from __future__ import annotations

import datetime as _dt
import threading
import uuid
from typing import Any


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

EPOCH_ISO = "1970-01-01T00:00:00.000Z"


def new_id() -> str:
    return str(uuid.uuid4())


def parse_iso(value: str) -> _dt.datetime:
    """Parse an ISO 8601 UTC string. Accepts fractional digits and 'Z' suffix."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = _dt.datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt.astimezone(_dt.timezone.utc)


def fmt_iso(dt: _dt.datetime) -> str:
    """Format datetime as ISO 8601 UTC with millisecond precision and Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    dt = dt.astimezone(_dt.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


class Store:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        # Top-level: id -> dict
        self.platforms: dict[str, dict] = {}
        # Per-platform collections — each maps id -> dict
        self.drugs: dict[str, dict] = {}
        self.vendors: dict[str, dict] = {}
        self.pharmacists: dict[str, dict] = {}
        self.customers: dict[str, dict] = {}
        self.prescriptions: dict[str, dict] = {}
        self.purchase_limit_rules: dict[str, dict] = {}
        self.orders: dict[str, dict] = {}
        self.pharmacist_reviews: dict[str, dict] = {}
        self.cold_chain_shipments: dict[str, dict] = {}
        self.adverse_reaction_reports: dict[str, dict] = {}
        # Append-only logs
        self.audit_logs: list[dict] = []
        self.external_events: list[dict] = []
        self.external_event_keys: set[str] = set()
        self.prescriber_denylist: dict[str, dict] = {}
        # Insertion-order trackers per type (for stable list ordering — matches
        # creation timestamp order because clock advances are monotone and we
        # also fall back to a per-row sequence when timestamps tie).
        self._seq = 0

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq


db = Store()


# ---------------------------------------------------------------------------
# Platform clock
# ---------------------------------------------------------------------------


def platform_clock(platform: dict) -> str:
    return platform["current_clock_iso"]


def set_platform_clock(platform: dict, iso: str) -> None:
    platform["current_clock_iso"] = iso


def stamp_create(row: dict, platform: dict, *, common: bool = True) -> dict:
    """Initialize standard system fields on a new row."""
    if "id" not in row:
        row["id"] = new_id()
    now = platform_clock(platform)
    if common:
        row["created_at"] = now
        row["updated_at"] = now
        row["version"] = 1
    else:
        row.setdefault("created_at", now)
    row["_seq"] = db.next_seq()
    return row


def stamp_update(row: dict, platform: dict) -> dict:
    """Bump updated_at and version after a mutation."""
    row["updated_at"] = platform_clock(platform)
    row["version"] = int(row.get("version", 0)) + 1
    return row


# ---------------------------------------------------------------------------
# Public-facing serialization (strip private fields, hide _seq)
# ---------------------------------------------------------------------------


_PRIVATE_PREFIX = "_"


def serialize(row: dict, *, include: list[str] | None = None) -> dict:
    if row is None:
        return None
    if include is not None:
        return {k: row[k] for k in include if k in row}
    return {k: v for k, v in row.items() if not k.startswith(_PRIVATE_PREFIX)}


def serialize_list(rows: list[dict]) -> list[dict]:
    return [serialize(r) for r in rows]


# ---------------------------------------------------------------------------
# Lookup helpers (raise ApiError if not found and platform mismatch)
# ---------------------------------------------------------------------------


def by_id(coll: dict[str, dict], rid: str) -> dict | None:
    return coll.get(rid)


def filter_by_platform(coll: dict[str, dict], platform_id: str) -> list[dict]:
    return [r for r in coll.values() if r.get("platform_id") == platform_id]


def order_by_seq(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: r.get("_seq", 0))


# ---------------------------------------------------------------------------
# Append-only logs
# ---------------------------------------------------------------------------


def append_audit_log(
    *,
    platform: dict,
    subject_type: str,
    subject_id: str,
    action: str,
    actor_role: str,
    actor_id: str,
    payload: dict | None = None,
) -> dict:
    row = {
        "id": new_id(),
        "platform_id": platform["id"],
        "subject_type": subject_type,
        "subject_id": subject_id,
        "action": action,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "occurred_at": platform_clock(platform),
        "payload": payload or {},
        "created_at": platform_clock(platform),
        "_seq": db.next_seq(),
    }
    db.audit_logs.append(row)
    return row


def emit_external_event(
    *,
    platform: dict,
    channel: str,
    event_type: str,
    subject_type: str,
    subject_id: str,
    payload: dict | None = None,
    idempotency_key: str | None = None,
) -> dict | None:
    """Idempotent emission. Returns the new event dict, or None if a duplicate
    idempotency_key has already been emitted (silently dropped)."""
    if idempotency_key and idempotency_key in db.external_event_keys:
        return None
    row = {
        "id": new_id(),
        "platform_id": platform["id"],
        "channel": channel,
        "event_type": event_type,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "occurred_at": platform_clock(platform),
        "payload": payload or {},
        "idempotency_key": idempotency_key or "",
        "created_at": platform_clock(platform),
        "_seq": db.next_seq(),
    }
    if idempotency_key:
        db.external_event_keys.add(idempotency_key)
    db.external_events.append(row)
    return row


__all__ = [
    "db",
    "EPOCH_ISO",
    "new_id",
    "parse_iso",
    "fmt_iso",
    "platform_clock",
    "set_platform_clock",
    "stamp_create",
    "stamp_update",
    "serialize",
    "serialize_list",
    "by_id",
    "filter_by_platform",
    "order_by_seq",
    "append_audit_log",
    "emit_external_event",
]
