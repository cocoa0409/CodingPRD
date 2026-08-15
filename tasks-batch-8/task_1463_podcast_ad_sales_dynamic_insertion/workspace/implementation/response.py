"""Standard response envelope helpers, matching the scaffold's envelope spec.

Success:
  { "meta": { "api_request_id": ..., "api_request_timestamp": ... },
    "response_type": "object" | "array", "data": ... }
List responses additionally carry limit/offset/total_count/has_more in meta.

Error:
  { "meta": { ... }, "response_type": "error",
    "data": { "error_id": ..., "message": ... } }
"""

from flask import jsonify

from helpers import new_request_id, now_timestamp

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _meta(extra=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_timestamp(),
    }
    if extra:
        meta.update(extra)
    return meta


def success_object(data, http_status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), http_status


def success_array(items, http_status=200, paginate=None):
    """Array envelope; `paginate` = (total_count, limit, offset) adds the
    pagination fields to meta (list endpoints only)."""
    extra = None
    if paginate is not None:
        total_count, limit, offset = paginate
        extra = {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        }
    body = {"meta": _meta(extra), "response_type": "array", "data": items}
    return jsonify(body), http_status


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def parse_pagination(args):
    """Parse limit/offset query params (defaults 10/0, limit in 1..100)."""
    from errors import err_invalid

    raw_limit = args.get("limit")
    raw_offset = args.get("offset")

    if raw_limit is None:
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_invalid("Query parameter 'limit' must be an integer")
        if isinstance(limit, bool) or limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise err_invalid(
                f"Query parameter 'limit' must be between {MIN_LIMIT} and {MAX_LIMIT}"
            )

    if raw_offset is None:
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_invalid("Query parameter 'offset' must be an integer")
        if isinstance(offset, bool) or offset < 0:
            raise err_invalid("Query parameter 'offset' must be >= 0")

    return limit, offset


def serialize(entity):
    """Strip internal keys (prefixed '_') from a stored record."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def list_response(all_items, args):
    """Sort by creation order (created_at ascending), paginate, emit envelope."""
    limit, offset = parse_pagination(args)
    ordered = sorted(all_items, key=lambda item: (item["_seq"],))
    total = len(ordered)
    page = ordered[offset : offset + limit]
    return success_array([serialize(item) for item in page], 200, (total, limit, offset))
