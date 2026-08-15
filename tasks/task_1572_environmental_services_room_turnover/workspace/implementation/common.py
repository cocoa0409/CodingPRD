"""Shared helpers: errors, response envelope, time, auth, validation, pagination."""
import secrets
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

from store import store


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# ---------------------------------------------------------------- time helpers
def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + '%03dZ' % (dt.microsecond // 1000)


def parse_dt(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ApiError('ERR_INVALID_REQUEST',
                       'Field %s must be an ISO 8601 datetime string' % field, 400)
    text = value.strip()
    if text.endswith('Z') or text.endswith('z'):
        text = text[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise ApiError('ERR_INVALID_REQUEST',
                       'Field %s is not a valid ISO 8601 datetime' % field, 400)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def round2(value):
    return Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def round_int(value):
    return int(Decimal(value).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def new_id():
    return str(uuid.uuid4())


def now():
    return store.clock


# ------------------------------------------------------------------- envelope
def _meta():
    return {
        'api_request_id': 'req_' + ''.join(
            secrets.choice(string.ascii_letters + string.digits) for _ in range(20)),
        'api_request_timestamp': fmt_dt(datetime.now(timezone.utc)),
    }


def success_object(data, status=200):
    return jsonify({'meta': _meta(), 'response_type': 'object', 'data': data}), status


def success_list(items, limit, offset, total):
    m = _meta()
    m['limit'] = limit
    m['offset'] = offset
    m['total_count'] = total
    m['has_more'] = (offset + len(items)) < total
    return jsonify({'meta': m, 'response_type': 'array', 'data': items}), 200


def error_response(err):
    body = {'meta': _meta(), 'response_type': 'error',
            'data': {'error_id': err.error_id, 'message': err.message}}
    return jsonify(body), err.http_status


# ----------------------------------------------------------------------- auth
ROLES = ['EVSAdministrator', 'EVSDispatcher', 'EVSTechnician', 'QualityAuditor',
         'BedPlacementCoordinator', 'InfectionPreventionist', 'Any']
ENTITY_ROLE_CAPABILITY = {'EVSTechnician': 'CLEAN', 'QualityAuditor': 'AUDIT'}


class Ctx:
    def __init__(self, user_id, role, staff):
        self.user_id = user_id
        self.role = role
        self.staff = staff


def check_headers():
    uid = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if uid is None or not str(uid).strip() or role is None or not str(role).strip():
        raise ApiError('ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER',
                       'X-User-ID and X-User-Role headers must be present and non-empty', 400)


def authorize(allowed_roles):
    uid = request.headers.get('X-User-ID').strip()
    role = request.headers.get('X-User-Role').strip()
    if 'Any' in allowed_roles:
        if role not in ROLES:
            raise ApiError('ERR_INSUFFICIENT_PERMISSIONS',
                           'Role %s is not authorized for this endpoint' % role, 403)
    elif role not in allowed_roles:
        raise ApiError('ERR_INSUFFICIENT_PERMISSIONS',
                       'Role %s is not authorized for this endpoint' % role, 403)
    staff = None
    if role in ENTITY_ROLE_CAPABILITY:
        staff = store.staff.get(uid)
        if staff is None:
            raise ApiError('ERR_STAFF_NOT_FOUND',
                           'X-User-ID does not identify an existing staff member', 404)
        if ENTITY_ROLE_CAPABILITY[role] not in staff['capabilities']:
            raise ApiError('ERR_ROLE_CAPABILITY_MISMATCH',
                           'Staff member lacks the %s capability'
                           % ENTITY_ROLE_CAPABILITY[role], 403)
    return Ctx(uid, role, staff)


# -------------------------------------------------------------- body parsing
def json_body():
    raw = request.get_data()
    if raw is None or raw == b'':
        return {}
    data = request.get_json(silent=True, force=True)
    if data is None or not isinstance(data, dict):
        raise ApiError('ERR_INVALID_REQUEST', 'Request body must be a JSON object', 400)
    return data


def req_field(body, name):
    if name not in body or body[name] is None:
        raise ApiError('ERR_INVALID_REQUEST', 'Missing required field: %s' % name, 400)
    return body[name]


def opt_field(body, name, default=None):
    v = body.get(name, default)
    return default if v is None else v


def as_str(v, name):
    if not isinstance(v, str) or v == '':
        raise ApiError('ERR_INVALID_REQUEST',
                       'Field %s must be a non-empty string' % name, 400)
    return v


def as_int(v, name, min_value=None):
    if not isinstance(v, int) or isinstance(v, bool):
        raise ApiError('ERR_INVALID_REQUEST', 'Field %s must be an integer' % name, 400)
    if min_value is not None and v < min_value:
        raise ApiError('ERR_INVALID_REQUEST',
                       'Field %s must be >= %d' % (name, min_value), 400)
    return v


def as_enum(v, name, allowed):
    if not isinstance(v, str) or v not in allowed:
        raise ApiError('ERR_INVALID_REQUEST',
                       'Field %s must be one of %s' % (name, sorted(allowed)), 400)
    return v


def as_number(v, name):
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        raise ApiError('ERR_INVALID_REQUEST', 'Field %s must be a number' % name, 400)
    return Decimal(str(v))


def pagination_params():
    limit_raw = request.args.get('limit')
    offset_raw = request.args.get('offset')
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError('ERR_INVALID_REQUEST', 'limit must be an integer', 400)
        if limit < 1 or limit > 100:
            raise ApiError('ERR_INVALID_REQUEST', 'limit must be between 1 and 100', 400)
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError('ERR_INVALID_REQUEST', 'offset must be an integer', 400)
        if offset < 0:
            raise ApiError('ERR_INVALID_REQUEST', 'offset must be >= 0', 400)
    return limit, offset


def do_list(all_items, serializer, filter_fn=None):
    """Shape (pagination) before role (authorize) before filtering."""
    limit, offset = pagination_params()
    authorize(['Any'])
    items = [i for i in all_items if filter_fn is None or filter_fn(i)]
    items.sort(key=lambda e: (e['created_at'], e['_seq']))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serializer(i) for i in page], limit, offset, total)
