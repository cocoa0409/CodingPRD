"""In-memory data store for the Pt Rehab API.

Every store starts empty on each fresh boot. The test harness restarts the
server via start.sh before every test, so there is no carry-over state.
"""
from __future__ import annotations

import re
import threading
import uuid
from datetime import datetime, timezone, date
from typing import Any, Dict, Optional


# ---- ID + request helpers ---------------------------------------------------

def new_uuid() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    raw = uuid.uuid4().hex + uuid.uuid4().hex
    return "req_" + raw[:20]


# ---- timestamp helpers ------------------------------------------------------


def now_wall_iso() -> str:
    """Wall-clock ISO-8601 UTC with three fractional digits.

    Used for the response envelope's api_request_timestamp only.
    """
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_logical_iso() -> str:
    """Server logical-clock ISO-8601 UTC (3 fractional digits).

    Entity created_at and updated_at use the logical clock so that comparisons
    against logical-clock-derived deadlines stay consistent.
    """
    iso = get_current_utc()
    dt = parse_iso_dt(iso)
    if dt is None:
        return now_wall_iso()
    return iso_format(dt)


def iso_format(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso_dt(s: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 datetime, returning a tz-aware UTC datetime.

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


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_iso_date(s: Optional[str]) -> Optional[date]:
    """Parse a strict YYYY-MM-DD calendar date. None for None/empty.

    Raises ValueError on malformed input.
    """
    if s is None or s == "":
        return None
    if not isinstance(s, str) or not _DATE_RE.match(s):
        raise ValueError("invalid date")
    return date.fromisoformat(s)


# ---- entity stores (cleared at module load each fresh boot) ----------------

patients: Dict[str, Dict[str, Any]] = {}
therapists: Dict[str, Dict[str, Any]] = {}
veteran_referrals: Dict[str, Dict[str, Any]] = {}
plans_of_care: Dict[str, Dict[str, Any]] = {}
evaluations: Dict[str, Dict[str, Any]] = {}
authorization_grants: Dict[str, Dict[str, Any]] = {}
visits: Dict[str, Dict[str, Any]] = {}
home_exercise_programs: Dict[str, Dict[str, Any]] = {}
mips_measures: Dict[str, Dict[str, Any]] = {}
discharge_assessments: Dict[str, Dict[str, Any]] = {}


# Logical clock (PRD §2.10). Initialised to a sensible epoch; tests overwrite
# via POST /_clock/set_current_utc.
_clock: Dict[str, Any] = {"current_utc": "2025-01-01T00:00:00.000Z"}


def get_current_utc() -> str:
    return _clock["current_utc"]


def set_current_utc(iso: str) -> str:
    _clock["current_utc"] = iso
    return iso


# Global mutation lock — every API mutation runs under this lock to make the
# request stream serializable, which keeps cascade side-effects, version bumps
# and computed-field re-aggregation observably atomic.
mutation_lock = threading.RLock()


# ---- common-field stamping helpers ------------------------------------------


def stamp_common(obj: Dict[str, Any]) -> Dict[str, Any]:
    ts = now_logical_iso()
    obj.setdefault("id", new_uuid())
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    return obj


def bump(obj: Dict[str, Any]) -> Dict[str, Any]:
    obj["updated_at"] = now_logical_iso()
    obj["version"] = obj.get("version", 1) + 1
    return obj


# Stable sort key used for deterministic order across multiple aggregation
# calculations (units_consumed_running, units_finalized_running,
# cumulative_billed).
def created_then_id(v: Dict[str, Any]):
    return (v.get("created_at", ""), v.get("id", ""))
