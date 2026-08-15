"""Response envelope helpers — structure fixed by scaffold section 1.0 / PRD 2.2."""
import uuid

from flask import jsonify

from store import store


def _meta(with_pagination=None):
    meta = {
        'api_request_id': 'req_' + uuid.uuid4().hex[:20],
        'api_request_timestamp': store.timestamp(),
    }
    if with_pagination:
        meta.update(with_pagination)
    return meta


def success_object(data, status=200):
    body = {'meta': _meta(), 'response_type': 'object', 'data': data}
    return jsonify(body), status


def success_list(items, total_count, limit, offset, status=200):
    page_meta = {
        'limit': limit,
        'offset': offset,
        'total_count': total_count,
        'has_more': (offset + len(items)) < total_count,
    }
    body = {'meta': _meta(page_meta), 'response_type': 'array', 'data': items}
    return jsonify(body), status


def error_body(error_id, message, status):
    body = {
        'meta': _meta(),
        'response_type': 'error',
        'data': {'error_id': error_id, 'message': message},
    }
    return jsonify(body), status
