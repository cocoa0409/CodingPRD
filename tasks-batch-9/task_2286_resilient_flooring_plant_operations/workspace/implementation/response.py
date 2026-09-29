"""Response envelope helpers (SCAFFOLD response_envelope / PRD 2.2, 2.3)."""

import random
import string
from datetime import datetime, timezone

from db import iso, ordered, serialize
from errors import ApiError

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

_ALPHABET = string.ascii_lowercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(16))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(datetime.now(timezone.utc)),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(data, status=200):
    return {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }, status


def list_response(rows, args, serializer=serialize):
    limit, offset = parse_pagination(args)
    rows = ordered(rows)
    total = len(rows)
    window = rows[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
    return {
        "meta": _meta(meta),
        "response_type": "array",
        "data": [serializer(r) for r in window],
    }, 200


def error_response(err):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }, err.http_status


def _as_int(raw):
    text = raw.strip()
    if text == "":
        raise ApiError("ERR_INVALID_REQUEST")
    negative = text.startswith("-")
    digits = text[1:] if negative or text.startswith("+") else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_REQUEST")
    return int(text)


def parse_pagination(args):
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    if "limit" in args:
        limit = _as_int(args.get("limit"))
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise ApiError("ERR_INVALID_REQUEST")
    if "offset" in args:
        offset = _as_int(args.get("offset"))
        if offset < PAGE_OFFSET_DEFAULT:
            raise ApiError("ERR_INVALID_REQUEST")
    return limit, offset


def enum_filter(args, name, allowed):
    """Read a query filter constrained to a declared vocabulary."""
    if name not in args:
        return None
    value = args.get(name)
    if value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST")
    return value


def string_filter(args, name):
    if name not in args:
        return None
    return args.get(name)
