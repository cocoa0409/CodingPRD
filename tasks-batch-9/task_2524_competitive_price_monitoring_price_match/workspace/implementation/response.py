"""Standard response envelope (PRD section 2.2) and pagination (2.3)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify

from errors import err

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _request_timestamp():
    inst = datetime.now(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        inst.year, inst.month, inst.day, inst.hour, inst.minute, inst.second,
        inst.microsecond // 1000,
    )


def _meta():
    return {"api_request_id": _request_id(),
            "api_request_timestamp": _request_timestamp()}


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data or {}}
    return jsonify(body), status


def array_response(rows, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}
    return jsonify(body), status


# ------------------------------------------------------------- pagination

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _parse_page_int(raw, name):
    if raw is None:
        return None
    text = raw.strip() if isinstance(raw, str) else raw
    if isinstance(text, str):
        if text == "":
            raise err("ERR_INVALID_PAGINATION", "%s must be an integer." % name)
        try:
            return int(text, 10)
        except ValueError:
            raise err("ERR_INVALID_PAGINATION", "%s must be an integer." % name)
    if isinstance(text, bool) or not isinstance(text, int):
        raise err("ERR_INVALID_PAGINATION", "%s must be an integer." % name)
    return text


def pagination(args):
    """Return (limit, offset), enforcing the PRD 2.3 bounds."""
    limit = _parse_page_int(args.get("limit"), "limit")
    offset = _parse_page_int(args.get("offset"), "offset")
    if limit is None:
        limit = PAGE_LIMIT_DEFAULT
    elif limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
        raise err("ERR_INVALID_PAGINATION",
                  "limit must be an integer between 1 and 100.")
    if offset is None:
        offset = PAGE_OFFSET_DEFAULT
    elif offset < 0:
        raise err("ERR_INVALID_PAGINATION", "offset must be at least 0.")
    return limit, offset


def paginate(rows, limit, offset):
    return rows[offset:offset + limit]
