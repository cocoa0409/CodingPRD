"""Response envelope helpers — exact structure from the scaffold/PRD §2.2."""
import uuid
from flask import jsonify

import db


def _meta():
    return {
        'api_request_id': 'req_' + uuid.uuid4().hex[:24],
        'api_request_timestamp': db.iso(db.now()),
    }


def ok_object(data, status=200):
    body = {'meta': _meta(), 'response_type': 'object', 'data': data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta['limit'] = limit
    meta['offset'] = offset
    meta['total_count'] = total_count
    meta['has_more'] = (offset + len(items)) < total_count
    body = {'meta': meta, 'response_type': 'array', 'data': items}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        'meta': _meta(),
        'response_type': 'error',
        'data': {'error_id': error_id, 'message': message},
    }
