"""Response envelope helpers (PRD 2.2, 2.3)."""
import random
import string

from flask import jsonify

import store

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return 'req_' + ''.join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {'api_request_id': request_id(),
            'api_request_timestamp': store.iso(store.now())}


def obj(data, code=200):
    return jsonify({'meta': _meta(), 'response_type': 'object',
                    'data': data if data is not None else {}}), code


def created(data):
    return obj(data, 201)


def arr(rows, limit, offset, total_count):
    meta = _meta()
    meta['limit'] = limit
    meta['offset'] = offset
    meta['total_count'] = total_count
    meta['has_more'] = (offset + len(rows)) < total_count
    return jsonify({'meta': meta, 'response_type': 'array', 'data': rows}), 200


def error(error_id, message, code):
    return jsonify({'meta': _meta(), 'response_type': 'error',
                    'data': {'error_id': error_id, 'message': message}}), code


def page(rows, serializer, limit, offset):
    """Apply the limit/offset window to already-sorted rows."""
    total = len(rows)
    window = rows[offset:offset + limit]
    return arr([serializer(r) for r in window], limit, offset, total)
