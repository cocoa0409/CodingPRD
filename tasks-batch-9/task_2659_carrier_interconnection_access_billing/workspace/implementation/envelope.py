"""Response envelope (PRD 2.2) and pagination (PRD 2.3)."""
import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import jsonify

from errors import ApiError

ALNUM = string.ascii_uppercase + string.digits

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0
PAGE_OFFSET_MIN = 0


def request_id():
    return "req_" + "".join(random.choice(ALNUM) for _ in range(20))


def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def _wall_now():
    return datetime.now(timezone.utc)


def base_meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": iso_ms(_wall_now()),
    }


def encode(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return iso_ms(value)
    if isinstance(value, dict):
        return {k: encode(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [encode(v) for v in value]
    return value


def object_response(data, status=200):
    body = {
        "meta": base_meta(),
        "response_type": "object",
        "data": encode(data) if data is not None else {},
    }
    return jsonify(body), status


def empty_response(status=200):
    return object_response({}, status)


def list_response(rows, limit, offset, total_count, status=200):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": encode(list(rows)),
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _int_param(args, name, default, minimum, maximum):
    raw = args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(str(raw), 10)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "%s below minimum" % name)
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "%s above maximum" % name)
    return value


def pagination(args):
    limit = _int_param(args, "limit", PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MIN, PAGE_LIMIT_MAX)
    offset = _int_param(args, "offset", PAGE_OFFSET_DEFAULT, PAGE_OFFSET_MIN, None)
    return limit, offset


def paginate(rows, args, serializer):
    limit, offset = pagination(args)
    total = len(rows)
    page = rows[offset:offset + limit]
    return list_response([serializer(r) for r in page], limit, offset, total)
