"""Request-body shape validation helpers (pipeline stage 3)."""
import re
from datetime import datetime, timezone

from flask import request

from errors import ApiError

DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def body():
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'Request body must be a JSON object')
    return data


def _bad(field, msg):
    raise ApiError('ERR_INVALID_REQUEST', 400, '{} {}'.format(field, msg))


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str):
        _bad(field, 'is required and must be a string')
    return v


def opt_str(data, field):
    if field not in data or data.get(field) is None:
        return None
    v = data.get(field)
    if not isinstance(v, str):
        _bad(field, 'must be a string')
    return v


def req_int(data, field, min_v=None, max_v=None):
    v = data.get(field)
    if not is_int(v):
        _bad(field, 'is required and must be an integer')
    if min_v is not None and v < min_v:
        _bad(field, 'must be >= {}'.format(min_v))
    if max_v is not None and v > max_v:
        _bad(field, 'must be <= {}'.format(max_v))
    return v


def opt_int(data, field, min_v=None, max_v=None, default=None):
    if field not in data or data.get(field) is None:
        return default
    return req_int(data, field, min_v, max_v)


def req_enum(data, field, allowed):
    v = data.get(field)
    if not isinstance(v, str) or v not in allowed:
        _bad(field, 'must be one of {}'.format(', '.join(sorted(allowed))))
    return v


def parse_date_value(v, field):
    if not isinstance(v, str) or not DATE_RE.match(v):
        _bad(field, 'must be an ISO date YYYY-MM-DD')
    try:
        return datetime.strptime(v, '%Y-%m-%d').date()
    except ValueError:
        _bad(field, 'must be a valid calendar date')


def req_date(data, field):
    return parse_date_value(data.get(field), field)


def opt_date(data, field, default=None):
    if field not in data or data.get(field) is None:
        return default
    return parse_date_value(data.get(field), field)


def parse_datetime_value(v, field):
    if not isinstance(v, str) or 'T' not in v:
        _bad(field, 'must be an ISO 8601 datetime')
    txt = v.strip()
    if txt.endswith('Z'):
        txt = txt[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        _bad(field, 'must be a valid ISO 8601 datetime')
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_datetime(data, field):
    return parse_datetime_value(data.get(field), field)
