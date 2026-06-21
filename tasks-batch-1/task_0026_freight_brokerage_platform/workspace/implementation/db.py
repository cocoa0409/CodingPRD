"""In-memory data store for the Freight Brokerage Platform.

Every store starts empty on each fresh boot. The test harness restarts the
server via start.sh before every test, so there is no carry-over state.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional


def new_uuid() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    """Wall-clock ISO 8601 UTC timestamp with three fractional digits.

    Used for created_at / updated_at / api_request_timestamp.
    Business-time comparisons use get_current_utc() (the logical clock).
    """
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_request_id() -> str:
    raw = uuid.uuid4().hex + uuid.uuid4().hex
    return "req_" + raw[:20]


# ---- entity stores (cleared at module load each fresh boot) -----------------

shippers: Dict[str, Dict[str, Any]] = {}
carriers: Dict[str, Dict[str, Any]] = {}
contract_rates: Dict[str, Dict[str, Any]] = {}
quote_requests: Dict[str, Dict[str, Any]] = {}
loads: Dict[str, Dict[str, Any]] = {}
accessorials: Dict[str, Dict[str, Any]] = {}
invoices: Dict[str, Dict[str, Any]] = {}
factoring_requests: Dict[str, Dict[str, Any]] = {}
dispute_claims: Dict[str, Dict[str, Any]] = {}
smartway_audits: Dict[str, Dict[str, Any]] = {}


# Logical clock (PRD §3.9). Defaults to a sensible epoch; tests overwrite via
# POST /freight/_clock/set_current_utc.
_clock: Dict[str, Any] = {"current_utc": "2025-01-01T00:00:00.000Z"}


def get_current_utc() -> str:
    return _clock["current_utc"]


def set_current_utc(iso: str) -> Dict[str, Any]:
    _clock["current_utc"] = iso
    return {"current_utc": _clock["current_utc"]}


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
    ts = now_iso()
    obj.setdefault("id", new_uuid())
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    return obj


def stamp_immutable(obj: Dict[str, Any]) -> Dict[str, Any]:
    """For Accessorial and SmartWayAudit — only id + created_at."""
    obj.setdefault("id", new_uuid())
    obj["created_at"] = now_iso()
    return obj


def bump(obj: Dict[str, Any]) -> Dict[str, Any]:
    obj["updated_at"] = now_iso()
    obj["version"] = obj.get("version", 1) + 1
    return obj
