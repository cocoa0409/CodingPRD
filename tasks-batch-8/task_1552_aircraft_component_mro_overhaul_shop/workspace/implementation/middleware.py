"""Auth headers, role gating, request body validation, pagination."""
import re
from functools import wraps

from flask import request

from db import parse_dt
from errors import ApiError

ALL_ROLES = (
    "ShopManager",
    "CustomerServiceRep",
    "Technician",
    "Inspector",
    "PartsBuyer",
    "Customer",
)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def require_roles(*allowed):
    """Validation pipeline steps 1-2: auth headers, then role authorization."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if uid is None or uid == "" or role is None or role == "":
                raise ApiError(
                    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                    400,
                    "X-User-ID and X-User-Role headers must be present and non-empty",
                )
            if role not in ALL_ROLES or role not in allowed:
                raise ApiError(
                    "ERR_FORBIDDEN_ROLE", 403, "Role not permitted for this endpoint"
                )
            request.user_id = uid
            request.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco


def get_json_body(required=True):
    body = request.get_json(silent=True)
    if body is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be valid JSON")
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return body


def validate_body(body, spec):
    """spec: {name: (kind, required[, choices][, vmin, vmax])}.

    kinds: str, int, bool, enum, array_str, date, datetime.
    Unknown fields and type/enum/range violations -> ERR_INVALID_REQUEST.
    Returns a dict with every spec key (None for absent optional fields).
    """
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    for key in body:
        if key not in spec:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Unknown field: %s" % key)
    out = {}
    for name, rule in spec.items():
        kind = rule[0]
        required = rule[1] if len(rule) > 1 else False
        choices = rule[2] if len(rule) > 2 else None
        vmin = rule[3] if len(rule) > 3 else None
        vmax = rule[4] if len(rule) > 4 else None
        present = name in body and body[name] is not None
        if not present:
            if required:
                raise ApiError(
                    "ERR_INVALID_REQUEST", 400, "Missing required field: %s" % name
                )
            out[name] = None
            continue
        v = body[name]
        if kind == "str":
            if not isinstance(v, str):
                raise ApiError("ERR_INVALID_REQUEST", 400, "Field %s must be a string" % name)
        elif kind == "int":
            if not isinstance(v, int) or isinstance(v, bool):
                raise ApiError("ERR_INVALID_REQUEST", 400, "Field %s must be an integer" % name)
            if vmin is not None and v < vmin:
                raise ApiError("ERR_INVALID_REQUEST", 400, "Field %s below minimum" % name)
            if vmax is not None and v > vmax:
                raise ApiError("ERR_INVALID_REQUEST", 400, "Field %s above maximum" % name)
        elif kind == "bool":
            if not isinstance(v, bool):
                raise ApiError("ERR_INVALID_REQUEST", 400, "Field %s must be a boolean" % name)
        elif kind == "enum":
            if not isinstance(v, str) or v not in (choices or []):
                raise ApiError(
                    "ERR_INVALID_REQUEST", 400, "Field %s has an invalid value" % name
                )
        elif kind == "array_str":
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                raise ApiError(
                    "ERR_INVALID_REQUEST", 400, "Field %s must be an array of strings" % name
                )
        elif kind == "date":
            if not isinstance(v, str) or not _DATE_RE.match(v):
                raise ApiError(
                    "ERR_INVALID_REQUEST", 400, "Field %s must be a YYYY-MM-DD date" % name
                )
            try:
                from datetime import date as _date

                _date.fromisoformat(v)
            except ValueError:
                raise ApiError(
                    "ERR_INVALID_REQUEST", 400, "Field %s must be a valid date" % name
                )
        elif kind == "datetime":
            if not isinstance(v, str):
                raise ApiError(
                    "ERR_INVALID_REQUEST", 400, "Field %s must be an ISO 8601 datetime" % name
                )
            try:
                parse_dt(v)
            except (ValueError, TypeError):
                raise ApiError(
                    "ERR_INVALID_REQUEST", 400, "Field %s must be a valid datetime" % name
                )
        out[name] = v
    return out


def pagination_params():
    """limit (default 10, min 1, max 100), offset (default 0)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit, offset = 10, 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit out of range")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset out of range")
    return limit, offset
