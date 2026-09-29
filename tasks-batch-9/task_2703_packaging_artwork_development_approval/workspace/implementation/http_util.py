"""Response envelope (PRD 2.2), auth (PRD 2.1), pagination (PRD 2.3) and the
request-schema validators behind ERR_INVALID_REQUEST (PRD 2.10)."""
import re

from flask import jsonify, request

from core import db, parse_dt, request_id, wall_iso
from errors import ApiError, fail, invalid

ROLES = (
    "PackagingCoordinator",
    "BrandReviewer",
    "LegalReviewer",
    "RegulatoryReviewer",
    "QualityReviewer",
    "PrinterRep",
    "PlatformAdmin",
)

ALL_ROLES = list(ROLES)


# ------------------------------------------------------------------ envelope
def _meta(extra=None):
    meta = {"api_request_id": request_id(), "api_request_timestamp": wall_iso()}
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(items, pagination):
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ------------------------------------------------------------------ auth
def auth(allowed_roles):
    """PRD 2.1 / 2.7 band 1: header presence and role validity, then endpoint role membership."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip() or not role or role not in ROLES:
        fail("ERR_MISSING_AUTH_HEADERS", "X-User-ID and a valid X-User-Role header are required")
    if allowed_roles is not None and role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "role %s may not call this endpoint" % role)
    return user_id, role


# ------------------------------------------------------------------ pagination
def pagination():
    """PRD 2.3: limit defaults to 10 (1..100), offset defaults to 0 (>= 0)."""
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None or limit == "":
        limit_value = 10
    else:
        limit_value = _query_int("limit", limit)
        if limit_value < 1 or limit_value > 100:
            invalid("limit must be between 1 and 100")
    if offset is None or offset == "":
        offset_value = 0
    else:
        offset_value = _query_int("offset", offset)
        if offset_value < 0:
            invalid("offset must not be negative")
    return limit_value, offset_value


def _query_int(name, raw):
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        invalid("%s must be an integer" % name)


def query_int(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return _query_int(name, raw)


def query_bool(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    text = str(raw).strip().lower()
    if text in ("true", "1"):
        return True
    if text in ("false", "0"):
        return False
    invalid("%s must be a boolean" % name)


def paginate(items, serializer):
    limit, offset = pagination()
    total = len(items)
    window = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
    return ok_list([serializer(item) for item in window], meta)


# ------------------------------------------------------------------ body parsing
def raw_body():
    """The JSON body as a dict, without validating it (existence checks run first)."""
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        return body
    return {}


def body_fields(required, optional=()):
    """PRD 2.10: unknown fields, missing required fields -> ERR_INVALID_REQUEST."""
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        invalid("request body must be a JSON object")
    known = set(required) | set(optional)
    for key in body.keys():
        if key not in known:
            invalid("unknown field %s" % key)
    for key in required:
        if key not in body or body[key] is None:
            invalid("field %s is required" % key)
    return body


def opt_id(body, key):
    value = body.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


# ------------------------------------------------------------------ scalar validators
def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def need_string(body, key, min_len=None, max_len=None, pattern=None, required=True):
    if key not in body or body[key] is None:
        if required:
            invalid("field %s is required" % key)
        return None
    value = body[key]
    if not isinstance(value, str):
        invalid("field %s must be a string" % key)
    if min_len is not None and len(value) < min_len:
        invalid("field %s must be at least %d characters" % (key, min_len))
    if max_len is not None and len(value) > max_len:
        invalid("field %s must be at most %d characters" % (key, max_len))
    if pattern is not None and not re.match(pattern, value):
        invalid("field %s is malformed" % key)
    return value


def need_nonempty(body, key, required=True):
    if key not in body or body[key] is None:
        if required:
            invalid("field %s is required" % key)
        return None
    value = body[key]
    if not isinstance(value, str) or not value.strip():
        invalid("field %s must be a non-empty string" % key)
    return value


def need_enum(body, key, members, required=True):
    if key not in body or body[key] is None:
        if required:
            invalid("field %s is required" % key)
        return None
    value = body[key]
    if value not in members:
        invalid("field %s must be one of %s" % (key, ", ".join(sorted(members))))
    return value


def need_int(body, key, minimum=None, maximum=None, required=True):
    if key not in body or body[key] is None:
        if required:
            invalid("field %s is required" % key)
        return None
    value = body[key]
    if not is_int(value):
        invalid("field %s must be an integer" % key)
    if minimum is not None and value < minimum:
        invalid("field %s must be >= %s" % (key, minimum))
    if maximum is not None and value > maximum:
        invalid("field %s must be <= %s" % (key, maximum))
    return value


def need_number(body, key, minimum=None, maximum=None, required=True):
    if key not in body or body[key] is None:
        if required:
            invalid("field %s is required" % key)
        return None
    value = body[key]
    if not is_number(value):
        invalid("field %s must be a number" % key)
    if minimum is not None and value < minimum:
        invalid("field %s must be >= %s" % (key, minimum))
    if maximum is not None and value > maximum:
        invalid("field %s must be <= %s" % (key, maximum))
    return value


def need_bool(body, key, default=None, required=False):
    if key not in body or body[key] is None:
        if required:
            invalid("field %s is required" % key)
        return default
    value = body[key]
    if not isinstance(value, bool):
        invalid("field %s must be a boolean" % key)
    return value


def need_array(body, key, min_len=None, max_len=None, required=True, unique=False):
    if key not in body or body[key] is None:
        if required:
            invalid("field %s is required" % key)
        return None
    value = body[key]
    if not isinstance(value, list):
        invalid("field %s must be an array" % key)
    if min_len is not None and len(value) < min_len:
        invalid("field %s must hold at least %d entries" % (key, min_len))
    if max_len is not None and len(value) > max_len:
        invalid("field %s must hold at most %d entries" % (key, max_len))
    if unique and len(set(map(repr, value))) != len(value):
        invalid("field %s entries must be unique" % key)
    return value


def need_code_array(body, key, pattern, min_len, max_len, required=True, members=None):
    values = need_array(body, key, min_len, max_len, required=required, unique=True)
    if values is None:
        return None
    for entry in values:
        if not isinstance(entry, str):
            invalid("field %s entries must be strings" % key)
        if pattern is not None and not re.match(pattern, entry):
            invalid("field %s entry %s is malformed" % (key, entry))
        if members is not None and entry not in members:
            invalid("field %s entry %s is not a declared member" % (key, entry))
    return values


def need_datetime(body, key, required=True):
    if key not in body or body[key] is None:
        if required:
            invalid("field %s is required" % key)
        return None
    parsed = parse_dt(body[key])
    if parsed is None:
        invalid("field %s must be an ISO 8601 UTC datetime" % key)
    return parsed


def need_object(body, key, required=True):
    if key not in body or body[key] is None:
        if required:
            invalid("field %s is required" % key)
        return None
    value = body[key]
    if not isinstance(value, dict):
        invalid("field %s must be an object" % key)
    return value


# ------------------------------------------------------------------ lookups
_LOOKUPS = (
    ("briefs", "ERR_BRIEF_NOT_FOUND"),
    ("claims", "ERR_MARKETING_CLAIM_NOT_FOUND"),
    ("assets", "ERR_ARTWORK_ASSET_NOT_FOUND"),
    ("versions", "ERR_ARTWORK_VERSION_NOT_FOUND"),
    ("element_checks", "ERR_ELEMENT_CHECK_NOT_FOUND"),
    ("routes", "ERR_REVIEW_ROUTE_NOT_FOUND"),
    ("tasks", "ERR_REVIEW_TASK_NOT_FOUND"),
    ("printers", "ERR_PRINTER_NOT_FOUND"),
    ("proofs", "ERR_PRINTER_PROOF_NOT_FOUND"),
    ("plate_orders", "ERR_PLATE_ORDER_NOT_FOUND"),
    ("runouts", "ERR_INVENTORY_RUNOUT_NOT_FOUND"),
    ("escapes", "ERR_ERROR_ESCAPE_NOT_FOUND"),
)

_LOOKUP_ERRORS = dict(_LOOKUPS)


def load(collection, row_id):
    """Existence resolution (PRD 2.5): each collection has its own 404 code."""
    if not isinstance(row_id, str):
        fail(_LOOKUP_ERRORS[collection], "%s id is malformed" % collection)
    row = getattr(db, collection).get(row_id)
    if row is None:
        fail(_LOOKUP_ERRORS[collection], "no such %s: %s" % (collection, row_id))
    return row


def load_opt(collection, row_id):
    if row_id is None:
        return None
    return load(collection, row_id)


def filter_exists(collection, name):
    """Existence validation for an FK query filter (PRD 2.5)."""
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    load(collection, raw)
    return raw
