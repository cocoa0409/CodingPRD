"""Standard response envelope helpers (PRD section 2.2)."""
import secrets
import string

from flask import jsonify

from db import now_iso

_ALPHABET = string.ascii_letters + string.digits


def _request_id():
    return 'req_' + ''.join(secrets.choice(_ALPHABET) for _ in range(20))


def _meta():
    return {
        'api_request_id': _request_id(),
        'api_request_timestamp': now_iso(),
    }


def ok(data, status=200, response_type='object', pagination=None):
    meta = _meta()
    if pagination is not None:
        meta.update(pagination)
    body = {'meta': meta, 'response_type': response_type, 'data': data}
    return jsonify(body), status


def ok_list(items, pagination):
    return ok(items, status=200, response_type='array', pagination=pagination)


def err(error_id, status, message):
    body = {
        'meta': _meta(),
        'response_type': 'error',
        'data': {'error_id': error_id, 'message': message},
    }
    return jsonify(body), status
