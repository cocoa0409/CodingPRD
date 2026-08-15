"""Request shape validation helpers (validation tier 3) + pagination parsing."""
from datetime import datetime, timezone

from flask import request

from errors import ApiError

MISSING = object()


def get_body(required=True):
    body = request.get_json(silent=True)
    if body is None:
        if required:
            raise ApiError('ERR_VALIDATION', 400, 'request body must be a JSON object')
        return {}
    if not isinstance(body, dict):
        raise ApiError('ERR_VALIDATION', 400, 'request body must be a JSON object')
    return body


def _bad(field):
    raise ApiError('ERR_VALIDATION', 400, 'field %s is missing or has an invalid type' % field)


def req_str(body, field):
    v = body.get(field, MISSING)
    if v is MISSING or not isinstance(v, str) or v == '':
        _bad(field)
    return v


def opt_str(body, field, default=None):
    v = body.get(field, MISSING)
    if v is MISSING or v is None:
        return default
    if not isinstance(v, str):
        _bad(field)
    return v


def req_enum(body, field, values):
    v = body.get(field, MISSING)
    if v is MISSING or not isinstance(v, str):
        _bad(field)
    if v not in values:
        raise ApiError('ERR_INVALID_ENUM', 400,
                       'field %s must be one of %s' % (field, '|'.join(values)))
    return v


def opt_enum(body, field, values, default=None):
    v = body.get(field, MISSING)
    if v is MISSING or v is None:
        return default
    if not isinstance(v, str):
        _bad(field)
    if v not in values:
        raise ApiError('ERR_INVALID_ENUM', 400,
                       'field %s must be one of %s' % (field, '|'.join(values)))
    return v


def req_int(body, field, minimum=None):
    v = body.get(field, MISSING)
    if v is MISSING or isinstance(v, bool) or not isinstance(v, int):
        _bad(field)
    if minimum is not None and v < minimum:
        _bad(field)
    return v


def opt_int(body, field, default=None, minimum=None):
    v = body.get(field, MISSING)
    if v is MISSING or v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(field)
    if minimum is not None and v < minimum:
        _bad(field)
    return v


def req_number(body, field, minimum=None, min_exclusive=False):
    v = body.get(field, MISSING)
    if v is MISSING or isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad(field)
    if minimum is not None:
        if min_exclusive and not v > minimum:
            _bad(field)
        if not min_exclusive and v < minimum:
            _bad(field)
    return v


def opt_number(body, field, default=None, minimum=None):
    v = body.get(field, MISSING)
    if v is MISSING or v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad(field)
    if minimum is not None and v < minimum:
        _bad(field)
    return v


def opt_bool(body, field, default=None):
    v = body.get(field, MISSING)
    if v is MISSING or v is None:
        return default
    if not isinstance(v, bool):
        _bad(field)
    return v


def req_dict(body, field):
    v = body.get(field, MISSING)
    if v is MISSING or not isinstance(v, dict):
        _bad(field)
    return v


def opt_str_list(body, field, default=None):
    v = body.get(field, MISSING)
    if v is MISSING or v is None:
        return list(default) if default is not None else []
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        _bad(field)
    return list(v)


def parse_dt(value, field):
    """Parse an ISO 8601 datetime string to an aware UTC datetime."""
    if not isinstance(value, str) or not value:
        _bad(field)
    s = value.strip()
    if s.endswith('Z') or s.endswith('z'):
        s = s[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        _bad(field)
    if dt.tzinfo is None:
        _bad(field)
    return dt.astimezone(timezone.utc)


def req_datetime(body, field):
    return parse_dt(body.get(field, MISSING), field)


def parse_pagination():
    """limit: default 10, min 1, max 100. offset: default 0, min 0."""
    raw_limit = request.args.get('limit')
    raw_offset = request.args.get('offset')
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError('ERR_VALIDATION', 400, 'limit must be an integer')
        if limit < 1 or limit > 100:
            raise ApiError('ERR_VALIDATION', 400, 'limit must be between 1 and 100')
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError('ERR_VALIDATION', 400, 'offset must be an integer')
        if offset < 0:
            raise ApiError('ERR_VALIDATION', 400, 'offset must be >= 0')
    return limit, offset


def bool_filter(name):
    raw = request.args.get(name)
    if raw is None:
        return MISSING
    low = raw.lower()
    if low == 'true':
        return True
    if low == 'false':
        return False
    raise ApiError('ERR_VALIDATION', 400, 'filter %s must be true or false' % name)


def enum_filter(name, values):
    raw = request.args.get(name)
    if raw is None:
        return MISSING
    if raw not in values:
        raise ApiError('ERR_INVALID_ENUM', 400,
                       'filter %s must be one of %s' % (name, '|'.join(values)))
    return raw


def str_filter(name):
    raw = request.args.get(name)
    if raw is None:
        return MISSING
    return raw


def paginate(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total
