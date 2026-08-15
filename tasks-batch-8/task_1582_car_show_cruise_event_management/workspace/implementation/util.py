"""Shared helpers: time parsing, validation, pagination, serialization."""
from datetime import datetime

from flask import request

from errors import ApiError

MISSING = object()


def parse_dt(value, field='datetime'):
    """Parse an ISO 8601 datetime string into an aware datetime (UTC assumed for Z)."""
    if not isinstance(value, str):
        raise ApiError('ERR_VALIDATION', 400, f'{field} must be an ISO 8601 string')
    s = value.strip()
    try:
        if s.endswith('Z'):
            s2 = s[:-1] + '+00:00'
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
    except (ValueError, TypeError):
        raise ApiError('ERR_VALIDATION', 400, f'{field} is not a valid ISO 8601 datetime')
    if dt.tzinfo is None:
        from datetime import timezone
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_hhmm(value, field='HH:MM'):
    if not isinstance(value, str) or len(value) != 5 or value[2] != ':':
        raise ApiError('ERR_VALIDATION', 400, f'{field} must be HH:MM')
    try:
        h = int(value[:2])
        m = int(value[3:])
    except ValueError:
        raise ApiError('ERR_VALIDATION', 400, f'{field} must be HH:MM')
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ApiError('ERR_VALIDATION', 400, f'{field} must be a valid HH:MM time')
    return h, m


def parse_date(value, field='date'):
    if not isinstance(value, str):
        raise ApiError('ERR_VALIDATION', 400, f'{field} must be YYYY-MM-DD')
    try:
        datetime.strptime(value, '%Y-%m-%d')
    except (ValueError, TypeError):
        raise ApiError('ERR_VALIDATION', 400, f'{field} must be YYYY-MM-DD')
    return value


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError('ERR_VALIDATION', 400, 'Request body must be a JSON object')
    return data


def get_field(data, name, required=True, default=None, type_=None, field_label=None):
    val = data.get(name, MISSING)
    if val is MISSING:
        if required:
            raise ApiError('ERR_VALIDATION', 400,
                           f'Missing required field: {field_label or name}')
        return default
    if type_ is not None and val is not None:
        if type_ is bool:
            if not isinstance(val, bool):
                raise ApiError('ERR_VALIDATION', 400,
                               f'{field_label or name} must be a boolean')
        elif type_ is int:
            if not isinstance(val, int) or isinstance(val, bool):
                raise ApiError('ERR_VALIDATION', 400,
                               f'{field_label or name} must be an integer')
        elif type_ is (int, float):
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                raise ApiError('ERR_VALIDATION', 400,
                               f'{field_label or name} must be a number')
        elif type_ is str:
            if not isinstance(val, str):
                raise ApiError('ERR_VALIDATION', 400,
                               f'{field_label or name} must be a string')
        elif type_ is list:
            if not isinstance(val, list):
                raise ApiError('ERR_VALIDATION', 400,
                               f'{field_label or name} must be an array')
    return val


def get_enum(data, name, allowed, required=True, default=None):
    val = get_field(data, name, required=required, default=default)
    if val is None and not required:
        return val
    if val not in allowed:
        raise ApiError('ERR_VALIDATION', 400,
                       f'{name} must be one of {sorted(allowed)}')
    return val


def get_int(data, name, required=True, default=None, min_v=None, max_v=None):
    val = get_field(data, name, required=required, default=default, type_=int)
    if val is None and not required:
        return val
    if min_v is not None and val < min_v:
        raise ApiError('ERR_VALIDATION', 400, f'{name} must be >= {min_v}')
    if max_v is not None and val > max_v:
        raise ApiError('ERR_VALIDATION', 400, f'{name} must be <= {max_v}')
    return val


def get_number(data, name, required=True, default=None, min_v=None):
    val = get_field(data, name, required=required, default=default, type_=(int, float))
    if val is None and not required:
        return val
    if min_v is not None and not (val > min_v if min_v == 0 else val >= min_v):
        pass  # handled by explicit checks at call sites
    return val


def get_pagination():
    """limit/offset per PRD 2.3: default 10, min 1, max 100, offset default 0."""
    raw_limit = request.args.get('limit')
    raw_offset = request.args.get('offset')
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (ValueError, TypeError):
        raise ApiError('ERR_VALIDATION', 400, 'limit must be an integer')
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (ValueError, TypeError):
        raise ApiError('ERR_VALIDATION', 400, 'offset must be an integer')
    if limit < 1 or limit > 100:
        raise ApiError('ERR_VALIDATION', 400, 'limit must be between 1 and 100')
    if offset < 0:
        raise ApiError('ERR_VALIDATION', 400, 'offset must be >= 0')
    return limit, offset


def paginate(items, limit, offset):
    """items: full sorted list. Returns (page_items, total_count)."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
