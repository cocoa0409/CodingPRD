"""In-memory data store for the Family Court Divorce API.

Every store starts EMPTY on each fresh boot. The test harness restarts the
server via start.sh before every test, so there is no carry-over state and
NO entity is ever seeded at startup.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional


def new_uuid() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    """ISO-8601 UTC timestamp with exactly three fractional digits (PRD §2.2/§2.4)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_request_id() -> str:
    raw = uuid.uuid4().hex + uuid.uuid4().hex
    return "req_" + raw[:20]


# ---- entity stores (empty at module load on each fresh boot) ----------------
guideline_schedules: Dict[str, Dict[str, Any]] = {}
cases: Dict[str, Dict[str, Any]] = {}
parties: Dict[str, Dict[str, Any]] = {}
children: Dict[str, Dict[str, Any]] = {}
pleadings: Dict[str, Dict[str, Any]] = {}
financial_disclosures: Dict[str, Dict[str, Any]] = {}
parenting_plans: Dict[str, Dict[str, Any]] = {}
mediation_sessions: Dict[str, Dict[str, Any]] = {}
support_orders: Dict[str, Dict[str, Any]] = {}
court_orders: Dict[str, Dict[str, Any]] = {}
hearings: Dict[str, Dict[str, Any]] = {}

# Monotonic creation sequence so list endpoints can sort by creation order
# deterministically even when two resources share the same millisecond ts.
_seq: Dict[str, int] = {"n": 0}


def next_seq() -> int:
    _seq["n"] += 1
    return _seq["n"]


# ---- timestamp parsing ------------------------------------------------------
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


# ---- common-field helpers ---------------------------------------------------
def stamp_common(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Stamp id, created_at, updated_at, version (PRD §2.4) for full entities."""
    ts = now_iso()
    obj.setdefault("id", new_uuid())
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    obj["_seq"] = next_seq()
    return obj


def stamp_immutable(obj: Dict[str, Any]) -> Dict[str, Any]:
    """For GuidelineSchedule — only id + created_at (no updated_at / version)."""
    obj.setdefault("id", new_uuid())
    obj["created_at"] = now_iso()
    obj["_seq"] = next_seq()
    return obj


def bump(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Record a mutation: refresh updated_at and increment version (PRD §2.4)."""
    obj["updated_at"] = now_iso()
    obj["version"] = obj.get("version", 1) + 1
    return obj
