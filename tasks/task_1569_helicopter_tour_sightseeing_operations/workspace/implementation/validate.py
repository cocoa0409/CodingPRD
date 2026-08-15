"""Request validation, auth, and pagination helpers.

Global guard ladder (PRD section 2.9): request validity, then authentication,
then authorization, then existence, then OCC, then state, then business rules.
These helpers implement rungs 1-3; views call them in that order.
"""
import json

from flask import request

from errors import raise_error, ERR_INVALID_REQUEST, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED_ROLE
from store import parse_datetime, parse_date

ROLES = (
    'OpsAdmin',
    'Dispatcher',
    'BookingAgent',
    'ComplianceOfficer',
    'CommunityReporter',
    'Pilot',
)

_MISSING = object()


def get_body():
    """Parse the JSON request body. Missing body -> {}; malformed -> 400."""
    raw = request.get_data(cache=True)
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        raise_error(ERR_INVALID_REQUEST, 'Request body is not valid JSON')
    if not isinstance(data, dict):
        raise_error(ERR_INVALID_REQUEST, 'Request body must be a JSON object')
    return data


def authenticate():
    uid = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if not uid or not role or role not in ROLES:
        raise_error(ERR_UNAUTHENTICATED, 'Missing or unrecognized X-User-Role / X-User-ID headers')
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise_error(ERR_UNAUTHORIZED_ROLE, 'Role not permitted on this endpoint')


def _value(data, field, required):
    v = data.get(field, _MISSING)
    if v is _MISSING or v is None:
        if required:
            raise_error(ERR_INVALID_REQUEST, f'Missing required field: {field}')
        return None
    return v


def _str(data, field, required):
    v = _value(data, field, required)
    if v is None:
        return None
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f'Field {field} must be a string')
    return v


def _int(data, field, required):
    v = _value(data, field, required)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_INVALID_REQUEST, f'Field {field} must be an integer')
    return v


def _num(data, field, required):
    v = _value(data, field, required)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_error(ERR_INVALID_REQUEST, f'Field {field} must be a number')
    return v


def _bool(data, field, required):
    v = _value(data, field, required)
    if v is None:
        return None
    if not isinstance(v, bool):
        raise_error(ERR_INVALID_REQUEST, f'Field {field} must be a boolean')
    return v


def _enum(data, field, required, choices):
    v = _value(data, field, required)
    if v is None:
        return None
    if not isinstance(v, str) or v not in choices:
        raise_error(ERR_INVALID_REQUEST, f'Field {field} must be one of {sorted(choices)}')
    return v


def _dt(data, field, required):
    v = _value(data, field, required)
    if v is None:
        return None
    try:
        return parse_datetime(v)
    except Exception:
        raise_error(ERR_INVALID_REQUEST, f'Field {field} must be an ISO8601 datetime')


def _date(data, field, required):
    v = _value(data, field, required)
    if v is None:
        return None
    try:
        return parse_date(v)
    except Exception:
        raise_error(ERR_INVALID_REQUEST, f'Field {field} must be a YYYY-MM-DD date')


def _list(data, field, required):
    v = _value(data, field, required)
    if v is None:
        return None
    if not isinstance(v, list):
        raise_error(ERR_INVALID_REQUEST, f'Field {field} must be an array')
    return v


def pagination_params():
    limit_raw = request.args.get('limit')
    offset_raw = request.args.get('offset')
    limit, offset = 10, 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, 'limit must be an integer')
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, 'offset must be an integer')
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paginated(items):
    """items is the full filtered+sorted list; returns (page, meta fields)."""
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        'limit': limit,
        'offset': offset,
        'total_count': total,
        'has_more': (offset + len(page)) < total,
    }
    return page, meta
