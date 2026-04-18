import uuid
from flask import jsonify
from utils.clock import clock


def make_request_id():
    return 'req_' + uuid.uuid4().hex[:20]


def success_response(data, status_code=200, response_type='object', pagination=None):
    meta = {
        'api_request_id': make_request_id(),
        'api_request_timestamp': clock.format(clock.now()),
    }
    if pagination:
        meta.update(pagination)
    body = {
        'meta': meta,
        'response_type': response_type,
        'data': data,
    }
    return jsonify(body), status_code


def error_response(error_id, message, status_code):
    body = {
        'meta': {
            'api_request_id': make_request_id(),
            'api_request_timestamp': clock.format(clock.now()),
        },
        'response_type': 'error',
        'data': {
            'error_id': error_id,
            'message': message,
        },
    }
    return jsonify(body), status_code


ERROR_MAP = {
    'ERR_AUTH_REQUIRED': 401,
    'ERR_FORBIDDEN': 403,
    'ERR_NOT_FOUND': 404,
    'ERR_INVALID_STATE': 409,
    'ERR_VERSION_CONFLICT': 409,
    'ERR_ORDER_ALREADY_ASSIGNED': 409,
    'ERR_DUPLICATE_RETURN': 409,
    'ERR_RESTAURANT_UNAVAILABLE': 422,
    'ERR_SUSPEND_CRITERIA_NOT_MET': 422,
    'ERR_RETURN_WINDOW_EXPIRED': 422,
    'ERR_REFUND_AMOUNT_INVALID': 422,
    'ERR_ORDER_INVALID': 422,
    'ERR_RELATED_RETURN_UNRESOLVED': 422,
    'ERR_VALIDATION': 422,
}


def err(error_id, message=''):
    return error_response(error_id, message, ERROR_MAP.get(error_id, 400))
