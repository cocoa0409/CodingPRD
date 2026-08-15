"""Response envelope helpers — exact structure from scaffold response_envelope / PRD 2.2/2.3."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import raise_err, ERR_VALIDATION
from timeutil import fmt_ts

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _meta():
    return {
        "api_request_id": "req_" + "".join(
            random.choices(string.ascii_letters + string.digits, k=22)
        ),
        "api_request_timestamp": fmt_ts(datetime.now(timezone.utc)),
    }


def success_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def parse_pagination():
    """limit (default 10, min 1, max 100), offset (default 0). Violations -> ERR_VALIDATION."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = DEFAULT_LIMIT
    offset = DEFAULT_OFFSET
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err(ERR_VALIDATION, "limit must be an integer")
        if isinstance(limit, bool) or limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise_err(ERR_VALIDATION, f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err(ERR_VALIDATION, "offset must be an integer")
        if offset < 0:
            raise_err(ERR_VALIDATION, "offset must be >= 0")
    return limit, offset


def success_list(items):
    """items: full filtered+sorted list of serialized dicts; paginates here."""
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset : offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {"meta": meta, "response_type": "array", "data": page}
    return jsonify(body)


def error_body(error_id, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return body
