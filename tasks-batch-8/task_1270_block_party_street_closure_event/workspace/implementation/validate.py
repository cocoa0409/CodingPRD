"""Schema-level request validation helpers (ERR_INVALID_REQUEST, HTTP 400)."""
import re
from datetime import datetime, timezone

from flask import request

from errors import ApiError

_HHMM = re.compile(r'^([01][0-9]|2[0-3]):([0-5][0-9])$')


def body():
    j = request.get_json(silent=True)
    return j if isinstance(j, dict) else {}


def req(b, name):
    v = b.get(name)
    if v is None:
        raise ApiError('ERR_INVALID_REQUEST',
                       'Missing required field: %s' % name, 400)
    return v


def as_str(v, name):
    if not isinstance(v, str):
        raise ApiError('ERR_INVALID_REQUEST', '%s must be a string' % name, 400)
    return v


def as_int(v, name):
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError('ERR_INVALID_REQUEST', '%s must be an integer' % name, 400)
    return v


def as_num(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError('ERR_INVALID_REQUEST', '%s must be a number' % name, 400)
    return v


def as_bool(v, name):
    if not isinstance(v, bool):
        raise ApiError('ERR_INVALID_REQUEST', '%s must be a boolean' % name, 400)
    return v


def as_enum(v, name, allowed):
    if not isinstance(v, str) or v not in allowed:
        raise ApiError('ERR_INVALID_REQUEST',
                       '%s must be one of %s' % (name, ', '.join(allowed)), 400)
    return v


def as_dt(v, name):
    if not isinstance(v, str):
        raise ApiError('ERR_INVALID_REQUEST', '%s must be an ISO 8601 datetime' % name, 400)
    try:
        dt = datetime.fromisoformat(v.replace('Z', '+00:00'))
    except ValueError:
        raise ApiError('ERR_INVALID_REQUEST', '%s must be an ISO 8601 datetime' % name, 400)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def as_date(v, name):
    if not isinstance(v, str):
        raise ApiError('ERR_INVALID_REQUEST', '%s must be a YYYY-MM-DD date' % name, 400)
    try:
        return datetime.strptime(v, '%Y-%m-%d').date()
    except ValueError:
        raise ApiError('ERR_INVALID_REQUEST', '%s must be a YYYY-MM-DD date' % name, 400)


def as_hhmm(v, name):
    if not isinstance(v, str):
        raise ApiError('ERR_INVALID_REQUEST', '%s must be an HH:MM time' % name, 400)
    m = _HHMM.match(v)
    if not m:
        raise ApiError('ERR_INVALID_REQUEST', '%s must be an HH:MM time' % name, 400)
    return (int(m.group(1)), int(m.group(2)))


def opt_int(b, name, default=None):
    v = b.get(name)
    return default if v is None else as_int(v, name)


def opt_bool(b, name, default=False):
    v = b.get(name)
    return default if v is None else as_bool(v, name)
