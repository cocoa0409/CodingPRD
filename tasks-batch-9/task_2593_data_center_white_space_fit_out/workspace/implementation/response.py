"""Response envelope helpers (PRD 2.2) and pagination (PRD 2.3)."""

import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import jsonify, request

from errors import ApiError

_ALNUM = string.ascii_uppercase + string.digits

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def iso_now():
    """Wall-clock instant for the envelope / row bookkeeping stamps."""
    return format_dt(datetime.now(timezone.utc))


def format_dt(dt):
    if dt is None:
        return None
    echo = getattr(dt, "raw", None)
    if echo:
        # A supplied or clock-set instant is echoed back exactly as it was given.
        return echo
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def base_meta():
    return {"api_request_id": new_request_id(), "api_request_timestamp": iso_now()}


def jsonify_value(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return format_dt(value)
    if isinstance(value, dict):
        return {k: jsonify_value(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [jsonify_value(v) for v in value]
    return value


def object_response(data, status=200):
    body = {
        "meta": base_meta(),
        "response_type": "object",
        "data": jsonify_value(data),
    }
    return jsonify(body), status


def created_response(data):
    return object_response(data, 201)


def array_response(rows, limit, offset, total_count):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": jsonify_value(rows),
    }
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _positive_int(raw, name):
    try:
        if isinstance(raw, str):
            raw = raw.strip()
        value = int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", "%s must be an integer." % name)
    if str(raw).strip() != str(value):
        # tolerate leading zeros / plus signs but reject junk such as "1.5"
        try:
            if float(raw) != float(value):
                raise ApiError("ERR_VALIDATION", "%s must be an integer." % name)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "%s must be an integer." % name)
    return value


def read_pagination():
    """limit/offset with page_size/page aliases; limit and offset win (PRD 2.3)."""
    args = request.args
    limit = None
    if "limit" in args:
        limit = _positive_int(args.get("limit"), "limit")
    elif "page_size" in args:
        limit = _positive_int(args.get("page_size"), "page_size")
    if limit is None:
        limit = LIMIT_DEFAULT
    if limit < LIMIT_MIN or limit > LIMIT_MAX:
        raise ApiError(
            "ERR_VALIDATION",
            "limit must be between %d and %d." % (LIMIT_MIN, LIMIT_MAX),
        )

    offset = None
    if "offset" in args:
        offset = _positive_int(args.get("offset"), "offset")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", "offset may not be negative.")
    elif "page" in args:
        page = _positive_int(args.get("page"), "page")
        if page < 1:
            raise ApiError("ERR_VALIDATION", "page is one-based.")
        offset = (page - 1) * limit
    if offset is None:
        offset = OFFSET_DEFAULT
    return limit, offset


def paginate(rows):
    """Sort by created_at ascending, slice, and emit the array envelope."""
    limit, offset = read_pagination()
    ordered = sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))
    total = len(ordered)
    page_rows = ordered[offset:offset + limit]
    return array_response(page_rows, limit, offset, total)
