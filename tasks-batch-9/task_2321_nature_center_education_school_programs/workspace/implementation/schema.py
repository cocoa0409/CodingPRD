"""Request-shape validation (PRD 2.9 step 4) and path/foreign-key resolution
(PRD 2.6, steps 6 and 7).  Every failure here is ERR_INVALID_REQUEST (400)
except identifier resolution, which yields the entity's own 404 code."""

from flask import request

from errors import ApiError
from store import db, parse_iso

_MISSING = object()


def bad():
    raise ApiError("ERR_INVALID_REQUEST")


def body_json():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        bad()
    if not isinstance(payload, dict):
        bad()
    return payload


def _present(body, name):
    return name in body and body[name] is not None


def req_str(body, name):
    if not _present(body, name):
        bad()
    value = body[name]
    if not isinstance(value, str) or not value.strip():
        bad()
    return value


def opt_str(body, name, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str):
        bad()
    return value


def opt_id(body, name):
    """Optional foreign-key style string; empty strings are rejected."""
    if not _present(body, name):
        return None
    value = body[name]
    if not isinstance(value, str) or not value.strip():
        bad()
    return value


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value):
    return (isinstance(value, int) or isinstance(value, float)) and not isinstance(value, bool)


def req_int(body, name, low=None, high=None):
    if not _present(body, name):
        bad()
    value = body[name]
    if not _is_int(value):
        bad()
    if low is not None and value < low:
        bad()
    if high is not None and value > high:
        bad()
    return value


def opt_int(body, name, low=None, high=None, default=None):
    if not _present(body, name):
        return default
    return req_int(body, name, low, high)


def req_num(body, name, low=None, high=None, exclusive_low=None):
    if not _present(body, name):
        bad()
    value = body[name]
    if not _is_num(value):
        bad()
    if low is not None and value < low:
        bad()
    if exclusive_low is not None and value <= exclusive_low:
        bad()
    if high is not None and value > high:
        bad()
    return value


def opt_num(body, name, low=None, high=None, exclusive_low=None, default=None):
    if not _present(body, name):
        return default
    return req_num(body, name, low, high, exclusive_low)


def req_bool(body, name):
    if not _present(body, name):
        bad()
    if not isinstance(body[name], bool):
        bad()
    return body[name]


def opt_bool(body, name, default=False):
    if not _present(body, name):
        return default
    if not isinstance(body[name], bool):
        bad()
    return body[name]


def req_enum(body, name, allowed):
    value = req_str(body, name)
    if value not in allowed:
        bad()
    return value


def opt_enum(body, name, allowed, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        bad()
    return value


def req_dt(body, name):
    value = req_str(body, name)
    parsed = parse_iso(value)
    if parsed is None:
        bad()
    return value, parsed


def opt_dt(body, name):
    if not _present(body, name):
        return None, None
    value = body[name]
    if not isinstance(value, str):
        bad()
    parsed = parse_iso(value)
    if parsed is None:
        bad()
    return value, parsed


def opt_str_array(body, name, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, list):
        bad()
    for item in value:
        if not isinstance(item, str):
            bad()
    return value


def req_str_array(body, name):
    if not _present(body, name):
        bad()
    return opt_str_array(body, name)


# --------------------------------------------------------------------------
# pagination + query filters
# --------------------------------------------------------------------------
def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            bad()
        if limit < 1 or limit > 100:
            bad()
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            bad()
        if offset < 0:
            bad()
    return limit, offset


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        bad()
    return value


def query_str(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def paginate(rows, limit, offset):
    return rows[offset:offset + limit], len(rows)


# --------------------------------------------------------------------------
# identifier resolution
# --------------------------------------------------------------------------
_LOOKUPS = (
    ("offering", "offerings", "ERR_OFFERING_NOT_FOUND"),
    ("material", "materials", "ERR_MATERIAL_NOT_FOUND"),
    ("school", "schools", "ERR_SCHOOL_NOT_FOUND"),
    ("educator", "educators", "ERR_EDUCATOR_NOT_FOUND"),
    ("training", "training", "ERR_TRAINING_RECORD_NOT_FOUND"),
    ("permit", "permits", "ERR_PERMIT_NOT_FOUND"),
    ("animal", "animals", "ERR_ANIMAL_NOT_FOUND"),
    ("trail", "trails", "ERR_TRAIL_SEGMENT_NOT_FOUND"),
    ("booking", "bookings", "ERR_BOOKING_NOT_FOUND"),
    ("fund", "funds", "ERR_FUND_NOT_FOUND"),
    ("aid", "aid", "ERR_AID_APPLICATION_NOT_FOUND"),
    ("manifest", "manifests", "ERR_MANIFEST_NOT_FOUND"),
    ("evaluation", "evaluations", "ERR_EVALUATION_REPORT_NOT_FOUND"),
)

_BY_KIND = {kind: (collection, code) for kind, collection, code in _LOOKUPS}


def lookup(kind, identifier):
    collection, code = _BY_KIND[kind]
    row = getattr(db, collection).get(identifier)
    if row is None:
        raise ApiError(code)
    return row


def find(kind, identifier):
    collection, _ = _BY_KIND[kind]
    return getattr(db, collection).get(identifier)
