"""In-memory data store, ID/timestamp utilities, and a logical clock.

Per PRD §3.11 (Test-driving capabilities) the system uses a logical clock
that PlatformAdmin can advance via /_clock/advance. Real wall-clock is
used until the first /_clock/advance call; thereafter the latest advanced
instant is treated as "now". We store the clock as an ISO datetime string;
all date math goes through datetime helpers.
"""

from __future__ import annotations

import datetime as _dt
import threading
import uuid
from typing import Any


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


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

        # Primary collections (id -> dict)
        self.budget_accounts: dict[str, dict] = {}
        self.suppliers: dict[str, dict] = {}
        self.requirements: dict[str, dict] = {}
        self.quotes: dict[str, dict] = {}
        self.purchase_orders: dict[str, dict] = {}
        self.approval_steps: dict[str, dict] = {}
        self.contracts: dict[str, dict] = {}
        self.contract_versions: dict[str, dict] = {}
        self.clause_templates: dict[str, dict] = {}
        self.receipts: dict[str, dict] = {}
        self.payment_schedules: dict[str, dict] = {}
        self.payments: dict[str, dict] = {}
        self.invoices: dict[str, dict] = {}
        # Append-only audit log
        self.audit_log: list[dict] = []
        # Supplier-delivery records: list of {purchase_order_id, delivery_note_no, declared_quantity}
        self.delivery_notes: list[dict] = []

        # Logical clock (None means use wall clock)
        self._clock: _dt.datetime | None = None
        # Insertion sequence — used as a stable secondary sort key
        self._seq = 0

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq

    # --- clock ---
    def now(self) -> _dt.datetime:
        if self._clock is not None:
            return self._clock
        return _dt.datetime.now(tz=_dt.timezone.utc)

    def now_iso(self) -> str:
        return fmt_iso(self.now())

    def set_clock(self, dt: _dt.datetime) -> None:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_dt.timezone.utc)
        self._clock = dt.astimezone(_dt.timezone.utc)


db = Store()


# ---------------------------------------------------------------------------
# Common-field stamping
# ---------------------------------------------------------------------------


def stamp_create(row: dict, *, common: bool = True) -> dict:
    """Initialize standard system fields on a new row.

    common=True → id, created_at, updated_at, version=1
    common=False → id, created_at only (auxiliary entities per PRD §2.4)
    """
    if "id" not in row:
        row["id"] = new_id()
    now_iso = db.now_iso()
    row.setdefault("created_at", now_iso)
    if common:
        row["updated_at"] = now_iso
        row["version"] = 1
    row["_seq"] = db.next_seq()
    return row


def stamp_update(row: dict) -> dict:
    """Bump updated_at and version after a mutation. Only call on common-fields entities."""
    row["updated_at"] = db.now_iso()
    row["version"] = int(row.get("version", 0)) + 1
    return row


# ---------------------------------------------------------------------------
# Public-facing serialization (strip private underscore-prefixed fields)
# ---------------------------------------------------------------------------


_PRIVATE_PREFIX = "_"


def serialize(row: dict | None) -> dict | None:
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith(_PRIVATE_PREFIX)}


def serialize_list(rows: list[dict]) -> list[dict]:
    return [serialize(r) for r in rows]


def order_by_created_then_seq(rows: list[dict]) -> list[dict]:
    """Sort rows by created_at ascending, with _seq as a stable tiebreaker.

    Per PRD §2.3 the default list ordering is created_at ascending.
    """
    return sorted(rows, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))


__all__ = [
    "db",
    "new_id",
    "parse_iso",
    "fmt_iso",
    "stamp_create",
    "stamp_update",
    "serialize",
    "serialize_list",
    "order_by_created_then_seq",
]
