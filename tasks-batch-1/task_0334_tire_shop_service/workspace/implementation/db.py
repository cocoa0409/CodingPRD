"""In-memory data store for the Tire Shop & Service API.

Every store starts empty on each fresh boot. The test harness restarts the
server via start.sh before every test, so there is no carry-over state. No
entity is seeded at startup — every row a test needs is created through the
declared API surface.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional


# ---- ID + request helpers ---------------------------------------------------

def new_uuid() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    raw = uuid.uuid4().hex + uuid.uuid4().hex
    return "req_" + raw[:20]


# ---- timestamp helpers ------------------------------------------------------


def now_iso() -> str:
    """Wall-clock ISO 8601 UTC with three fractional digits (PRD §2.4)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso_dt(s: Optional[str]) -> Optional[datetime]:
    """Parse an ISO 8601 datetime, returning a tz-aware UTC datetime.

    Accepts trailing 'Z' or explicit offset. Returns None for None / empty.
    Raises ValueError on malformed input.
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


# ---- entity stores (cleared at module load each fresh boot) ----------------

customers: Dict[str, Dict[str, Any]] = {}
vehicles: Dict[str, Dict[str, Any]] = {}
tire_models: Dict[str, Dict[str, Any]] = {}
fitment_rules: Dict[str, Dict[str, Any]] = {}
service_bays: Dict[str, Dict[str, Any]] = {}
work_orders: Dict[str, Dict[str, Any]] = {}
work_order_lines: Dict[str, Dict[str, Any]] = {}
road_hazard_warranties: Dict[str, Dict[str, Any]] = {}
appointments: Dict[str, Dict[str, Any]] = {}
special_orders: Dict[str, Dict[str, Any]] = {}
mileage_claims: Dict[str, Dict[str, Any]] = {}


# Global mutation lock — every API mutation runs under this lock to make the
# request stream serializable, which keeps cascade side-effects, version bumps
# and computed-field re-aggregation observably atomic.
mutation_lock = threading.RLock()


# Monotone creation sequence — used as a tiebreaker for default list ordering so
# that resources created within the same millisecond still sort deterministically
# by creation order.
_seq_counter = 0


def next_seq() -> int:
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


# ---- common-field stamping helpers ------------------------------------------


def stamp_common(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Full audit triad (PRD §2.4): id, created_at, updated_at, version=1."""
    ts = now_iso()
    obj.setdefault("id", new_uuid())
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    obj["_seq"] = next_seq()
    return obj


def stamp_immutable(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Immutable junction (FitmentRule, PRD §2.4): id + created_at only."""
    ts = now_iso()
    obj.setdefault("id", new_uuid())
    obj["created_at"] = ts
    obj["_seq"] = next_seq()
    return obj


def touch(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Refresh updated_at without bumping version."""
    obj["updated_at"] = now_iso()
    return obj


def bump(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Refresh updated_at and increment version by one (PRD §2.8)."""
    obj["updated_at"] = now_iso()
    obj["version"] = obj.get("version", 1) + 1
    return obj


def created_then_seq(v: Dict[str, Any]):
    """Stable sort key used for default list ordering (PRD §2.3)."""
    return (v.get("created_at", ""), v.get("_seq", 0))


def public(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Strip internal-only keys (those prefixed with '_') from a record."""
    return {k: val for k, val in obj.items() if not k.startswith("_")}
