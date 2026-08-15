"""Envelope, auth, pagination, and request-shape helpers (PRD §2)."""

import random
import re
import string
from datetime import datetime, timezone

from flask import jsonify, request

import db
from errors import (
    ApiError,
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_UNAUTHENTICATED,
    ERR_FORBIDDEN,
)

DECLARED_ROLES = {"FarmManager", "GateStaff", "FieldStaff", "KioskDevice", "Anonymous"}

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


# ---------------------------------------------------------------- envelope
def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=16))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.wall_ts(),
    }


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, total_count, limit, offset, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_body(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------- auth
def authenticate(public_endpoint=False):
    """PRD §2.1. Returns the acting role.

    public_endpoint=True is used only by POST /farm/waivers: the auth header
    check does not apply there, but authorization still does — any presented
    role other than Anonymous is ERR_FORBIDDEN.
    """
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if public_endpoint:
        if role is None or role == "":
            return "Anonymous"
        if role != "Anonymous":
            raise_err(ERR_FORBIDDEN, "Role is not authorized for this endpoint")
        return "Anonymous"
    if role is None or role == "" or role not in DECLARED_ROLES:
        raise_err(ERR_UNAUTHENTICATED, "Missing or unknown X-User-Role")
    if role != "Anonymous" and (uid is None or uid == ""):
        raise_err(ERR_UNAUTHENTICATED, "Missing X-User-ID")
    return role


def authorize(role, allowed):
    if role not in allowed:
        raise_err(ERR_FORBIDDEN, "Role is not authorized for this endpoint")


def require(allowed, public_endpoint=False):
    role = authenticate(public_endpoint=public_endpoint)
    authorize(role, allowed)
    return role


# ---------------------------------------------------------------- pagination
def pagination_params():
    limit_s = request.args.get("limit")
    offset_s = request.args.get("offset")
    if limit_s is None:
        limit = 10
    else:
        try:
            limit = int(limit_s)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
        if isinstance(limit, bool) or limit < 1 or limit > 100:
            raise_err(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset_s is None:
        offset = 0
    else:
        try:
            offset = int(offset_s)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(items, serializer):
    """items: pre-filtered list of entity dicts. Sorts created_at ASC and
    applies limit/offset, then wraps in the list envelope."""
    limit, offset = pagination_params()
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return ok_list([serializer(e) for e in page], total, limit, offset)


# ---------------------------------------------------------------- body shape
def get_body():
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def check_no_undeclared(body, allowed_fields):
    for key in body:
        if key not in allowed_fields:
            raise_err(ERR_INVALID_REQUEST, f"Undeclared field: {key}")


def req_str(body, field):
    v = body.get(field)
    if v is None:
        raise_err(ERR_INVALID_REQUEST, f"Missing required field: {field}")
    if not isinstance(v, str):
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must be a string")
    return v


def opt_str(body, field):
    v = body.get(field)
    if v is not None and not isinstance(v, str):
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must be a string")
    return v


def req_int(body, field, min_value=None):
    v = body.get(field)
    if v is None:
        raise_err(ERR_INVALID_REQUEST, f"Missing required field: {field}")
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must be an integer")
    if min_value is not None and v < min_value:
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must be >= {min_value}")
    return v


def opt_int(body, field, min_value=None):
    v = body.get(field)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must be an integer")
    if min_value is not None and v < min_value:
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must be >= {min_value}")
    return v


def req_enum(body, field, values):
    v = req_str(body, field)
    if v not in values:
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must be one of {sorted(values)}")
    return v


def req_date(body, field):
    v = req_str(body, field)
    if not DATE_RE.match(v):
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must be YYYY-MM-DD")
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, f"Field {field} is not a valid calendar date")
    return v


def req_time(body, field):
    v = req_str(body, field)
    if not TIME_RE.match(v):
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must be HH:MM (24h UTC)")
    return v


def req_str_list(body, field):
    v = body.get(field)
    if v is None:
        raise_err(ERR_INVALID_REQUEST, f"Missing required field: {field}")
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must be an array of strings")
    return v


# ---------------------------------------------------------------- rounding
def round_half_up_div(numerator, divisor):
    """round_half_up(numerator / divisor) for non-negative integers.
    floor((numerator*2 + divisor) / (2*divisor)) per scaffold §1.3."""
    return (2 * numerator + divisor) // (2 * divisor)


def ceil_div(a, b):
    return -(-a // b)
