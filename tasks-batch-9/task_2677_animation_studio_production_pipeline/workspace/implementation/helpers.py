"""Response envelope, error type, authentication and schema validation helpers."""
import random
import re
import string
from decimal import Decimal, InvalidOperation

from flask import g, jsonify, request

from store import db, iso, now, parse_dt

PM = 'ProductionManager'
ARTIST = 'Artist'
SUPERVISOR = 'Supervisor'
DIRECTOR = 'Director'
COORDINATOR = 'OutsourceCoordinator'
PARTNER_REP = 'PartnerRepresentative'

ROLES = (PM, ARTIST, SUPERVISOR, DIRECTOR, COORDINATOR, PARTNER_REP)
ALL_READ = (PM, SUPERVISOR, DIRECTOR, ARTIST, COORDINATOR)
READ_WITH_PARTNER = (PM, SUPERVISOR, DIRECTOR, ARTIST, COORDINATOR, PARTNER_REP)

_ALNUM = string.ascii_uppercase + string.digits


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def validation_error(message=None):
    return ApiError('ERR_VALIDATION', 422, message)


def request_meta():
    return {
        'api_request_id': 'req_' + ''.join(random.choice(_ALNUM) for _ in range(20)),
        'api_request_timestamp': iso(now()),
    }


def success(data, status=200, response_type='object', pagination=None):
    meta = request_meta()
    if pagination:
        meta.update(pagination)
    body = {'meta': meta, 'response_type': response_type, 'data': data}
    return jsonify(body), status


def error_response(error_id, http_status, message):
    body = {
        'meta': request_meta(),
        'response_type': 'error',
        'data': {'error_id': error_id, 'message': message},
    }
    return jsonify(body), http_status


# --------------------------------------------------------------- authentication
def authenticate(allowed_roles):
    user_id = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if user_id is None or not str(user_id).strip():
        raise ApiError('ERR_UNAUTHENTICATED', 401, 'X-User-ID header is required')
    if role is None or not str(role).strip() or role not in ROLES:
        raise ApiError('ERR_UNAUTHENTICATED', 401, 'X-User-Role header must name a known role')
    if role not in allowed_roles:
        raise ApiError('ERR_UNAUTHORIZED', 403, 'role %s may not call this endpoint' % role)
    g.user_id = user_id
    g.role = role
    return user_id, role


# ------------------------------------------------------------------ body access
def body_json():
    cached = getattr(g, '_body_cache', None)
    if cached is not None:
        return cached
    raw = request.get_json(silent=True)
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise validation_error('request body must be a JSON object')
    g._body_cache = raw
    return raw


_MISSING = object()


def _present(body, key):
    return key in body and body[key] is not None


def get_str(body, key, required=True, default=None, min_len=None, max_len=None, pattern=None):
    if not _present(body, key):
        if required:
            raise validation_error('%s is required' % key)
        return default
    value = body[key]
    if not isinstance(value, str):
        raise validation_error('%s must be a string' % key)
    if min_len is not None and len(value) < min_len:
        raise validation_error('%s is too short' % key)
    if max_len is not None and len(value) > max_len:
        raise validation_error('%s is too long' % key)
    if pattern is not None and re.match(pattern, value) is None:
        raise validation_error('%s has an invalid format' % key)
    return value


def get_id(body, key, required=True):
    """Foreign-key shaped field: a non-empty string, used before schema checks."""
    if not _present(body, key):
        if required:
            return _MISSING
        return None
    value = body[key]
    if not isinstance(value, str) or not value.strip():
        return _MISSING
    return value


def get_int(body, key, required=True, default=None, minimum=None, maximum=None, choices=None):
    if not _present(body, key):
        if required:
            raise validation_error('%s is required' % key)
        return default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise validation_error('%s must be an integer' % key)
    if minimum is not None and value < minimum:
        raise validation_error('%s is below the allowed minimum' % key)
    if maximum is not None and value > maximum:
        raise validation_error('%s is above the allowed maximum' % key)
    if choices is not None and value not in choices:
        raise validation_error('%s is not an allowed value' % key)
    return value


def get_number(body, key, required=True, default=None, minimum=None, maximum=None,
               exclusive_min=None, places=2, choices=None):
    if not _present(body, key):
        if required:
            raise validation_error('%s is required' % key)
        return default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise validation_error('%s must be a number' % key)
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        raise validation_error('%s must be a number' % key)
    if minimum is not None and dec < Decimal(str(minimum)):
        raise validation_error('%s is below the allowed minimum' % key)
    if maximum is not None and dec > Decimal(str(maximum)):
        raise validation_error('%s is above the allowed maximum' % key)
    if exclusive_min is not None and dec <= Decimal(str(exclusive_min)):
        raise validation_error('%s must be greater than %s' % (key, exclusive_min))
    if choices is not None:
        allowed = [Decimal(str(c)) for c in choices]
        if dec not in allowed:
            raise validation_error('%s is not an allowed value' % key)
    if places is None:
        return float(dec)
    from calc import round_half_up
    return float(round_half_up(dec, places))


def get_bool(body, key, required=True, default=None):
    if not _present(body, key):
        if required:
            raise validation_error('%s is required' % key)
        return default
    value = body[key]
    if not isinstance(value, bool):
        raise validation_error('%s must be a boolean' % key)
    return value


def get_enum(body, key, allowed, required=True, default=None):
    if not _present(body, key):
        if required:
            raise validation_error('%s is required' % key)
        return default
    value = body[key]
    if not isinstance(value, str) or value not in allowed:
        raise validation_error('%s is not a legal value' % key)
    return value


def get_datetime(body, key, required=True, default=None):
    if not _present(body, key):
        if required:
            raise validation_error('%s is required' % key)
        return default
    parsed = parse_dt(body[key])
    if parsed is None:
        raise validation_error('%s must be an ISO 8601 timestamp' % key)
    return parsed


def get_str_array(body, key, required=True, default=None):
    if not _present(body, key):
        if required:
            raise validation_error('%s is required' % key)
        return default
    value = body[key]
    if not isinstance(value, list):
        raise validation_error('%s must be an array' % key)
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise validation_error('%s must contain only non-empty strings' % key)
    return value


# ------------------------------------------------------------------- pagination
def pagination_params():
    args = request.args
    limit = 10
    offset = 0
    if 'limit' in args and args.get('limit') != '':
        raw = args.get('limit')
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise validation_error('limit must be an integer')
        if limit < 1 or limit > 100:
            raise validation_error('limit must be between 1 and 100')
    if 'offset' in args and args.get('offset') != '':
        raw = args.get('offset')
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise validation_error('offset must be an integer')
        if offset < 0:
            raise validation_error('offset may not be negative')
    return limit, offset


def paginate(rows, serializer):
    limit, offset = pagination_params()
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = {
        'limit': limit,
        'offset': offset,
        'total_count': total,
        'has_more': (offset + len(page)) < total,
    }
    return success([serializer(r) for r in page], 200, 'array', meta)


def arg(name):
    value = request.args.get(name)
    if value is None or value == '':
        return None
    return value
