"""In-memory data store + simulated clock for the PBM API.

The store tracks every entity by id, the simulated clock instant (driven by
POST /_clock/advance), and provides timestamp/version helpers shared across
all routes.

A single re-entrant lock guards every state-mutating path so the concurrency
guarantees described in PRD §2.10 are met (first-writer-wins by serialising
each adjudicate/approve/pay/reverse).
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any


# Simulated clock anchored at a deterministic epoch so test runs have a
# stable starting point regardless of wall time.
_CLOCK_EPOCH = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class _Clock:
    """Server-controlled simulated clock advanced via POST /_clock/advance."""

    def __init__(self) -> None:
        self._now = _CLOCK_EPOCH

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: int) -> datetime:
        self._now = self._now + timedelta(seconds=int(seconds))
        return self._now


class Store:
    """Thread-safe in-memory storage of every entity."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.clock = _Clock()
        self.plans: dict[str, dict] = {}
        self.drugs: dict[str, dict] = {}
        self.members: dict[str, dict] = {}
        self.formulary_entries: dict[str, dict] = {}
        self.prior_authorizations: dict[str, dict] = {}
        self.claims: dict[str, dict] = {}
        self.copay_cards: dict[str, dict] = {}
        self.rebate_agreements: dict[str, dict] = {}
        self.ledger_entries: dict[str, dict] = {}

    # ----- timestamp / id helpers -----
    @staticmethod
    def new_id() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def fmt_ts(dt: datetime) -> str:
        """Format any datetime as ISO 8601 UTC with three fractional digits."""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
            # strip tzinfo for formatting
            dt = dt.replace(tzinfo=timezone.utc)
        ms = int(dt.microsecond / 1000)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"

    def now_ts(self) -> str:
        return self.fmt_ts(self.clock.now())

    # ----- common-field initializers -----
    def init_common_fields(self, entity: dict[str, Any]) -> dict[str, Any]:
        ts = self.now_ts()
        entity.setdefault("id", self.new_id())
        entity["created_at"] = ts
        entity["updated_at"] = ts
        entity["version"] = 1
        return entity

    def bump(self, entity: dict[str, Any]) -> None:
        entity["updated_at"] = self.now_ts()
        entity["version"] = int(entity.get("version", 0)) + 1


# Singleton store instance shared across the app.
STORE = Store()
