"""Response envelope helpers, timestamps, id minting."""

import random
import string
import uuid
from datetime import datetime, timezone

from flask import jsonify


def new_id():
    return str(uuid.uuid4())


def request_id():
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def iso_now():
    """Wall-clock timestamp for meta.api_request_timestamp (ISO 8601, 3 fractional digits, UTC)."""
    return _iso3(datetime.now(timezone.utc))


def _iso3(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    return f"{base}.{ms:03d}Z"


def iso3(dt):
    return _iso3(dt)


def meta(with_pagination=None):
    m = {
        "api_request_id": request_id(),
        "api_request_timestamp": iso_now(),
    }
    if with_pagination is not None:
        m.update(with_pagination)
    return m


def success_object(data, http_status=200):
    body = {
        "meta": meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), http_status


def success_list(items, total_count, limit, offset, http_status=200):
    has_more = (offset + len(items)) < total_count
    pag = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    body = {
        "meta": meta(with_pagination=pag),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), http_status


def error_response(error_id, http_status, message):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status


def parse_pagination(args):
    """limit: default 10, min 1, max 100. offset: default 0, min 0.
    Out-of-range or non-integer values are clamped/defaulted rather than errored.
    """
    limit_raw = args.get("limit", None)
    offset_raw = args.get("offset", None)
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            limit = 10
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            offset = 0
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
