"""Standard response envelope helpers (scaffold §1.0 / PRD §2.2-2.3)."""
import uuid

from flask import jsonify, request

from db import fmt_dt, now
from errors import ApiError


def _meta():
    return {
        'api_request_id': 'req_' + uuid.uuid4().hex[:20],
        'api_request_timestamp': fmt_dt(now()),
    }


def ok(data, status=200):
    return jsonify({'meta': _meta(), 'response_type': 'object', 'data': data}), status


def ok_list(items, total, limit, offset, status=200):
    meta = _meta()
    meta.update({
        'limit': limit,
        'offset': offset,
        'total_count': total,
        'has_more': offset + len(items) < total,
    })
    return jsonify({'meta': meta, 'response_type': 'array', 'data': items}), status


def error_response(error_id, status, message):
    return jsonify({
        'meta': _meta(),
        'response_type': 'error',
        'data': {'error_id': error_id, 'message': message},
    }), status


def parse_pagination():
    raw_limit = request.args.get('limit', None)
    raw_offset = request.args.get('offset', None)
    if raw_limit is None:
        limit = 10
    else:
        if not raw_limit.isdigit():
            raise ApiError('ERR_INVALID_REQUEST', 400,
                           'limit must be an integer between 1 and 100')
        limit = int(raw_limit)
        if limit < 1 or limit > 100:
            raise ApiError('ERR_INVALID_REQUEST', 400,
                           'limit must be between 1 and 100')
    if raw_offset is None:
        offset = 0
    else:
        if not raw_offset.isdigit():
            raise ApiError('ERR_INVALID_REQUEST', 400,
                           'offset must be a non-negative integer')
        offset = int(raw_offset)
    return limit, offset


def sort_rows(rows):
    """List results are sorted by created_at ascending (insertion order breaks
    ties, since the logical clock can produce identical timestamps)."""
    return sorted(rows, key=lambda r: (r['created_at'], r['_seq']))


def paginate(rows, serializer):
    limit, offset = parse_pagination()
    rows = sort_rows(rows)
    total = len(rows)
    page = [serializer(r) for r in rows[offset:offset + limit]]
    return ok_list(page, total, limit, offset)
