"""In-memory data store — row tables keyed by id, with a global RLock."""
from __future__ import annotations

from threading import RLock
from typing import Any


class _Tables:
    def __init__(self) -> None:
        self.participants: dict[str, dict[str, Any]] = {}
        self.accounts: dict[str, dict[str, Any]] = {}
        self.contributions: dict[str, dict[str, Any]] = {}
        self.distributions: dict[str, dict[str, Any]] = {}
        self.conversions: dict[str, dict[str, Any]] = {}
        self.claims: dict[str, dict[str, Any]] = {}
        self.forms_1099r: dict[str, dict[str, Any]] = {}
        self.excess_penalties: dict[str, dict[str, Any]] = {}

        # Index: account_id -> claim_id (one claim per inherited account)
        self.claim_by_account: dict[str, str] = {}

        # Monotonic creation sequence (for stable ordering when timestamps collide)
        self.create_seq: int = 0

        self.lock: RLock = RLock()

    def next_seq(self) -> int:
        self.create_seq += 1
        return self.create_seq


_store = _Tables()


def store() -> _Tables:
    return _store


def reset_store() -> None:
    global _store
    _store = _Tables()
    from . import clock as _clock
    _clock.clock.reset()
