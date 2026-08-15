"""Response envelope helpers (PRD §2.2, §2.3).

Success: {"meta": {"api_request_id", "api_request_timestamp", [pagination]},
          "response_type": "object"|"array", "data": ...}
Error:   {"meta": {"api_request_id", "api_request_timestamp"},
          "response_type": "error", "data": {"error_id", "message"}}
Pagination fields in meta: limit, offset, total_count, has_more.
"""
import secrets
from flask import jsonify, request

from db import clock, fmt_ts
from errors import ApiError


def _meta(pagination=None):
    meta = {
        'api_request_id': 'req_' + secrets.token_hex(8),
        'api_request_timestamp': fmt_ts(clock.now()),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def ok(data, status=200, pagination=None):
    body = {
        'meta': _meta(pagination),
        'response_type': 'array' if isinstance(data, list) else 'object',
        'data': data,
    }
    return jsonify(body), status


def error_response(error_id, status, message):
    body = {
        'meta': _meta(),
        'response_type': 'error',
        'data': {'error_id': error_id, 'message': message},
    }
    return jsonify(body), status


def parse_pagination():
    """limit: default 10, min 1, max 100 (clamped). offset: default 0."""
    raw_limit = request.args.get('limit')
    raw_offset = request.args.get('offset')
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise ApiError('ERR_INVALID_REQUEST', 400, 'limit must be an integer')
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError('ERR_INVALID_REQUEST', 400, 'offset must be an integer')
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paginated_list(items):
    """Sort by creation order ascending, slice, and build pagination meta."""
    items = sorted(items, key=lambda e: e['_seq'])
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        'limit': limit,
        'offset': offset,
        'total_count': total,
        'has_more': (offset + len(page)) < total,
    }
    return page, pagination
