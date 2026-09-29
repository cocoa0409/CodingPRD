"""Response envelope helpers (PRD §2.2, §2.3)."""
import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import jsonify

from errors import fail

ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(ALNUM) for _ in range(20))


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def wall_now_iso():
    return iso(datetime.now(timezone.utc))


def jsonable(value):
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return iso(value)
    return value


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": wall_now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": jsonable(data if data is not None else {}),
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(items, limit, offset, total_count):
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + len(items) < total_count,
        }),
        "response_type": "array",
        "data": jsonable(items),
    }
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def paginate(args, records):
    """Apply limit/offset (default 10, min 1, max 100 / default 0)."""
    limit = args.get("limit", None)
    offset = args.get("offset", None)
    if limit is None or limit == "":
        limit_v = 10
    else:
        try:
            limit_v = int(str(limit))
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit_v < 1 or limit_v > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset is None or offset == "":
        offset_v = 0
    else:
        try:
            offset_v = int(str(offset))
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset_v < 0:
            fail("ERR_INVALID_REQUEST", "offset must be >= 0")
    total = len(records)
    return records[offset_v:offset_v + limit_v], limit_v, offset_v, total
