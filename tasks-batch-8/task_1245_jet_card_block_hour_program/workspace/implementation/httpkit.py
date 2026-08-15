"""HTTP plumbing: response envelope, errors, auth, body validation, pagination.

All structural names are taken from SCAFFOLD.yaml / PRD.md:
  success envelope: {"meta": {...}, "response_type": "object"|"array", "data": ...}
  error envelope:   {"meta": {...}, "response_type": "error",
                     "data": {"error_id": ..., "message": ...}}
  pagination:       limit / offset / total_count / has_more
                    defaults: limit=10, offset=0, min limit=1, max limit=100
  auth headers:     X-User-Role (Ops | Member | Anonymous), X-User-ID
"""

import random
import string
from functools import wraps

from flask import g, jsonify, request

from util import fmt_ts, parse_dt, wall_now_ts
from store import db


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_unauthenticated(msg="Missing or malformed X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_unauthorized(msg="Role not authorized for this endpoint"):
    return ApiError("ERR_UNAUTHORIZED", 403, msg)


def err_not_found(msg="Path-referenced resource does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_reference_not_found(msg="Body-referenced foreign key does not resolve"):
    return ApiError("ERR_REFERENCE_NOT_FOUND", 422, msg)


def err_invalid_request(msg="Schema violation, missing required field, or malformed value"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_invalid_state(msg="Entity in wrong from-state for invoked transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=18))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": wall_now_ts(),
    }
    if extra:
        m.update(extra)
    return m


def respond_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def respond_array(items, limit, offset, total_count):
    has_more = (offset + limit) < total_count
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    })
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def respond_error(api_error):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": api_error.error_id, "message": api_error.message},
    }
    return jsonify(body), api_error.http_status


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

RECOGNIZED_ROLES = {"Ops", "Member", "Anonymous"}


def authenticate():
    """Priority-1 auth check. Populates g.role and g.user_id."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in RECOGNIZED_ROLES:
        raise err_unauthenticated()
    if role == "Member" and (user_id is None or user_id == ""):
        # Member is entity_backed: the identifier header is required.
        raise err_unauthenticated()
    g.role = role
    g.user_id = user_id


def require_roles(*roles):
    """Priority-2 authorization check (endpoint-level role gate)."""
    if g.role not in roles:
        raise err_unauthorized()


def require_member_ownership(member_id):
    """Members may only touch resources owned by themselves."""
    if g.role == "Member" and g.user_id != member_id:
        raise err_unauthorized(
            "Members may only access resources they own")


# ---------------------------------------------------------------------------
# Request body validation
# ---------------------------------------------------------------------------

TYPE_CHECKERS = {}


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def _check_type(value, spec):
    t = spec["type"]
    if t == "string":
        return isinstance(value, str)
    if t == "integer":
        return _is_int(value)
    if t == "number":
        return _is_number(value)
    if t == "boolean":
        return isinstance(value, bool)
    if t == "datetime":
        return parse_dt(value) is not None
    if t == "enum":
        return isinstance(value, str) and value in spec["values"]
    return True


def get_body(fields):
    """Parse and validate a JSON object body against a field spec.

    fields: list of dicts {name, type, required, values?}
    Raises ERR_INVALID_REQUEST (400) on any schema violation, including
    unrecognized fields. Returns a dict of validated values (datetimes
    parsed, everything else verbatim).
    """
    raw = request.get_data()
    if raw is None or raw == b"":
        data = {}
    else:
        try:
            data = request.get_json(force=True, silent=False)
        except Exception:
            raise err_invalid_request("Request body is not valid JSON")
        if not isinstance(data, dict):
            raise err_invalid_request("Request body must be a JSON object")

    known = {f["name"]: f for f in fields}
    for key in data:
        if key not in known:
            raise err_invalid_request(f"Unrecognized field: {key}")

    out = {}
    for name, spec in known.items():
        if name not in data or data[name] is None:
            if spec.get("required"):
                raise err_invalid_request(f"Missing required field: {name}")
            out[name] = None
            continue
        value = data[name]
        if not _check_type(value, spec):
            raise err_invalid_request(f"Field {name} has an invalid value")
        if spec["type"] == "datetime":
            value = parse_dt(value)
        out[name] = value
    return out


def ensure_empty_body():
    """Action endpoints take no payload; an object with keys is a 400."""
    raw = request.get_data()
    if raw is None or raw == b"":
        return
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err_invalid_request("Request body is not valid JSON")
    if isinstance(data, dict) and len(data) == 0:
        return
    raise err_invalid_request("This endpoint does not accept a request body")


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_invalid_request("limit must be an integer")
        if str(raw_limit).strip() != str(limit) and not (
            raw_limit.strip().lstrip("+").isdigit()
        ):
            raise err_invalid_request("limit must be an integer")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise err_invalid_request(
                f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}")
    if raw_offset is None:
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_invalid_request("offset must be an integer")
        if not raw_offset.strip().lstrip("+").isdigit():
            raise err_invalid_request("offset must be an integer")
        if offset < 0:
            raise err_invalid_request("offset must be >= 0")
    return limit, offset


def sorted_items(iterable):
    """List results sort by created_at ascending; insertion seq breaks ties."""
    return sorted(iterable, key=lambda r: (r["created_at"], r.get("_seq", 0)))


def paginate(items):
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    return respond_array(page, limit, offset, total)
