"""HTTP utilities: envelope, auth, structural body validation, datetimes, pagination."""
import re
import uuid
from datetime import datetime, timezone

from flask import request, jsonify

from errors import err
from db import store

ROLES = ('Dispatcher', 'Captain', 'DispatchSupervisor')
_MISSING = object()


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

def _req_meta():
    now = datetime.now(timezone.utc)
    return {
        'api_request_id': 'req_' + uuid.uuid4().hex,
        'api_request_timestamp': fmt_ts(now),
    }


def ok(data, status=200, is_list=False, pagination=None):
    meta = _req_meta()
    if pagination is not None:
        meta.update(pagination)
    body = {
        'meta': meta,
        'response_type': 'array' if is_list else 'object',
        'data': data,
    }
    return jsonify(body), status


def error_body(api_err):
    body = {
        'meta': _req_meta(),
        'response_type': 'error',
        'data': {'error_id': api_err.error_id, 'message': api_err.message},
    }
    return jsonify(body), api_err.http_status


# ---------------------------------------------------------------------------
# Datetimes
# ---------------------------------------------------------------------------

def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits (created_at etc.)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + '%03dZ' % (dt.microsecond // 1000)


def fmt_dt(dt):
    """Echo format for caller-supplied / clock-stamped instants."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    return fmt_ts(dt)


def parse_dt(value):
    if not isinstance(value, str):
        raise err('ERR_INVALID_REQUEST', 'datetime field must be an ISO 8601 string')
    s = value.strip()
    if s.endswith('Z') or s.endswith('z'):
        s = s[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise err('ERR_INVALID_REQUEST', 'invalid ISO 8601 datetime: %r' % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def authenticate():
    uid = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if not uid or not role or role not in ROLES:
        raise err('ERR_UNAUTHENTICATED')
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise err('ERR_UNAUTHORIZED_ROLE')


# ---------------------------------------------------------------------------
# Structural body validation
# ---------------------------------------------------------------------------

def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def _convert(type_spec, value, field):
    bad = lambda: err('ERR_INVALID_REQUEST', 'field %r has wrong type or value' % field)
    if type_spec == 'str':
        if not isinstance(value, str):
            raise bad()
        return value
    if type_spec == 'int':
        if not _is_int(value):
            raise bad()
        return value
    if type_spec == 'pos_int':
        if not _is_int(value) or value <= 0:
            raise bad()
        return value
    if type_spec == 'nn_int':
        if not _is_int(value) or value < 0:
            raise bad()
        return value
    if type_spec == 'num':
        if not _is_num(value):
            raise bad()
        return value
    if type_spec == 'pos_num':
        if not _is_num(value) or value <= 0:
            raise bad()
        return value
    if type_spec == 'nn_num':
        if not _is_num(value) or value < 0:
            raise bad()
        return value
    if type_spec == 'bool':
        if not isinstance(value, bool):
            raise bad()
        return value
    if type_spec == 'dt':
        return parse_dt(value)
    if type_spec == 'str_list':
        if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
            raise bad()
        return list(value)
    if type_spec.startswith('enum:'):
        members = type_spec[5:].split(',')
        if not isinstance(value, str) or value not in members:
            raise bad()
        return value
    raise RuntimeError('unknown type spec ' + type_spec)


def validate_body(schema):
    """schema: {field: (type_spec, required, default)}. Returns dict of cleaned
    values; fields omitted with no default are absent from the result."""
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise err('ERR_INVALID_REQUEST', 'request body must be a JSON object')
    for key in body:
        if key not in schema:
            raise err('ERR_INVALID_REQUEST', 'unknown field %r' % key)
    out = {}
    for field, (type_spec, required, default) in schema.items():
        if field in body and body[field] is not None:
            out[field] = _convert(type_spec, body[field], field)
        elif required:
            raise err('ERR_INVALID_REQUEST', 'missing required field %r' % field)
        elif default is not _MISSING:
            out[field] = default
    return out


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def pagination_params():
    limit_raw = request.args.get('limit')
    offset_raw = request.args.get('offset')
    limit, offset = 10, 0
    if limit_raw is not None:
        if not re.fullmatch(r'-?\d+', limit_raw or ''):
            raise err('ERR_INVALID_REQUEST', 'limit must be an integer')
        limit = int(limit_raw)
        if limit < 1 or limit > 100:
            raise err('ERR_INVALID_REQUEST', 'limit out of range [1, 100]')
    if offset_raw is not None:
        if not re.fullmatch(r'-?\d+', offset_raw or ''):
            raise err('ERR_INVALID_REQUEST', 'offset must be an integer')
        offset = int(offset_raw)
        if offset < 0:
            raise err('ERR_INVALID_REQUEST', 'offset must be >= 0')
    return limit, offset


def paginate(items, limit, offset):
    """items must already be sorted by (created_at, insertion seq) ascending."""
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        'limit': limit,
        'offset': offset,
        'total_count': total,
        'has_more': (offset + len(page)) < total,
    }
    return page, meta


def sorted_created(records):
    return sorted(records, key=lambda r: (r['created_at'], r['_seq']))


def get_or_404(collection, rid, what='resource'):
    rec = collection.get(rid)
    if rec is None:
        raise err('ERR_NOT_FOUND', '%s %s does not exist' % (what, rid))
    return rec
