"""In-memory data store + utilities.

Every collection is a dict keyed by uuid string. The store starts empty on
every boot; tests create whatever state they need via the declared API.

`ClockState` is special: a single mutable global that test code drives via
/_clock/set_current_utc. Default at boot: 2026-01-01T00:00:00.000Z (well before
any clock the test suite cares about, so any test that doesn't set the clock
still gets a sane tax_year).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict


def new_id() -> str:
    return str(uuid.uuid4())


def iso_ms(dt: datetime) -> str:
    """Format a datetime (must be UTC-aware) as ISO 8601 with millisecond precision."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Store:
    def __init__(self) -> None:
        self.donors: Dict[str, Dict[str, Any]] = {}
        self.beneficiaries: Dict[str, Dict[str, Any]] = {}
        self.accounts: Dict[str, Dict[str, Any]] = {}
        self.scheduled_contributions: Dict[str, Dict[str, Any]] = {}
        self.contributions: Dict[str, Dict[str, Any]] = {}
        self.withdrawals: Dict[str, Dict[str, Any]] = {}
        self.beneficiary_changes: Dict[str, Dict[str, Any]] = {}
        self.state_tax_incentives: Dict[str, Dict[str, Any]] = {}
        self.forms_1099q: Dict[str, Dict[str, Any]] = {}

        # Submitter tracking for segregation-of-duties.
        # withdrawal_id -> X-User-ID that submitted (DRAFT->SUBMITTED).
        self.withdrawal_submitter: Dict[str, str] = {}
        # beneficiary_change_id -> X-User-ID that created the change.
        self.bchange_creator: Dict[str, str] = {}

        # System clock — single instant, no envelope fields.
        self.clock_utc: datetime = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


store = Store()


def reset_store() -> None:
    """Wipe state. The server starts fresh on every boot via start.sh, but this
    helper exists for tests/dev that import the module directly."""
    global store
    store = Store()


# ---------------------------------------------------------------------------
# Entity envelope helpers
# ---------------------------------------------------------------------------

def stamp_create(entity: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    """Pin id/created_at/updated_at/version for a freshly-minted entity."""
    entity["id"] = new_id()
    ts = iso_ms(now)
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    return entity


def stamp_update(entity: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    """Refresh updated_at and bump version on a successful mutation."""
    entity["updated_at"] = iso_ms(now)
    entity["version"] = entity.get("version", 1) + 1
    return entity
