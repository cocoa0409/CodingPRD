"""Standard response envelope (PRD 2.2) and pagination (PRD 2.3)."""
import secrets
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import ApiError, ERR_INVALID_REQUEST

_ALPHANUM = string.ascii_letters + string.digits

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(secrets.choice(_ALPHANUM) for _ in range(20))


def _wall_timestamp():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _wall_timestamp(),
    }


def success(data, code=200, pagination=None):
    """Build the success envelope. `pagination` adds limit/offset/total_count/has_more."""
    body = {
        "meta": _meta(),
        "response_type": "array" if pagination is not None else "object",
        "data": data,
    }
    if pagination is not None:
        body["meta"].update(pagination)
    return jsonify(body), code


def error_response(api_error):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": api_error.error_id,
            "message": api_error.message,
        },
    }
    return jsonify(body), api_error.http_status


def parse_pagination():
    """Parse and validate limit/offset query params per PRD 2.3."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    limit = DEFAULT_LIMIT
    offset = DEFAULT_OFFSET

    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if isinstance(limit, bool) or limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise ApiError(
                ERR_INVALID_REQUEST,
                400,
                "limit must be between %d and %d" % (MIN_LIMIT, MAX_LIMIT),
            )

    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be an integer")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be non-negative")

    return limit, offset


def paginated(items, serializer):
    """Sort by (created_at, insertion seq) ascending, paginate, build envelope."""
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda r: (r.get("created_at") or datetime.min.replace(tzinfo=timezone.utc), r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return success([serializer(r) for r in page], code=200, pagination=meta)
