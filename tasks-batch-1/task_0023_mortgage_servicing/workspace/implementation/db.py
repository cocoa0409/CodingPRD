"""In-memory data store. Starts empty on every boot — NO seeding."""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any


# ---------- Stores ----------
borrowers: dict[str, dict[str, Any]] = {}
loans: dict[str, dict[str, Any]] = {}
payments: dict[str, dict[str, Any]] = {}
escrow_accounts: dict[str, dict[str, Any]] = {}
escrow_disbursements: dict[str, dict[str, Any]] = {}
escrow_analyses: dict[str, dict[str, Any]] = {}
forbearance_plans: dict[str, dict[str, Any]] = {}
foreclosure_cases: dict[str, dict[str, Any]] = {}
mediation_sessions: dict[str, dict[str, Any]] = {}
pmi_removal_requests: dict[str, dict[str, Any]] = {}

# Logical/simulated UTC clock per PRD §2.4.
# When None, fall back to real wall-clock.
_logical_clock: dict[str, datetime | None] = {"now": None}

# Global lock for atomicity of multi-entity mutations.
lock = threading.RLock()


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    return "req_" + uuid.uuid4().hex[:20]


def utcnow() -> datetime:
    if _logical_clock["now"] is not None:
        return _logical_clock["now"]
    return datetime.now(timezone.utc)


def set_clock(dt: datetime) -> None:
    _logical_clock["now"] = dt


def get_clock() -> datetime | None:
    return _logical_clock["now"]


def fmt_ts(dt: datetime) -> str:
    """ISO 8601 UTC with three fractional digits and Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def parse_ts(s: str) -> datetime:
    """Parse an ISO 8601 timestamp into a tz-aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("timestamp must be a string")
    raw = s.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def reset_all() -> None:
    with lock:
        for store in (
            borrowers,
            loans,
            payments,
            escrow_accounts,
            escrow_disbursements,
            escrow_analyses,
            forbearance_plans,
            foreclosure_cases,
            mediation_sessions,
            pmi_removal_requests,
        ):
            store.clear()
        _logical_clock["now"] = None
