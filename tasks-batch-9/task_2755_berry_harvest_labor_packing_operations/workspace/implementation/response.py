"""The PRD §2.2 response envelope, JSON rendering and pagination helpers."""

import json
from decimal import Decimal

from flask import Response, request

import config
import util
from errors import fail


def _default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError("not JSON serializable: %r" % (obj,))


def _render(payload, status):
    body = json.dumps(payload, default=_default)
    return Response(body, status=status, mimetype="application/json")


def _meta():
    return {
        "api_request_id": util.new_request_id(),
        "api_request_timestamp": util.instant_str(util.now_instant()),
    }


def public(record):
    """Strip private bookkeeping keys (anything starting with '_')."""
    if record is None:
        return None
    return {k: v for k, v in record.items() if not k.startswith("_")}


def object_response(record, status=200):
    return _render(
        {"meta": _meta(), "response_type": "object", "data": public(record)}, status
    )


def raw_object_response(data, status=200):
    return _render({"meta": _meta(), "response_type": "object", "data": data}, status)


def list_response(records, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = offset + len(records) < total_count
    return _render(
        {
            "meta": meta,
            "response_type": "array",
            "data": [public(r) for r in records],
        },
        200,
    )


def error_response(error_id, message, status):
    return _render(
        {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": error_id, "message": message},
        },
        status,
    )


# ---------------------------------------------------------------------------
# pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def _int_arg(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
    return -int(digits) if negative else int(digits)


def page_params():
    limit = _int_arg("limit", config.PAGE_LIMIT_DEFAULT)
    offset = _int_arg("offset", config.PAGE_OFFSET_DEFAULT)
    if limit < config.PAGE_LIMIT_MIN or limit > config.PAGE_LIMIT_MAX:
        fail("ERR_VALUE_OUT_OF_RANGE", "limit must be between 1 and 100.")
    if offset < 0:
        fail("ERR_VALUE_OUT_OF_RANGE", "offset may not be negative.")
    return limit, offset


def paginate(records):
    """Apply the standard offset/limit page to an already-ordered sequence."""
    limit, offset = page_params()
    total = len(records)
    page = records[offset : offset + limit]
    return list_response(page, limit, offset, total)
