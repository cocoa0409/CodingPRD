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


def success_list(items, total_count, limit, offset):
    meta = _meta(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        }
    )
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def parse_pagination(args):
    """Parse limit/offset query params per the pagination defaults.

    Invalid values (non-integer, limit out of [1,100], negative offset) are
    rejected with ERR_VALIDATION (400).
    """
    from errors import err_validation

    raw_limit = args.get("limit")
    raw_offset = args.get("offset")

    if raw_limit is None:
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_validation("Query parameter 'limit' must be an integer")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise err_validation(
                f"Query parameter 'limit' must be between {MIN_LIMIT} and {MAX_LIMIT}"
            )

    if raw_offset is None:
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_validation("Query parameter 'offset' must be an integer")
        if offset < 0:
            raise err_validation("Query parameter 'offset' must be >= 0")

    return limit, offset


def list_response(all_items, args):
    """Sort by created_at ascending, apply pagination, emit list envelope."""
    limit, offset = parse_pagination(args)
    ordered = sorted(all_items, key=lambda item: (item["created_at"], item["id"]))
    total = len(ordered)
    page = ordered[offset : offset + limit]
    return success_list(page, total, limit, offset)
