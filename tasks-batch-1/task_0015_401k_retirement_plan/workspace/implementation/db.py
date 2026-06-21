"""In-memory data store for the 401(k) Retirement Plan API.

The store starts empty on every process boot. Tests build all state via the
declared API surface. No seeding occurs at startup.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from threading import RLock
from typing import Any


# A global lock to keep mutations atomic for the in-memory store.
LOCK = RLock()


# Primary stores keyed by id.
plans: dict[str, dict[str, Any]] = {}
participants: dict[str, dict[str, Any]] = {}
contribution_periods: dict[str, dict[str, Any]] = {}
loans: dict[str, dict[str, Any]] = {}
hardship_withdrawals: dict[str, dict[str, Any]] = {}
rmd_distributions: dict[str, dict[str, Any]] = {}
vesting_events: dict[str, dict[str, Any]] = {}


# Mutable system clock used for age, vesting, and YoS calculations.
# Tests advance this via POST /_clock/set_current_utc.
_system_clock: dict[str, datetime] = {"now": datetime.now(timezone.utc)}


def new_id() -> str:
    return str(uuid.uuid4())


def iso_ms(dt: datetime) -> str:
    """ISO 8601 UTC with millisecond precision."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_clock() -> datetime:
    return _system_clock["now"]


def set_clock(dt: datetime) -> None:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _system_clock["now"] = dt.astimezone(timezone.utc)


def reset_all() -> None:
    """Clear every store. Used by tests if they hit a reset endpoint;
    not exposed via HTTP in this implementation but useful for unit tests."""
    plans.clear()
    participants.clear()
    contribution_periods.clear()
    loans.clear()
    hardship_withdrawals.clear()
    rmd_distributions.clear()
    vesting_events.clear()
    _system_clock["now"] = datetime.now(timezone.utc)
