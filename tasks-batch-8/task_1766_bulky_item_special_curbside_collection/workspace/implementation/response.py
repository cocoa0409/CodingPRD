"""Standard response envelope helpers (SCAFFOLD response_envelope / PRD 2.2-2.3)."""
import uuid
from flask import jsonify, request

import db
from errors import ApiError, ERR_INVALID_REQUEST


def _meta(pagination=None):
    m = {
        'api_request_id': 'req_' + uuid.uuid4().hex[:20],
        'api_request_timestamp': db.fmt_ts3(db.wall_now()),
    }
    if pagination:
        m.update(pagination)
    return m


def ok(data, status=200):
    return jsonify({'meta': _meta(), 'response_type': 'object', 'data': data}), status


def ok_list(page, total, limit, offset):
    pag = {
        'limit': limit,
        'offset': offset,
        'total_count': total,
        'has_more': (offset + len(page)) < total,
    }
    return jsonify({'meta': _meta(pag), 'response_type': 'array', 'data': page}), 200


def err(error_id, message, status):
    body = {
        'meta': _meta(),
        'response_type': 'error',
        'data': {'error_id': error_id, 'message': message},
    }
    return jsonify(body), status


def pagination_args():
    """limit: default 10, min 1, max 100 (clamped); offset: default 0, min 0 (clamped)."""
    raw_limit = request.args.get('limit', None)
    raw_offset = request.args.get('offset', None)
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, 'limit must be an integer', 400)
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, 'offset must be an integer', 400)
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paginate(rows):
    """rows: full filtered+sorted list. Returns (page, total, limit, offset)."""
    limit, offset = pagination_args()
    total = len(rows)
    return rows[offset:offset + limit], total, limit, offset
