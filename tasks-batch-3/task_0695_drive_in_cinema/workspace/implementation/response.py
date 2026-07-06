"""Response envelope + pagination (PRD §2.2, §2.3; SCAFFOLD response_envelope).

Success:
  { "meta": { "api_request_id", "api_request_timestamp", [pagination] },
    "response_type": "object" | "array", "data": {} }
Error:
  { "meta": {...}, "response_type": "error",
    "data": { "error_id", "message" } }
"""
from datetime import datetime, timezone

from flask import jsonify

from util import new_request_id, iso_now
from errors import err, ERR_VALIDATION_LIMIT

# Pagination defaults (SCAFFOLD response_envelope.pagination_defaults / PRD §2.3).
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _meta(extra=None):
    # api_request_timestamp is a real server-generated wall-clock timestamp for
    # the response itself (PRD §2.2), independent of the logical domain clock.
    m = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso_now(datetime.now(timezone.utc)),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, status=201)


def ok_list(items, total_count, limit, offset):
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + len(items) < total_count,
        }),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def parse_pagination(args):
    """Parse and validate limit/offset query params (PRD §2.3).

    A limit outside [1,100] or a negative offset -> ERR_VALIDATION_LIMIT (422).
    """
    limit = DEFAULT_LIMIT
    offset = DEFAULT_OFFSET

    raw_limit = args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise err(ERR_VALIDATION_LIMIT, "limit must be an integer.")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise err(ERR_VALIDATION_LIMIT, "limit must be within [1,100].")

    raw_offset = args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise err(ERR_VALIDATION_LIMIT, "offset must be an integer.")
        if offset < 0:
            raise err(ERR_VALIDATION_LIMIT, "offset must not be negative.")

    return limit, offset


def paginate(rows):
    """Sort by creation order ascending, then return the page slice.

    rows: list of (entity_dict, _seq) tuples — _seq is the stable creation
    sequence stored on each entity. Returns the sorted full list of dicts.
    """
    rows = sorted(rows, key=lambda r: r["_seq"])
    return rows
