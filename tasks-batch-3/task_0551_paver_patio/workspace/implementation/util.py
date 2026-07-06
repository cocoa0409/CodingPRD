"""Cross-cutting helpers: errors, response envelope, validation, auth, math."""

import random
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

from store import db, new_id, next_seq, now_iso, iso_millis

# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------
ROLES = {'PlatformAdmin', 'DesignConsultant', 'ProjectManager', 'Client'}


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# ---------------------------------------------------------------------------
def gen_request_id():
    return 'req_' + ''.join(random.choices(string.ascii_letters + string.digits, k=20))


def build_meta(extra=None):
    m = {'api_request_id': gen_request_id(), 'api_request_timestamp': now_iso()}
    if extra:
        m.update(extra)
    return m


def envelope(data, response_type, pagination=None):
    return {'meta': build_meta(pagination), 'response_type': response_type, 'data': data}


def ok(data, response_type='object', code=200, pagination=None):
    return jsonify(envelope(data, response_type, pagination)), code


# ---------------------------------------------------------------------------
# Money / number helpers (PRD 2.6)
# ---------------------------------------------------------------------------
def D(x):
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def rhu(value):
    """Round half up to the nearest whole cent, returning an int."""
    return int(D(value).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def num_out(value):
    """Serialize a numeric value as int when integral, else float."""
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    return value


# ---------------------------------------------------------------------------
# ISO parsing (logical clock + date fields)
# ---------------------------------------------------------------------------
def parse_iso(s):
    if not isinstance(s, str):
        raise ValueError('not a string')
    t = s.strip()
    if t.endswith('Z') or t.endswith('z'):
        t = t[:-1] + '+00:00'
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Request body validation (produces ERR_INVALID_REQUEST / 422)
# ---------------------------------------------------------------------------
def _bad(msg):
    raise ApiError('ERR_INVALID_REQUEST', 422, msg)


def get_body():
    b = request.get_json(silent=True)
    if b is None:
        b = {}
    if not isinstance(b, dict):
        _bad('Request body must be a JSON object')
    return b


def _present(body, field):
    return field in body and body[field] is not None


def v_str(body, field, required=True, default=None):
    if not _present(body, field):
        if required:
            _bad('Missing required field: %s' % field)
        return default
    v = body[field]
    if not isinstance(v, str):
        _bad('%s must be a string' % field)
    return v


def v_bool(body, field, required=False, default=None):
    if not _present(body, field):
        if required:
            _bad('Missing required field: %s' % field)
        return default
    v = body[field]
    if not isinstance(v, bool):
        _bad('%s must be a boolean' % field)
    return v


def v_int(body, field, required=True, default=None, minimum=None, positive=False):
    if not _present(body, field):
        if required:
            _bad('Missing required field: %s' % field)
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        _bad('%s must be an integer' % field)
    if positive and v <= 0:
        _bad('%s must be positive' % field)
    if minimum is not None and v < minimum:
        _bad('%s below minimum' % field)
    return v


def v_num(body, field, required=True, default=None, minimum=None, positive=False, lt=None):
    if not _present(body, field):
        if required:
            _bad('Missing required field: %s' % field)
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad('%s must be a number' % field)
    if positive and not v > 0:
        _bad('%s must be positive' % field)
    if minimum is not None and v < minimum:
        _bad('%s below minimum' % field)
    if lt is not None and not v < lt:
        _bad('%s must be less than %s' % (field, lt))
    return v


def v_enum(body, field, choices, required=True, default=None):
    if not _present(body, field):
        if required:
            _bad('Missing required field: %s' % field)
        return default
    v = body[field]
    if v not in choices:
        _bad('%s is not a valid value' % field)
    return v


def v_date(body, field, required=True, default=None):
    s = v_str(body, field, required=required, default=None)
    if s is None:
        return default
    try:
        datetime.strptime(s, '%Y-%m-%d')
    except (ValueError, TypeError):
        _bad('%s must be a YYYY-MM-DD date' % field)
    return s


def v_list(body, field, required=True, default=None):
    if not _present(body, field):
        if required:
            _bad('Missing required field: %s' % field)
        return default if default is not None else []
    v = body[field]
    if not isinstance(v, list):
        _bad('%s must be an array' % field)
    return v


# ---------------------------------------------------------------------------
# Auth / RBAC (PRD 2.1, 2.5)
# ---------------------------------------------------------------------------
def authorize(allowed_roles):
    user_id = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if not user_id or not role:
        raise ApiError('ERR_UNAUTHENTICATED', 401, 'Missing X-User-ID or X-User-Role')
    if role not in allowed_roles:
        raise ApiError('ERR_UNAUTHORIZED', 403, 'Role not permitted for this operation')
    return user_id, role


def check_owner(project, user_id):
    if project['customer_id'] != user_id:
        raise ApiError('ERR_NOT_PROJECT_OWNER', 403, 'Caller does not own this project')


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------
def base_record(kind, fields):
    ts = now_iso()
    rec = {
        'id': new_id(),
        'created_at': ts,
        'updated_at': ts,
        'version': 1,
        '_kind': kind,
        '_seq': next_seq(),
    }
    rec.update(fields)
    return rec


def touch(rec):
    rec['updated_at'] = now_iso()
    rec['version'] += 1


def count_active_bookings(crew_id):
    return sum(
        1 for wp in db.work_phases.values()
        if wp['crew_id'] == crew_id and wp['status'] in ('SCHEDULED', 'IN_PROGRESS')
    )


def serialize(rec):
    out = {k: v for k, v in rec.items() if not k.startswith('_')}
    if rec.get('_kind') == 'crew':
        out['active_booking_count'] = count_active_bookings(rec['id'])
    return out


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def find(collection, ident, not_found_error):
    rec = collection.get(ident)
    if rec is None:
        raise ApiError(not_found_error, 404, 'Resource not found')
    return rec


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
def get_pagination():
    def parse(name, default, lo, hi):
        raw = request.args.get(name)
        if raw is None or raw == '':
            return default
        try:
            v = int(raw)
        except (ValueError, TypeError):
            return default
        if lo is not None and v < lo:
            v = lo
        if hi is not None and v > hi:
            v = hi
        return v

    limit = parse('limit', 10, 1, 100)
    offset = parse('offset', 0, 0, None)
    return limit, offset


def list_response(values, predicate):
    items = [r for r in sorted(values, key=lambda x: x['_seq']) if predicate(r)]
    limit, offset = get_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        'limit': limit,
        'offset': offset,
        'total_count': total,
        'has_more': offset + len(page) < total,
    }
    return ok([serialize(x) for x in page], 'array', 200, pagination)
