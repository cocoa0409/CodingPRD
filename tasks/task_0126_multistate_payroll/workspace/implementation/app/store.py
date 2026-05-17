"""In-memory data store — row tables keyed by id, with a global RLock."""
from __future__ import annotations

from threading import RLock
from typing import Any


class _Tables:
    def __init__(self) -> None:
        self.employees: dict[str, dict[str, Any]] = {}
        self.w4_profiles: dict[str, dict[str, Any]] = {}
        self.pay_periods: dict[str, dict[str, Any]] = {}
        self.payroll_items: dict[str, dict[str, Any]] = {}
        self.paychecks: dict[str, dict[str, Any]] = {}
        self.garnishment_orders: dict[str, dict[str, Any]] = {}
        self.ytd_ledger: dict[str, dict[str, Any]] = {}
        self.remittances: dict[str, dict[str, Any]] = {}
        self.tax_brackets: dict[str, dict[str, Any]] = {}

        # Monotonic creation sequence for stable ordering
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
