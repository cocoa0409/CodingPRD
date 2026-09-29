"""Response envelope helpers.

Success bodies carry ``meta`` / ``response_type`` / ``data``; error bodies carry
``meta`` / ``response_type`` = "error" / ``data`` = {error_id, message}.
"""
import random
import string

from db import commit, wall_stamp

_ID_ALPHABET = string.ascii_lowercase + string.digits


def request_id():
    return 'req_' + ''.join(random.choice(_ID_ALPHABET) for _ in range(24))


def _meta(extra=None):
    meta = {
        'api_request_id': request_id(),
        'api_request_timestamp': wall_stamp(),
    }
    if extra:
        meta.update(extra)
    return meta


def object_body(data):
    return {'meta': _meta(), 'response_type': 'object', 'data': data if data is not None else {}}


def array_body(items, limit, offset, total_count):
    extra = {
        'limit': limit,
        'offset': offset,
        'total_count': total_count,
        'has_more': (offset + len(items)) < total_count,
    }
    return {'meta': _meta(extra), 'response_type': 'array', 'data': items}


def error_body(error_id, message):
    return {
        'meta': _meta(),
        'response_type': 'error',
        'data': {'error_id': error_id, 'message': message},
    }


def entity(serializer, row, status=200):
    """Commit pending version bumps, then serialise the row."""
    commit()
    return object_body(serializer(row)), status


def payload(data, status=200):
    commit()
    return object_body(data), status


def collection(serializer, rows, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    return array_body([serializer(r) for r in page], limit, offset, total), 200
