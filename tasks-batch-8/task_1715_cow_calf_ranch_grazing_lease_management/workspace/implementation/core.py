"""Core foundation: logical clock, decimal rounding, store, errors, envelope, auth.

Everything structural (header names, envelope field names, pagination names,
error ids) is taken from the task's SCAFFOLD.yaml / PRD.md.
"""
from __future__ import annotations

import random
import string
import uuid
from datetime import datetime, timezone, date
from decimal import Decimal, ROUND_HALF_UP

from flask import request


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4): startup default 2026-08-01T00:00:00Z, never wall-clock.
# ---------------------------------------------------------------------------
class _LogicalClock:
    def __init__(self):
        self._dt = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def get(self) -> datetime:
        return self._dt

    def set(self, dt: datetime) -> None:
        self._dt = dt

    def current_date(self) -> date:
        return self._dt.date()


CLOCK = _LogicalClock()


# ---------------------------------------------------------------------------
# Decimal helpers (PRD §2.6): round-half-up everywhere, no banker's rounding.
# ---------------------------------------------------------------------------
D0 = Decimal("0")


def d2(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def d1(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def d4(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def dec(x) -> Decimal:
    return Decimal(str(x))


def num(x):
    """Convert Decimal -> JSON number: int if integral (no fractional part at
    the carried precision), else float. JSON numbers, never strings (PRD §2.6)."""
    if isinstance(x, Decimal):
        f = float(x)
        if f == int(f):
            return int(f)
        return f
    return x


# ---------------------------------------------------------------------------
# Timestamps / ids (PRD §2.5)
# ---------------------------------------------------------------------------
def wall_ts() -> str:
    """ISO 8601 UTC with three fractional digits, trailing Z."""
    now = datetime.now(timezone.utc)
    ms = now.microsecond // 1000
    return now.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=18))
    return "req_" + suffix


def parse_date(s) -> date:
    if isinstance(s, date) and not isinstance(s, datetime):
        return s
    if isinstance(s, datetime):
        return s.date()
    if not isinstance(s, str):
        raise ValueError("not a date string")
    t = s.strip()
    if "T" in t:
        t = t.split("T", 1)[0]
        # datetime-shaped input still accepted; date part governs
    return datetime.strptime(t, "%Y-%m-%d").date()


def parse_iso8601(s) -> datetime:
    if not isinstance(s, str):
        raise ValueError("not a datetime string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# In-memory store. Starts EMPTY on every boot (no seeding ever).
# ---------------------------------------------------------------------------
class DB:
    def __init__(self):
        self.ranches = {}
        self.pastures = {}
        self.grazing_leases = {}
        self.lease_statements = {}
        self.herd_groups = {}
        self.breeding_seasons = {}
        self.bulls = {}
        self.bull_turnouts = {}
        self.preg_checks = {}
        self.calf_crops = {}
        self.sale_lots = {}
        self.grazing_assignments = {}
        self.supplement_programs = {}
        self.drought_assessments = {}
        self.destock_orders = {}


db = DB()


# ---------------------------------------------------------------------------
# Errors (PRD §5 catalogue)
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def err_invalid_request(msg="Invalid request"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def err_invalid_state(msg="Invalid state transition"):
    return ApiError("ERR_INVALID_STATE_TRANSITION", msg, 400)


def err_already_terminal(msg="Resource is in a terminal state"):
    return ApiError("ERR_ALREADY_TERMINAL", msg, 400)


# ---------------------------------------------------------------------------
# Response envelope (SCAFFOLD response_envelope / PRD §2.2)
# ---------------------------------------------------------------------------
def success_envelope(data, response_type="object", status=200, pagination=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": wall_ts(),
    }
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    body = {"meta": meta, "response_type": response_type, "data": data}
    return body, status


def error_envelope(error_id: str, message: str, status: int):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": wall_ts(),
    }
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return body, status


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10 min 1 max 100; offset default 0;
# sort by created_at ascending.
# ---------------------------------------------------------------------------
def paginate(items: list):
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    items = sorted(items, key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    total = len(items)
    window = items[offset:offset + limit]
    has_more = (offset + limit) < total
    return window, {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}


# ---------------------------------------------------------------------------
# Auth (PRD §2.1): X-User-ID + X-User-Role; four roles.
# ---------------------------------------------------------------------------
ROLES = {"RanchManager", "RangeManager", "HerdManager", "SalesAgent"}
ALL_ROLES = ["RanchManager", "RangeManager", "HerdManager", "SalesAgent"]


class Ctx:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def require_ctx(allowed_roles):
    """Validation cascade priorities 1-2: headers then role authorization."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers are required and must name a declared role",
            400,
        )
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Role is not authorized for this endpoint", 403)
    return Ctx(user_id, role)


# ---------------------------------------------------------------------------
# Body validation helpers (priority 5: ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------
def get_body(required: bool = True) -> dict:
    body = request.get_json(silent=True)
    if body is None:
        if required:
            raise err_invalid_request("Request body must be a JSON object")
        return {}
    if not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return body


def check_allowed_fields(body: dict, allowed: set):
    for k in body.keys():
        if k not in allowed:
            raise err_invalid_request(f"Unknown or system-managed field supplied: {k}")


def req_field(body: dict, name: str):
    if name not in body or body[name] is None:
        raise err_invalid_request(f"Missing required field: {name}")
    return body[name]


def req_int(body: dict, name: str, positive: bool = False, nonneg: bool = False):
    v = req_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_request(f"Field {name} must be an integer")
    if positive and v <= 0:
        raise err_invalid_request(f"Field {name} must be positive")
    if nonneg and v < 0:
        raise err_invalid_request(f"Field {name} must be non-negative")
    return v


def opt_int(body: dict, name: str, default=None, positive: bool = False, nonneg: bool = False):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_request(f"Field {name} must be an integer")
    if positive and v <= 0:
        raise err_invalid_request(f"Field {name} must be positive")
    if nonneg and v < 0:
        raise err_invalid_request(f"Field {name} must be non-negative")
    return v


def req_number(body: dict, name: str, positive: bool = False, nonneg: bool = False):
    v = req_field(body, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_invalid_request(f"Field {name} must be a number")
    if positive and v <= 0:
        raise err_invalid_request(f"Field {name} must be positive")
    if nonneg and v < 0:
        raise err_invalid_request(f"Field {name} must be non-negative")
    return v


def opt_number(body: dict, name: str, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_invalid_request(f"Field {name} must be a number")
    return v


def req_str(body: dict, name: str):
    v = req_field(body, name)
    if not isinstance(v, str) or v == "":
        raise err_invalid_request(f"Field {name} must be a non-empty string")
    return v


def opt_str(body: dict, name: str, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, str):
        raise err_invalid_request(f"Field {name} must be a string")
    return v


def req_enum(body: dict, name: str, values):
    v = req_field(body, name)
    if v not in values:
        raise err_invalid_request(f"Field {name} must be one of {sorted(values)}")
    return v


def req_date(body: dict, name: str) -> date:
    v = req_field(body, name)
    try:
        return parse_date(v)
    except (ValueError, TypeError):
        raise err_invalid_request(f"Field {name} must be an ISO date (YYYY-MM-DD)")


def opt_date(body: dict, name: str, default=None):
    if name not in body or body[name] is None:
        return default
    try:
        return parse_date(body[name])
    except (ValueError, TypeError):
        raise err_invalid_request(f"Field {name} must be an ISO date (YYYY-MM-DD)")


def date_str(d) -> str:
    if d is None:
        return None
    if isinstance(d, datetime):
        d = d.date()
    return d.isoformat()


# ---------------------------------------------------------------------------
# Common record scaffolding (PRD §2.5)
# ---------------------------------------------------------------------------
def new_record() -> dict:
    ts = wall_ts()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def touch(rec: dict, bump_version: bool = True):
    rec["updated_at"] = wall_ts()
    if bump_version:
        rec["version"] = rec.get("version", 1) + 1
