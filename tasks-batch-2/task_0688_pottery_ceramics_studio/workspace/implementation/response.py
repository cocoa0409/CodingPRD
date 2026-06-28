"""Standard response envelope (SCAFFOLD §1.0, PRD §2.2).

Success:
  { "meta": { "api_request_id": "req_xxx", "api_request_timestamp": "ISO8601",
              <pagination fields on lists> },
    "response_type": "object" | "array", "data": {} }

Error:
  { "meta": { "api_request_id", "api_request_timestamp" },
    "response_type": "error",
    "data": { "error_id": "ERR_XXX", "message": "..." } }

Pagination fields: limit, offset, total_count, has_more (defaults limit=10,
min 1, max 100, offset=0).
"""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

# Pagination defaults (SCAFFOLD §1.0 pagination_defaults, PRD §2.3)
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _request_timestamp():
    # The envelope meta timestamp is the real server time of the response,
    # ISO 8601 UTC with three fractional digits (PRD §2.2).
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }


def success(data, status=200, response_type="object"):
    body = {
        "meta": _base_meta(),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def list_success(items, limit, offset, total_count, status=200):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error(error_id, message, status):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def parse_pagination(args):
    """Parse limit/offset from query args; raises ApiError(ERR_INVALID_REQUEST).

    limit defaults to 10, min 1, max 100. offset defaults to 0, min 0.
    """
    from errors import invalid_request

    limit = DEFAULT_LIMIT
    offset = DEFAULT_OFFSET

    if "limit" in args and args.get("limit") != "":
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            raise invalid_request("limit must be an integer")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise invalid_request("limit must be between 1 and 100")

    if "offset" in args and args.get("offset") != "":
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            raise invalid_request("offset must be an integer")
        if offset < 0:
            raise invalid_request("offset must be >= 0")

    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at ascending (tie-break on insertion seq), then slice."""
    ordered = sorted(records, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return window, total
