import uuid

from flask import jsonify, request

import db
from errors import invalid
from util import fmt_dt


def _meta():
    return {
        'api_request_id': 'req_' + uuid.uuid4().hex[:20],
        'api_request_timestamp': fmt_dt(db.now()),
    }


def ok(data, status=200, response_type='object', pagination=None):
    meta = _meta()
    if pagination:
        meta.update(pagination)
    return jsonify({'meta': meta, 'response_type': response_type, 'data': data}), status


def err(error_id, message, status):
    return jsonify({
        'meta': _meta(),
        'response_type': 'error',
        'data': {'error_id': error_id, 'message': message},
    }), status


def pagination_params():
    raw_limit = request.args.get('limit')
    raw_offset = request.args.get('offset')
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid('limit must be an integer')
        if limit < 1 or limit > 100:
            raise invalid('limit must be between 1 and 100')
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid('offset must be an integer')
        if offset < 0:
            raise invalid('offset must be >= 0')
    return limit, offset


def ok_list(items, serializer=None, status=200):
    """Sort by created_at ascending (stable over insertion order), paginate, serialize."""
    items = sorted(items, key=lambda r: r['created_at'])
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    if serializer is not None:
        page = [serializer(r) for r in page]
    meta = {
        'limit': limit,
        'offset': offset,
        'total_count': total,
        'has_more': offset + len(page) < total,
    }
    return ok(page, status, 'array', meta)
