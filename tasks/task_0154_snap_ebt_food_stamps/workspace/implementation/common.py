"""Common helpers: response envelope, error class, store, clock, ids, time helpers."""

from __future__ import annotations

import random
import string
import threading
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from flask import jsonify, request, g


# -----------------------------------------------------------------------------
# Error class
# -----------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# -----------------------------------------------------------------------------
# Request id / timestamp / envelope
# -----------------------------------------------------------------------------

_ALPHANUM = string.ascii_uppercase + string.digits


def _gen_request_id() -> str:
    suffix = "".join(random.choices(_ALPHANUM, k=20))
    return f"req_{suffix}"


def now_iso_utc(dt: Optional[datetime] = None) -> str:
    """ISO 8601 UTC with three fractional digits (millisecond precision)."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    micros = dt.microsecond
    millis = micros // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def meta_block() -> Dict[str, Any]:
    rid = getattr(g, "_api_request_id", None)
    if rid is None:
        rid = _gen_request_id()
        g._api_request_id = rid
    ts = getattr(g, "_api_request_timestamp", None)
    if ts is None:
        ts = now_iso_utc()
        g._api_request_timestamp = ts
    return {"api_request_id": rid, "api_request_timestamp": ts}


def ok(data: Any, status_code: int = 200, *, pagination: Optional[Dict[str, Any]] = None):
    response_type = "array" if isinstance(data, list) else "object"
    meta = meta_block()
    if pagination is not None:
        meta = {**meta, **pagination}
    body = {"meta": meta, "response_type": response_type, "data": data if data is not None else {}}
    resp = jsonify(body)
    resp.status_code = status_code
    return resp


def err(error_id: str, http_status: int, message: str = ""):
    body = {
        "meta": meta_block(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message or error_id},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp


# -----------------------------------------------------------------------------
# Datetime parsing
# -----------------------------------------------------------------------------

def parse_iso8601(value: Any) -> datetime:
    """Parse ISO 8601 datetime string into UTC-aware datetime. Raises ApiError on failure."""
    if not isinstance(value, str) or not value:
        raise ApiError("ERR_VALIDATION", 400, "Invalid datetime value")
    s = value.strip()
    try:
        # Allow trailing Z and date-only formats
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s2)
        elif "T" in s:
            dt = datetime.fromisoformat(s)
        else:
            # date-only
            dt = datetime.fromisoformat(s + "T00:00:00+00:00")
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, "Invalid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


# -----------------------------------------------------------------------------
# Rounding
# -----------------------------------------------------------------------------

def round_half_up_int(value) -> int:
    d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2(value) -> float:
    d = Decimal(str(value))
    return float(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# -----------------------------------------------------------------------------
# ID generation
# -----------------------------------------------------------------------------

def gen_id() -> str:
    return str(uuid.uuid4())


def gen_last4() -> str:
    return "".join(random.choices(string.digits, k=4))


# -----------------------------------------------------------------------------
# Clock singleton
# -----------------------------------------------------------------------------

class Clock:
    """Global server clock. now is monotonic non-decreasing UTC datetime."""

    def __init__(self):
        self._now: datetime = datetime.now(timezone.utc)
        self._lock = threading.Lock()

    @property
    def now(self) -> datetime:
        with self._lock:
            return self._now

    def advance_to(self, target: datetime) -> datetime:
        with self._lock:
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
            else:
                target = target.astimezone(timezone.utc)
            if target >= self._now:
                self._now = target
            # else: monotonic — refuse to go backward, silently keep the larger value
            return self._now


# -----------------------------------------------------------------------------
# Store
# -----------------------------------------------------------------------------

class Store:
    """In-memory data store with a single big lock to enforce serialization."""

    def __init__(self):
        self.lock = threading.RLock()
        self.households: Dict[str, dict] = {}
        self.members: Dict[str, dict] = {}
        self.applications: Dict[str, dict] = {}
        self.cards: Dict[str, dict] = {}
        self.ledger: Dict[str, dict] = {}
        self.transactions: Dict[str, dict] = {}
        self.merchants: Dict[str, dict] = {}
        self.fraud_cases: Dict[str, dict] = {}
        self.waivers: Dict[str, dict] = {}
        self.emergency_allotments: Dict[str, dict] = {}
        self.case_number_seq = 0
        self.clock = Clock()
        # Track per-card list of waiver-suspended card ids for uphold-appeal restoration.
        # Stored on fraud-case as suspended_card_ids list (computed inline).


STORE = Store()


# -----------------------------------------------------------------------------
# Common system fields utilities
# -----------------------------------------------------------------------------

def system_fields_new() -> dict:
    """Return common fields for a new resource with common_fields=true."""
    ts = now_iso_utc(STORE.clock.now)
    return {"created_at": ts, "updated_at": ts, "version": 1}


def touch(entity: dict) -> None:
    """Refresh updated_at and bump version on an entity."""
    entity["updated_at"] = now_iso_utc(STORE.clock.now)
    entity["version"] = entity.get("version", 1) + 1


# -----------------------------------------------------------------------------
# Pagination helper
# -----------------------------------------------------------------------------

def parse_pagination():
    limit_raw = request.args.get("limit", "10")
    offset_raw = request.args.get("offset", "0")
    try:
        limit = int(limit_raw)
        offset = int(offset_raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", 400, "limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_VALIDATION", 400, "limit must be 1..100")
    if offset < 0:
        raise ApiError("ERR_VALIDATION", 400, "offset must be >= 0")
    return limit, offset


def paginate(rows: List[dict], limit: int, offset: int) -> (List[dict], Dict[str, Any]):
    # Sort by created_at ascending — caller usually does this already.
    total = len(rows)
    slice_ = rows[offset: offset + limit]
    has_more = (offset + limit) < total
    return slice_, {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}
