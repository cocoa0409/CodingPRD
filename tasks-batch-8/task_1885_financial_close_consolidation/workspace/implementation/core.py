"""Core infrastructure: in-memory store, logical clock, envelope, auth, errors.

Storage is in-memory only (Python dicts keyed by id). The store starts empty on
every boot; nothing is seeded, preloaded, or hardcoded.
"""
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, jsonify, request

bp = Blueprint("close_api", __name__)

ROLES = ("Controller", "Preparer", "Approver", "Auditor")

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
STORE = {
    "periods": {},
    "entities": {},
    "entity_periods": {},
    "tasks": {},
    "cutoffs": {},
    "accruals": {},
    "journal_entries": {},
    "je_lines": {},
    "documents": {},
    "reconciliations": {},
    "recon_items": {},
    "elim_pairs": {},
    "fluxes": {},
    "fx_rates": {},
    "events": {},
    "subledger_txns": {},
}

_SEQ = {"n": 0}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


# ---------------------------------------------------------------------------
# Logical clock (never falls back to wall clock before a set call)
# ---------------------------------------------------------------------------
CLOCK = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}


def logical_now():
    return CLOCK["now"]


# ---------------------------------------------------------------------------
# Wall-clock timestamps for bookkeeping fields (strictly increasing)
# ---------------------------------------------------------------------------
_WALL = {"last_ms": 0}


def wall_now():
    ms = int(time.time() * 1000)
    if ms <= _WALL["last_ms"]:
        ms = _WALL["last_ms"] + 1
    _WALL["last_ms"] = ms
    base = datetime.fromtimestamp(ms // 1000, tz=timezone.utc)
    return base.replace(microsecond=(ms % 1000) * 1000)


def fmt_ts(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


# ---------------------------------------------------------------------------
# Errors + envelope
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": fmt_ts(wall_now()),
    }


def ok(data, code=200, response_type="object", pagination=None):
    meta = _meta()
    if pagination is not None:
        meta.update(pagination)
    return jsonify({"meta": meta, "response_type": response_type, "data": data}), code


def ok_list(page, total, limit, offset):
    return ok(
        page,
        200,
        "array",
        {
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": offset + len(page) < total,
        },
    )


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.status


# ---------------------------------------------------------------------------
# Auth (headers per PRD §2.1)
# ---------------------------------------------------------------------------
def current_actor():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or role not in ROLES or not uid:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            401,
            "Missing or invalid X-User-Role / X-User-ID request headers",
        )
    return uid, role


def require_roles(*roles):
    uid, role = current_actor()
    if role not in roles:
        raise ApiError(
            "ERR_FORBIDDEN", 403, "Role %s is not permitted on this endpoint" % role
        )
    return uid


ALL_ROLES = ROLES

# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def page_params():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else 10
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", 400, "limit must be an integer")
    try:
        offset = int(offset_raw) if offset_raw is not None else 0
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", 400, "offset must be an integer")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def sorted_by_creation(records):
    return sorted(records, key=lambda r: (r["created_at"], r.get("_seq", 0)))


def paged(records):
    limit, offset = page_params()
    ordered = sorted_by_creation(list(records))
    total = len(ordered)
    return ordered[offset : offset + limit], total, limit, offset


def paged_response(records, serializer):
    page, total, limit, offset = paged(records)
    return ok_list([serializer(r) for r in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Decimal helpers (PRD §2.6: round half up; per-component rounding)
# ---------------------------------------------------------------------------
def dec(value):
    return Decimal(str(value))


def rhu(value):
    """Round half up to integer minor units."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu2(value):
    """Round half up to two decimal places (percentages)."""
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Record plumbing
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def base_record():
    ts = wall_now()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1,
            "_seq": next_seq()}


def bump(rec):
    rec["version"] += 1
    rec["updated_at"] = wall_now()


# ---------------------------------------------------------------------------
# Request body helpers
# ---------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 400, "Request body must be a JSON object")
    return data


def req(b, field):
    v = b.get(field)
    if v is None:
        raise ApiError("ERR_VALIDATION", 400, "%s is required" % field)
    return v


def req_int(b, field):
    v = req(b, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 400, "%s must be an integer" % field)
    return v


def req_str(b, field):
    v = req(b, field)
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 400, "%s must be a string" % field)
    return v


def req_enum(b, field, allowed):
    v = req(b, field)
    if v not in allowed:
        raise ApiError(
            "ERR_VALIDATION", 400, "%s must be one of %s" % (field, ", ".join(allowed))
        )
    return v


def req_num(b, field):
    v = req(b, field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", 400, "%s must be a number" % field)
    return v


def parse_ts(value, field):
    if not isinstance(value, str):
        raise ApiError(
            "ERR_VALIDATION", 400, "%s must be an ISO 8601 datetime string" % field
        )
    s = value.strip()
    try:
        if s.endswith(("Z", "z")):
            dt = datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError(
            "ERR_VALIDATION", 400, "%s is not a valid ISO 8601 datetime" % field
        )
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_ts(b, field):
    return parse_ts(req(b, field), field)
