"""Request body validation helpers and pagination parsing."""
from flask import request

from dates import parse_date
from errors import ERR_INVALID_REQUEST, raise_err


def get_body():
    """Parse the JSON request body; absent/non-dict bodies become {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise_err(ERR_INVALID_REQUEST, 'Request body must be a JSON object')
    return data


def missing(value):
    return value is None


def require(body, field):
    if field not in body or body[field] is None:
        raise_err(ERR_INVALID_REQUEST, 'Missing required field: %s' % field)
    return body[field]


def opt(body, field, default=None):
    v = body.get(field, default)
    return default if v is None else v


def req_str(body, field):
    v = require(body, field)
    if not isinstance(v, str) or not v.strip():
        raise_err(ERR_INVALID_REQUEST, 'Field %s must be a non-empty string' % field)
    return v


def opt_str(body, field, default=None):
    v = body.get(field, default)
    if v is None:
        return default
    if not isinstance(v, str):
        raise_err(ERR_INVALID_REQUEST, 'Field %s must be a string' % field)
    return v


def req_enum(body, field, allowed):
    v = require(body, field)
    if v not in allowed:
        raise_err(ERR_INVALID_REQUEST, 'Field %s must be one of %s' % (field, sorted(allowed)))
    return v


def opt_enum(body, field, allowed, default):
    v = body.get(field, default)
    if v is None:
        return default
    if v not in allowed:
        raise_err(ERR_INVALID_REQUEST, 'Field %s must be one of %s' % (field, sorted(allowed)))
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(body, field, minimum=None):
    v = require(body, field)
    if not _is_int(v):
        raise_err(ERR_INVALID_REQUEST, 'Field %s must be an integer' % field)
    if minimum is not None and v < minimum:
        raise_err(ERR_INVALID_REQUEST, 'Field %s must be >= %s' % (field, minimum))
    return v


def req_bool(body, field):
    v = require(body, field)
    if not isinstance(v, bool):
        raise_err(ERR_INVALID_REQUEST, 'Field %s must be a boolean' % field)
    return v


def opt_bool(body, field, default):
    v = body.get(field, default)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise_err(ERR_INVALID_REQUEST, 'Field %s must be a boolean' % field)
    return v


def req_date(body, field):
    v = require(body, field)
    d = parse_date(v)
    if d is None:
        raise_err(ERR_INVALID_REQUEST, 'Field %s must be an ISO date (YYYY-MM-DD)' % field)
    return d


def parse_pagination():
    """limit: default 10, min 1, max 100. offset: default 0, min 0."""
    raw_limit = request.args.get('limit')
    raw_offset = request.args.get('offset')
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except ValueError:
            raise_err(ERR_INVALID_REQUEST, 'limit must be an integer')
        if limit < 1 or limit > 100:
            raise_err(ERR_INVALID_REQUEST, 'limit must be between 1 and 100')
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except ValueError:
            raise_err(ERR_INVALID_REQUEST, 'offset must be an integer')
        if offset < 0:
            raise_err(ERR_INVALID_REQUEST, 'offset must be >= 0')
    return limit, offset


def parse_bool_param(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    low = raw.lower()
    if low == 'true':
        return True
    if low == 'false':
        return False
    raise_err(ERR_INVALID_REQUEST, 'Query parameter %s must be true or false' % name)


def paginate(items, limit, offset):
    """items: pre-sorted full list. Returns (page, total_count)."""
    total = len(items)
    return items[offset:offset + limit], total


def sorted_created(items):
    return sorted(items, key=lambda e: e['_seq'])
