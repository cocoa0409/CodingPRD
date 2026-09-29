"""Standard response envelope (PRD 2.2) and pagination (PRD 2.3)."""
import json
import random
import string
from decimal import Decimal

from flask import Response

from clock import real_now_iso
from errors import api_error

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _encode(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError("Object of type %s is not JSON serializable" % type(obj).__name__)


def _dump(payload):
    return json.dumps(payload, default=_encode)


def base_meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": real_now_iso(),
    }


def envelope(data, response_type="object", status=200, pagination=None):
    meta = base_meta()
    if pagination:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return Response(_dump(body), status=status, mimetype="application/json")


def ok(data, status=200):
    return envelope(data, "object", status)


def created(data):
    return envelope(data, "object", 201)


def error_response(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return Response(_dump(body), status=status, mimetype="application/json")


def parse_pagination(args):
    """limit defaults 10 (min 1, max 100); offset defaults 0 (min 0)."""
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        limit = _as_int(raw, "limit")
        if limit < 1 or limit > 100:
            raise api_error("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        offset = _as_int(raw, "offset")
        if offset < 0:
            raise api_error("ERR_INVALID_REQUEST", "offset must be at least 0")
    return limit, offset


def _as_int(raw, name):
    if raw is None or raw == "":
        raise api_error("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    try:
        text = str(raw).strip()
        if text.startswith("+"):
            text = text[1:]
        neg = text.startswith("-")
        digits = text[1:] if neg else text
        if not digits.isdigit():
            raise ValueError(text)
        return int(text)
    except (TypeError, ValueError):
        raise api_error("ERR_INVALID_REQUEST", "%s must be an integer" % name)


def paginated(rows, limit, offset, serializer):
    total = len(rows)
    page = rows[offset:offset + limit]
    has_more = (offset + len(page)) < total
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return envelope([serializer(r) for r in page], "array", 200, pagination)
