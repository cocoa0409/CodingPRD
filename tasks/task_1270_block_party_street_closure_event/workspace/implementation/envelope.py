"""Response envelope helpers: success / list / error shapes and pagination.

Envelope per PRD section 2.2:
  success: {"meta": {api_request_id, api_request_timestamp[, pagination]},
            "response_type": "object"|"array", "data": ...}
  error:   {"meta": {api_request_id, api_request_timestamp},
            "response_type": "error", "data": {"error_id", "message"}}
"""
import uuid
from datetime import datetime, date

from flask import jsonify, request

from errors import ApiError
from store import tick, fmt, sort_key


def meta(pagination=None):
    m = {
        'api_request_id': 'req_' + uuid.uuid4().hex,
        'api_request_timestamp': fmt(tick()),
    }
    if pagination:
        m.update(pagination)
    return m


def _ser(v):
    if isinstance(v, datetime):
        return fmt(v)
    if isinstance(v, date):
        return v.isoformat()
    return v


def pub(e):
    """Serialize a stored resource: format datetimes/dates, drop internal keys."""
    return {k: _ser(v) for k, v in e.items() if not k.startswith('_')}


def ok(data, code=200):
    if isinstance(data, dict) and 'id' in data:
        payload = pub(data)
    else:
        payload = data
    return jsonify({'meta': meta(), 'response_type': 'object', 'data': payload}), code


def created(data):
    return ok(data, 201)


def parse_pagination():
    raw_limit = request.args.get('limit')
    raw_offset = request.args.get('offset')
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError('ERR_INVALID_REQUEST', 'limit must be an integer', 400)
        if limit < 1 or limit > 100:
            raise ApiError('ERR_INVALID_REQUEST', 'limit must be between 1 and 100', 400)
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError('ERR_INVALID_REQUEST', 'offset must be an integer', 400)
        if offset < 0:
            raise ApiError('ERR_INVALID_REQUEST', 'offset must be >= 0', 400)
    return limit, offset


def ok_list(items):
    """Sort by created_at ascending and paginate with limit/offset."""
    items = sorted(items, key=sort_key)
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    pag = {
        'limit': limit,
        'offset': offset,
        'total_count': total,
        'has_more': offset + len(page) < total,
    }
    return jsonify({
        'meta': meta(pag),
        'response_type': 'array',
        'data': [pub(i) for i in page],
    }), 200


def err_body(error_id, message):
    return jsonify({
        'meta': meta(),
        'response_type': 'error',
        'data': {'error_id': error_id, 'message': message},
    })
