from flask import jsonify

from util import new_request_id, fmt_ts, now


def meta_base():
    return {
        'api_request_id': new_request_id(),
        'api_request_timestamp': fmt_ts(now()),
    }


def ok(data, status=200):
    body = {'meta': meta_base(), 'response_type': 'object', 'data': data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    m = meta_base()
    m['limit'] = limit
    m['offset'] = offset
    m['total_count'] = total_count
    m['has_more'] = (offset + len(items)) < total_count
    return jsonify({'meta': m, 'response_type': 'array', 'data': items}), 200


def error_response(error_id, status, message):
    body = {
        'meta': meta_base(),
        'response_type': 'error',
        'data': {'error_id': error_id, 'message': message},
    }
    return jsonify(body), status
