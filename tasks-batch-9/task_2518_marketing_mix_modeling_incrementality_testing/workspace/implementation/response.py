"""Response envelope helpers (PRD section 2.2) and list pagination (PRD section 2.3)."""

import random
import string
from datetime import date, datetime, timezone
from decimal import Decimal

from flask import jsonify

from errors import ApiError

_ALNUM = string.ascii_uppercase + string.digits

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _request_timestamp():
    dt = datetime.now(timezone.utc)
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


def base_meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": _request_timestamp()}


def scrub(value):
    """Strip private keys and render Decimal/date values in wire form."""
    if isinstance(value, dict):
        out = {}
        for key, val in value.items():
            if isinstance(key, str) and key.startswith("_"):
                continue
            out[key] = scrub(val)
        return out
    if isinstance(value, (list, tuple)):
        return [scrub(v) for v in value]
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return "%s.%03dZ" % (value.strftime("%Y-%m-%dT%H:%M:%S"), value.microsecond // 1000)
    if isinstance(value, date):
        return value.isoformat()
    return value


def ok(data, status=200):
    body = {"meta": base_meta(), "response_type": "object", "data": scrub(data)}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(rows, limit, offset, total_count):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": [scrub(r) for r in rows]}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# ------------------------------------------------------------- pagination

def _int_param(args, name, default, minimum, maximum):
    raw = args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    if not text:
        return default
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    value = int(text)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be at most %d." % (name, maximum))
    return value


def page_params(args):
    limit = _int_param(args, "limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _int_param(args, "offset", OFFSET_DEFAULT, 0, None)
    return limit, offset


def paginate(rows, args):
    limit, offset = page_params(args)
    total = len(rows)
    return rows[offset:offset + limit], limit, offset, total


def listing(rows, args):
    page, limit, offset, total = paginate(rows, args)
    return ok_list(page, limit, offset, total)
