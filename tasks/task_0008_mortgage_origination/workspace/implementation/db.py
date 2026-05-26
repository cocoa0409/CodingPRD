"""In-memory data store. Starts empty on every boot — NO seeding."""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any


# ---------- Stores ----------
# Each store keyed by entity id (UUID string).
applicants: dict[str, dict[str, Any]] = {}
loan_applications: dict[str, dict[str, Any]] = {}
income_verifications: dict[str, dict[str, Any]] = {}
asset_verifications: dict[str, dict[str, Any]] = {}
appraisals: dict[str, dict[str, Any]] = {}
title_searches: dict[str, dict[str, Any]] = {}
rate_locks: dict[str, dict[str, Any]] = {}
disclosures: dict[str, dict[str, Any]] = {}
udaap_checks: dict[str, dict[str, Any]] = {}

# Auxiliary: originating LoanOfficer X-User-ID for SoD enforcement,
# keyed by loan_application_id.
loan_application_creator: dict[str, str] = {}

# Logical system clock (overridable via POST /_clock/set_current_utc).
# When None, fall back to wall clock UTC.
_logical_clock: dict[str, datetime | None] = {"now": None}

# Global lock for atomicity of multi-entity mutations.
lock = threading.RLock()


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    # Hex chars, prefixed "req_". 20 hex chars after the prefix.
    return "req_" + uuid.uuid4().hex[:20]


def utcnow() -> datetime:
    if _logical_clock["now"] is not None:
        return _logical_clock["now"]
    return datetime.now(timezone.utc)


def set_clock(dt: datetime) -> None:
    _logical_clock["now"] = dt


def fmt_ts(dt: datetime) -> str:
    """ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    # Microseconds → milliseconds; truncate to 3 fractional digits.
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def parse_ts(s: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into a tz-aware UTC datetime."""
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
    """Reset all stores (used only by tests if they wish; not called at boot)."""
    with lock:
        for store in (
            applicants,
            loan_applications,
            income_verifications,
            asset_verifications,
            appraisals,
            title_searches,
            rate_locks,
            disclosures,
            udaap_checks,
            loan_application_creator,
        ):
            store.clear()
        _logical_clock["now"] = None
