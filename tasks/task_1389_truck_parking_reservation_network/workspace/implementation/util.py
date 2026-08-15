"""Response envelope, pagination, rounding, and request-body helpers."""
import random
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

import db
import errors


def _request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _request_ts():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def ok(data, status=200, pagination=None):
    """Standard success envelope. `pagination` adds list meta fields."""
    meta = {"api_request_id": _request_id(), "api_request_timestamp": _request_ts()}
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    body = {
        "meta": meta,
        "response_type": "array" if pagination is not None else "object",
        "data": data,
    }
    return jsonify(body), status


def err_resp(exc):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_ts(),
        },
        "response_type": "error",
        "data": {"error_id": exc.error_id, "message": exc.message},
    }
    return jsonify(body), exc.http_status


def paginate(items):
    """Apply limit/offset query params (defaults 10/0, bounds 1..100)."""
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }


def sort_created(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


# --------------------------------------------------------------------------
# Rounding
# --------------------------------------------------------------------------
def rhu_cents(value):
    """Round half up to integer cents. Accepts int/Decimal."""
    if not isinstance(value, Decimal):
        value = Decimal(value)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu_pct_2dp(value):
    """Round half up to two decimal places, returned as float."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# Body validation helpers
# --------------------------------------------------------------------------
def get_body(required=False):
    """Return the JSON body dict. Raises ERR_VALIDATION when required and absent."""
    data = request.get_json(silent=True)
    if data is None:
        if required:
            raise errors.validation("Request body must be a JSON object")
        return {}
    if not isinstance(data, dict):
        raise errors.validation("Request body must be a JSON object")
    return data


def req_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise errors.validation(f"Missing required field: {f}")


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_int(body, field):
    v = body.get(field)
    if not is_int(v):
        raise errors.validation(f"Field {field} must be an integer")
    return v


def opt_int(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    if not is_int(body[field]):
        raise errors.validation(f"Field {field} must be an integer")
    return body[field]


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise errors.validation(f"Field {field} must be a non-empty string")
    return v


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    if not isinstance(body[field], str):
        raise errors.validation(f"Field {field} must be a string")
    return body[field]


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise errors.validation(f"Field {field} must be one of {sorted(allowed)}")
    return v


def opt_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    return req_enum(body, field, allowed)


def opt_num(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    if not is_num(body[field]):
        raise errors.validation(f"Field {field} must be a number")
    return body[field]


def opt_bool(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    if not isinstance(body[field], bool):
        raise errors.validation(f"Field {field} must be a boolean")
    return body[field]
