"""HTTP layer: error catalogue, response envelope, auth, pagination, body helpers."""
import random
import string
from functools import wraps

from datetime import datetime, timezone
from flask import request, jsonify, g

from util import fmt_dt

ROLES = {"DistrictAdministrator", "CountyTreasurer", "ParcelOwner", "Auditor"}
ALL_ROLES = ["DistrictAdministrator", "CountyTreasurer", "ParcelOwner", "Auditor"]

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_VALIDATION": 422,
    "ERR_DISTRICT_NOT_FOUND": 404,
    "ERR_PARCEL_NOT_FOUND": 404,
    "ERR_ROLL_NOT_FOUND": 404,
    "ERR_BOND_NOT_FOUND": 404,
    "ERR_INSTALLMENT_NOT_FOUND": 404,
    "ERR_PAYMENT_NOT_FOUND": 404,
    "ERR_QUOTE_NOT_FOUND": 404,
    "ERR_FORECLOSURE_NOT_FOUND": 404,
    "ERR_STALE_PARCEL_VERSION": 412,
    "ERR_INVALID_DISTRICT_STATE": 409,
    "ERR_INVALID_PARCEL_STATE": 409,
    "ERR_INVALID_ROLL_STATE": 409,
    "ERR_INVALID_BOND_STATE": 409,
    "ERR_INSTALLMENT_NOT_PAYABLE": 409,
    "ERR_INVALID_QUOTE_STATE": 409,
    "ERR_INVALID_FORECLOSURE_STATE": 409,
    "ERR_DISTRICT_NOT_FORMED": 409,
    "ERR_NO_CONFIRMED_ROLL": 409,
    "ERR_APN_DUPLICATE": 409,
    "ERR_BENEFIT_UNITS_MISMATCH": 422,
    "ERR_INSTALLMENT_YEAR_CONFLICT": 409,
    "ERR_BOND_TERM_OVERLAP": 409,
    "ERR_FORECLOSURE_THRESHOLD_NOT_MET": 409,
    "ERR_QUOTE_DATE_INVALID": 422,
    "ERR_GRACE_NOT_ELAPSED": 409,
    "ERR_PAYMENT_AMOUNT_MISMATCH": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http = ERROR_STATUS.get(error_id, 400)
        self.message = message or error_id


def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta():
    return {
        "api_request_id": _req_id(),
        "api_request_timestamp": fmt_dt(datetime.now(timezone.utc)),
    }


def ok(data, status=200, response_type="object", meta_extra=None):
    meta = _meta()
    if meta_extra:
        meta.update(meta_extra)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def ok_list(items, meta_extra):
    return ok(items, status=200, response_type="array", meta_extra=meta_extra)


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def protected(allowed_roles):
    """Decorator: require valid auth headers and an allowed role."""
    allowed = set(allowed_roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or role not in ROLES:
                raise ApiError("ERR_UNAUTHENTICATED")
            if role not in allowed:
                raise ApiError("ERR_UNAUTHORIZED")
            g.uid = uid
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco


def owner_check(parcel_id):
    """For ParcelOwner-scoped writes: X-User-ID must equal the target parcel id."""
    if g.role == "ParcelOwner" and g.uid != parcel_id:
        raise ApiError("ERR_UNAUTHORIZED")


# ---------------------------------------------------------------------------
# Body / query helpers
# ---------------------------------------------------------------------------
def body_json():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "request body must be a JSON object")
    return data


def require(body, field):
    if field not in body or body[field] is None:
        raise ApiError("ERR_VALIDATION", "missing required field: %s" % field)
    return body[field]


def as_int(value, field, minimum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_VALIDATION", "%s must be an integer" % field)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_VALIDATION", "%s must be >= %s" % (field, minimum))
    return value


def as_number(value, field, minimum=None, minimum_exclusive=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError("ERR_VALIDATION", "%s must be a number" % field)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_VALIDATION", "%s must be >= %s" % (field, minimum))
    if minimum_exclusive is not None and value <= minimum_exclusive:
        raise ApiError("ERR_VALIDATION", "%s must be > %s" % (field, minimum_exclusive))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_VALIDATION", "%s must be <= %s" % (field, maximum))
    return value


def as_str(value, field):
    if not isinstance(value, str) or value == "":
        raise ApiError("ERR_VALIDATION", "%s must be a non-empty string" % field)
    return value


def as_enum(value, field, choices):
    if value not in choices:
        raise ApiError("ERR_VALIDATION", "%s must be one of %s" % (field, sorted(choices)))
    return value


def pagination(items):
    """Slice `items` per limit/offset query params; return (page, meta_extra)."""
    args = request.args
    limit = 10
    offset = 0
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except ValueError:
            raise ApiError("ERR_VALIDATION", "limit must be an integer")
        if limit < 1:
            raise ApiError("ERR_VALIDATION", "limit must be >= 1")
        if limit > 100:
            limit = 100
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except ValueError:
            raise ApiError("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", "offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta_extra
