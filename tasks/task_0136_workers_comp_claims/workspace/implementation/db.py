"""In-memory data store for the Workers-Comp Claims API.

Every store starts empty on each fresh boot. The test harness restarts the
server via start.sh before every test (per-test-server isolation), so there is
no carry-over state. NO entity is seeded, preloaded, or hardcoded at startup —
every entity is created through the declared API surface.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional


def new_uuid() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    """Wall-clock ISO-8601 UTC timestamp with three fractional digits.

    Used for created_at / updated_at / api_request_timestamp (PRD §2.4).
    Business-time comparisons use the logical clock (get_current_utc()).
    """
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_request_id() -> str:
    raw = uuid.uuid4().hex + uuid.uuid4().hex
    return "req_" + raw[:20]


# ---- entity stores (cleared at module load each fresh boot) ----------------

employers: Dict[str, Dict[str, Any]] = {}
policies: Dict[str, Dict[str, Any]] = {}
workers: Dict[str, Dict[str, Any]] = {}
claims: Dict[str, Dict[str, Any]] = {}
injury_reports: Dict[str, Dict[str, Any]] = {}
wage_statements: Dict[str, Dict[str, Any]] = {}
benefit_payments: Dict[str, Dict[str, Any]] = {}
impairment_ratings: Dict[str, Dict[str, Any]] = {}
rtw_offers: Dict[str, Dict[str, Any]] = {}
reserves: Dict[str, Dict[str, Any]] = {}
ime_orders: Dict[str, Dict[str, Any]] = {}
experience_mods: Dict[str, Dict[str, Any]] = {}


# Logical clock (PRD §2.4). Tests overwrite via POST /_clock/set_current_utc.
# Defaults to a sensible epoch so time-gated checks have a deterministic base.
_clock: Dict[str, Any] = {"current_utc": "2025-01-01T00:00:00.000Z"}


def get_current_utc() -> str:
    return _clock["current_utc"]


def get_current_utc_dt() -> datetime:
    return parse_iso_dt(_clock["current_utc"])


def set_current_utc(iso: str) -> Dict[str, Any]:
    _clock["current_utc"] = iso
    return dict(_clock)


# ---- helpers ----------------------------------------------------------------

def parse_iso_dt(s: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 datetime (UTC aware). Accepts trailing 'Z' or +00:00.

    Returns None for None/empty. Raises ValueError on malformed input.
    """
    if s is None or s == "":
        return None
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def stamp_common(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Full quartet id/created_at/updated_at/version (PRD §2.4)."""
    ts = now_iso()
    obj.setdefault("id", new_uuid())
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    return obj


def stamp_immutable(obj: Dict[str, Any]) -> Dict[str, Any]:
    """For WageStatement — only id + created_at (PRD §2.4, append-only)."""
    obj.setdefault("id", new_uuid())
    obj["created_at"] = now_iso()
    return obj


def bump(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Refresh updated_at and increment version on a mutation (PRD §2.4)."""
    obj["updated_at"] = now_iso()
    obj["version"] = obj.get("version", 1) + 1
    return obj
