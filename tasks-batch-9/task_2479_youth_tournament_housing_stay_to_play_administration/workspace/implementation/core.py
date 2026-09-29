"""Response envelope, auth middleware, schema validation and pagination.

Every structural name in this module is taken from PRD 2.1 / 2.2 / 2.3 and the
scaffold's `response_envelope` block: the headers are `X-User-ID` and
`X-User-Role`; the envelope is `meta` / `response_type` / `data`; the error body
is `error_id` / `message`; pagination uses `limit` / `offset` / `total_count` /
`has_more` with a default limit of 10 (min 1, max 100) and a default offset of 0.
"""

import functools
import json
from decimal import Decimal

from flask import g, jsonify, request

from errors import ApiError
from store import db, fmt_dt, new_request_id, now, now_iso, parse_date, parse_datetime

ROLES = (
    "HousingManager",
    "ExceptionReviewer",
    "RightsHolder",
    "TeamManager",
    "HotelRepresentative",
)

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

def _meta():
    return {"api_request_id": new_request_id(), "api_request_timestamp": now_iso()}


def _clean(value):
    """Serialise stored values: Decimal ratios render as JSON numbers."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return dict((k, _clean(v)) for k, v in value.items() if not k.startswith("_"))
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


def serialize(row):
    return _clean(row)


def object_response(row, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": serialize(row)}
    return jsonify(body), status


def array_response(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": [serialize(r) for r in rows]}
    return jsonify(body), 200


def error_response(error):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error.error_id, "message": error.message},
    }
    return jsonify(body), error.http_status


# ---------------------------------------------------------------------------
# Auth — ladder checks 1 to 4
# ---------------------------------------------------------------------------

def endpoint(roles):
    """Enforce ladder checks 1-4 before the view body runs."""

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            user_role = request.headers.get("X-User-Role")
            if not user_id or not user_id.strip() or not user_role or not user_role.strip():
                raise ApiError(
                    "ERR_MISSING_AUTH_HEADERS",
                    "Both X-User-ID and X-User-Role headers are required.",
                )
            if user_role not in ROLES:
                raise ApiError("ERR_UNKNOWN_ROLE", "Unknown role '%s'." % user_role)
            if user_role not in roles:
                raise ApiError(
                    "ERR_ROLE_NOT_PERMITTED",
                    "Role '%s' may not call this endpoint." % user_role,
                )
            if user_role == "TeamManager" and user_id not in db.teams:
                raise ApiError(
                    "ERR_ACTOR_IDENTITY_UNKNOWN",
                    "X-User-ID does not identify a known team.",
                )
            if user_role == "HotelRepresentative" and user_id not in db.hotels:
                raise ApiError(
                    "ERR_ACTOR_IDENTITY_UNKNOWN",
                    "X-User-ID does not identify a known hotel.",
                )
            g.user_id = user_id
            g.role = user_role
            g.bumped = set()
            return view(*args, **kwargs)

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Body parsing and schema validation — ladder check 9
# ---------------------------------------------------------------------------

def raw_body():
    data = request.get_data(cache=True)
    if data is None or not data.strip():
        return {}
    try:
        parsed = json.loads(data)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def field(kind, required=False, **extra):
    spec = {"kind": kind, "required": required}
    spec.update(extra)
    return spec


def _bad(name, detail):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (name, detail))


def _check_scalar(name, value, spec):
    kind = spec["kind"]
    if kind == "string":
        if not isinstance(value, str):
            _bad(name, "must be a string")
        if spec.get("non_empty") and not value.strip():
            _bad(name, "must be a non-empty string")
        return value
    if kind == "id":
        if not isinstance(value, str):
            _bad(name, "must be a string identifier")
        return value
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            _bad(name, "must be an integer")
        if "minimum" in spec and value < spec["minimum"]:
            _bad(name, "must be at least %s" % spec["minimum"])
        if "maximum" in spec and value > spec["maximum"]:
            _bad(name, "must be at most %s" % spec["maximum"])
        return value
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _bad(name, "must be a number")
        if "minimum" in spec and value < spec["minimum"]:
            _bad(name, "must be at least %s" % spec["minimum"])
        if "exclusive_minimum" in spec and value <= spec["exclusive_minimum"]:
            _bad(name, "must be greater than %s" % spec["exclusive_minimum"])
        if "maximum" in spec and value > spec["maximum"]:
            _bad(name, "must be at most %s" % spec["maximum"])
        return value
    if kind == "boolean":
        if not isinstance(value, bool):
            _bad(name, "must be a boolean")
        return value
    if kind == "date":
        if parse_date(value) is None:
            _bad(name, "must be an ISO 8601 calendar date (YYYY-MM-DD)")
        return value
    if kind == "datetime":
        if parse_datetime(value) is None:
            _bad(name, "must be a well-formed ISO 8601 datetime")
        return value
    if kind == "enum":
        if not isinstance(value, str) or value not in spec["members"]:
            _bad(name, "must be one of %s" % ", ".join(spec["members"]))
        return value
    raise ApiError("ERR_INVALID_REQUEST", "Unsupported field kind.")


def validate_body(body, schema):
    """Validate a request body against a field-name -> spec mapping."""
    for key in body:
        if key not in schema:
            raise ApiError("ERR_INVALID_REQUEST", "Unknown field '%s' in request body." % key)
    result = {}
    for name, spec in schema.items():
        if name not in body or body[name] is None:
            if spec.get("required"):
                raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
            result[name] = spec.get("default")
            continue
        value = body[name]
        if spec["kind"] == "entry_list":
            result[name] = _validate_entries(name, value, spec)
            continue
        result[name] = _check_scalar(name, value, spec)
    return result


ENTRY_SCHEMA = {
    "room_index": field("integer", required=True, minimum=1),
    "occupant_count": field("integer", required=True, minimum=1),
    "minor_occupant_count": field("integer", required=True, minimum=0),
    "chaperone_name": field("string"),
}


def _validate_entries(name, value, spec):
    if not isinstance(value, list):
        _bad(name, "must be an array")
    out = []
    for element in value:
        if not isinstance(element, dict):
            _bad(name, "must contain only objects")
        for key in element:
            if key not in ENTRY_SCHEMA:
                raise ApiError(
                    "ERR_INVALID_REQUEST",
                    "Unknown field '%s' in a rooming list entry." % key,
                )
        entry = {}
        for field_name, field_spec in ENTRY_SCHEMA.items():
            if field_name not in element or element[field_name] is None:
                if field_spec.get("required"):
                    raise ApiError(
                        "ERR_INVALID_REQUEST",
                        "Field '%s' is required on every rooming list entry." % field_name,
                    )
                entry[field_name] = None
                continue
            entry[field_name] = _check_scalar(field_name, element[field_name], field_spec)
        out.append(entry)
    return out


# ---------------------------------------------------------------------------
# Query parameters — pagination plus per-endpoint domain filters
# ---------------------------------------------------------------------------

def parse_pagination():
    args = request.args
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "Query parameter 'limit' must be between %d and %d."
                % (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT),
            )
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'offset' must be at least 0.")
    return limit, offset


def parse_filters(spec):
    """spec: filter name -> None (free string) or a tuple of enum members."""
    filters = {}
    for name, members in spec.items():
        if name not in request.args:
            continue
        value = request.args.get(name)
        if members is not None and value not in members:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "Query parameter '%s' must be one of %s." % (name, ", ".join(members)),
            )
        filters[name] = value
    return filters


def sort_key(row):
    return (row.get("created_at") or "", row.get("_seq") or 0)


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


def list_response(rows, filters=None, sorter=None):
    limit, offset = parse_pagination()
    ordered = sorted(rows, key=sorter or sort_key)
    page, total = paginate(ordered, limit, offset)
    return array_response(page, limit, offset, total)
