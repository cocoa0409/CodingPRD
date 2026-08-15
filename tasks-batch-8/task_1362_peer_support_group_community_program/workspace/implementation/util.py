"""Response envelope, time helpers, pagination, auth-context extraction."""
import random
import string
import uuid
from datetime import datetime, timezone

from flask import request

from db import db
from errors import (
    ApiError, raise_err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN,
    ERR_OWNERSHIP_MISMATCH, ERR_VALIDATION,
)

ROLES = ("ProgramAdmin", "Facilitator", "Participant", "ClinicalCoordinator")
ENTITY_BACKED = {"Facilitator": "facilitators", "Participant": "participants"}


# ---------- time ----------

def fmt_ts(dt):
    """ISO 8601 UTC with three fractional digits (entity/meta timestamps)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{dt.microsecond // 1000:03d}Z"


def fmt_clock(dt):
    """Canonical logical-clock rendering: Z suffix, fractional seconds only
    when non-zero (round-trips typical test inputs like 2026-08-15T10:00:00Z)."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        frac = f"{dt.microsecond:06d}".rstrip("0")
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + frac + "Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_dt(value, field="timestamp"):
    if not isinstance(value, str):
        raise_err(ERR_VALIDATION, f"{field} must be an ISO 8601 string")
    s = value.strip()
    try:
        if s.endswith(("Z", "z")):
            dt = datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(s)
    except ValueError:
        raise_err(ERR_VALIDATION, f"{field} is not a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------- envelope ----------

def _request_id():
    rand = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return f"req_{rand}"


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_ts(db.now()),
    }


def ok_object(payload, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": payload}
    return body, status


def ok_list(items, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return body, 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return body, err.http_status


# ---------- pagination ----------

def pagination_args():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(records):
    """records: list already sorted by (created_at, seq). Returns (body,status)."""
    records = sorted(records, key=lambda r: (r.get("_created_dt"), r.get("_seq", 0)))
    total = len(records)
    limit, offset = pagination_args()
    page = records[offset:offset + limit]
    return ok_list([serialize(r) for r in page], total, limit, offset)


# ---------- serialization ----------

def serialize(rec):
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        out[k] = v
    return out


# ---------- auth ----------

class Ctx:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Priority 1: header presence/well-formedness."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not isinstance(role, str) or role not in ROLES:
        raise_err(ERR_UNAUTHENTICATED, "Missing or malformed X-User-Role header")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise_err(ERR_UNAUTHENTICATED, "Missing or malformed X-User-ID header")
    return Ctx(user_id=user_id.strip(), role=role)


def authorize(ctx, allowed_roles):
    """Priority 2: role authorized for the endpoint. Priority 3: entity-backed
    identity must reference an existing entity of the backing type."""
    if ctx.role not in allowed_roles:
        raise_err(ERR_FORBIDDEN, "Role is not authorized for this endpoint")
    backing = ENTITY_BACKED.get(ctx.role)
    if backing is not None:
        if ctx.user_id not in getattr(db, backing):
            raise_err(
                ERR_OWNERSHIP_MISMATCH,
                f"X-User-ID does not match an existing {ctx.role} entity",
            )


def require_owner(condition):
    if not condition:
        raise_err(ERR_OWNERSHIP_MISMATCH, "X-User-ID does not match the resource owner")


def forbid():
    raise_err(ERR_FORBIDDEN, "Role is not authorized for this endpoint")


# ---------- request body ----------

def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise_err(ERR_VALIDATION, "Request body must be a JSON object")
    return data


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise_err(ERR_VALIDATION, f"Missing required field: {f}")


def require_enum(data, field, values):
    v = data.get(field)
    if v not in values:
        raise_err(ERR_VALIDATION, f"{field} must be one of {sorted(values)}")
    return v


def require_int(data, field, lo=None, hi=None):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err(ERR_VALIDATION, f"{field} must be an integer")
    if lo is not None and v < lo:
        raise_err(ERR_VALIDATION, f"{field} must be >= {lo}")
    if hi is not None and v > hi:
        raise_err(ERR_VALIDATION, f"{field} must be <= {hi}")
    return v


def new_id():
    return str(uuid.uuid4())
