"""Envelope, datetime, auth, body-validation, and pagination helpers."""

import json
import secrets
import string
from datetime import datetime, timezone

from flask import request, jsonify

import errors as E
from errors import ApiError

# The six operational roles plus the "Any" designation, which PRD section 2.1
# treats as a recognized role value whose X-User-ID is an opaque operator id
# and which is authorized for GET endpoints only.
ROLES = {
    "Surgeon",
    "SupplyChainAnalyst",
    "CartTechnician",
    "CirculatingNurse",
    "ValueAnalysisOfficer",
    "MaterialsManager",
    "Any",
}


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_dt(datetime.now(timezone.utc)),
    }


def success_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def success_list(items, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Datetimes
# ---------------------------------------------------------------------------

def fmt_dt(dt):
    """Render an aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value, field):
    if not isinstance(value, str):
        raise ApiError(E.ERR_INVALID_REQUEST,
                       f"Field '{field}' must be an ISO8601 datetime string", 400)
    v = value.strip()
    try:
        if v.endswith(("Z", "z")):
            dt = datetime.fromisoformat(v[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(v)
    except ValueError:
        raise ApiError(E.ERR_INVALID_REQUEST,
                       f"Field '{field}' is not a valid ISO8601 datetime", 400)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def utcnow():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def authenticate():
    """Priority-1 validation: identity headers present and role recognized."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if (
        uid is None
        or not isinstance(uid, str)
        or not uid.strip()
        or role is None
        or role not in ROLES
    ):
        raise ApiError(
            E.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must be present and the role recognized",
            400,
        )
    return uid.strip(), role


def authorize(role, allowed):
    """Priority-2 validation: role permitted for this endpoint."""
    if role not in allowed:
        raise ApiError(
            E.ERR_FORBIDDEN_FOR_ROLE,
            f"Role '{role}' is not permitted to invoke this endpoint",
            403,
        )


# ---------------------------------------------------------------------------
# Body parsing and field validation (priority 3)
# ---------------------------------------------------------------------------

def get_body():
    raw = request.get_data()
    if raw is None or raw == b"":
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        raise ApiError(E.ERR_INVALID_REQUEST, "Malformed JSON body", 400)
    if not isinstance(data, dict):
        raise ApiError(E.ERR_INVALID_REQUEST, "JSON body must be an object", 400)
    return data


def _bad(field, why):
    raise ApiError(E.ERR_INVALID_REQUEST, f"Field '{field}': {why}", 400)


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        _bad(field, "is required and must be a non-empty string")
    return v


def opt_str(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        _bad(field, "must be a string")
    return v


def req_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(field, "is required and must be an integer")
    return v


def opt_int(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(field, "must be an integer")
    return v


def opt_bool(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        _bad(field, "must be a boolean")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        _bad(field, f"is required and must be one of {sorted(allowed)}")
    return v


def req_dt(body, field):
    if field not in body or body.get(field) is None:
        _bad(field, "is required")
    return parse_dt(body.get(field), field)


def req_list(body, field):
    v = body.get(field)
    if not isinstance(v, list):
        _bad(field, "is required and must be an array")
    return v


# ---------------------------------------------------------------------------
# Pagination (PRD section 2.3: limit default 10, min 1, max 100; offset 0)
# ---------------------------------------------------------------------------

def pagination_params():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError(E.ERR_INVALID_REQUEST, "'limit' must be an integer", 400)
        if limit < 1 or limit > 100:
            raise ApiError(
                E.ERR_INVALID_REQUEST, "'limit' must be between 1 and 100", 400
            )
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError(E.ERR_INVALID_REQUEST, "'offset' must be an integer", 400)
        if offset < 0:
            raise ApiError(E.ERR_INVALID_REQUEST, "'offset' must be >= 0", 400)
    return limit, offset


def paginate(items, limit, offset, sort_key=None):
    """Default sort: created_at ASC (insertion sequence breaks ties)."""
    if sort_key is None:
        sort_key = lambda e: (e["created_at"], e["_seq"])
    ordered = sorted(items, key=sort_key)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


def apply_filters(items, filters):
    """filters: list of (query_param, entity_field). Equality match."""
    out = list(items)
    for param, field in filters:
        v = request.args.get(param)
        if v is not None:
            out = [e for e in out if _filter_value(e.get(field)) == v]
    return out


def _filter_value(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)
