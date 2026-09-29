"""Authentication, authorisation and request payload validation.

Every request must carry two headers: ``X-User-ID`` identifies the acting user
and ``X-User-Role`` declares the capacity in which they act (PRD 2.1).
"""
import re
from decimal import Decimal, InvalidOperation

from flask import request

from dt_util import parse_date, parse_datetime
from errors import ApiError

ROLES = (
    'CsmUser',
    'CsOpsAdmin',
    'CsExecutive',
    'FinanceAnalyst',
    'SalesAccountExecutive',
    'AdvocacyManager',
)
ALL_ROLES = ROLES


def invalid(message):
    return ApiError('ERR_INVALID_REQUEST', message)


def authenticate(allowed_roles):
    """Rule 1 then rule 2 of the validation ladder."""
    user_id = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if role is None:
        role = request.headers.get('X-Role')
    if user_id is None or not str(user_id).strip():
        raise ApiError('ERR_UNAUTHENTICATED',
                       'X-User-ID header is missing or empty.')
    if role is None or role not in ROLES:
        raise ApiError('ERR_UNAUTHENTICATED',
                       'X-User-Role header is missing or names an unknown role.')
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError('ERR_UNAUTHORIZED',
                       'Role %s may not perform this operation.' % role)
    return str(user_id), role


def body():
    if request.method not in ('POST', 'PATCH', 'PUT'):
        return {}
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or not raw.strip():
        return {}
    data = request.get_json(force=True, silent=True)
    if data is None:
        raise invalid('Request body must be a JSON object.')
    if not isinstance(data, dict):
        raise invalid('Request body must be a JSON object.')
    return data


# ---------------------------------------------------------------------------
# Field level validation (ladder rule 5, ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------

def present(data, key):
    return key in data and data[key] is not None


def require_present(data, key):
    if not present(data, key):
        raise invalid('%s is required.' % key)


def as_string(data, key, required=True, min_len=1, max_len=None):
    if not present(data, key):
        if required:
            raise invalid('%s is required.' % key)
        return None
    value = data[key]
    if not isinstance(value, str):
        raise invalid('%s must be a string.' % key)
    if len(value.strip()) < min_len:
        raise invalid('%s must be a non-empty string.' % key)
    if max_len is not None and len(value) > max_len:
        raise invalid('%s must be at most %d characters.' % (key, max_len))
    return value


def as_enum(data, key, allowed, required=True):
    if not present(data, key):
        if required:
            raise invalid('%s is required.' % key)
        return None
    value = data[key]
    if not isinstance(value, str) or value not in allowed:
        raise invalid('%s must be one of %s.' % (key, ', '.join(sorted(allowed))))
    return value


def as_int(data, key, required=True, minimum=None, maximum=None):
    if not present(data, key):
        if required:
            raise invalid('%s is required.' % key)
        return None
    value = data[key]
    if isinstance(value, bool):
        raise invalid('%s must be an integer.' % key)
    if isinstance(value, int):
        result = value
    elif isinstance(value, float):
        if value != int(value):
            raise invalid('%s must be an integer.' % key)
        result = int(value)
    else:
        raise invalid('%s must be an integer.' % key)
    if minimum is not None and result < minimum:
        raise invalid('%s must be at least %s.' % (key, minimum))
    if maximum is not None and result > maximum:
        raise invalid('%s must be at most %s.' % (key, maximum))
    return result


def as_decimal(data, key, required=True, minimum=None, maximum=None,
               exclusive_minimum=None):
    if not present(data, key):
        if required:
            raise invalid('%s is required.' % key)
        return None
    value = data[key]
    if isinstance(value, bool):
        raise invalid('%s must be a number.' % key)
    if isinstance(value, (int, float)):
        try:
            result = Decimal(str(value))
        except InvalidOperation:
            raise invalid('%s must be a number.' % key)
    else:
        raise invalid('%s must be a number.' % key)
    if minimum is not None and result < Decimal(str(minimum)):
        raise invalid('%s must be at least %s.' % (key, minimum))
    if exclusive_minimum is not None and result <= Decimal(str(exclusive_minimum)):
        raise invalid('%s must be greater than %s.' % (key, exclusive_minimum))
    if maximum is not None and result > Decimal(str(maximum)):
        raise invalid('%s must be at most %s.' % (key, maximum))
    return result


def as_bool(data, key, required=True):
    if not present(data, key):
        if required:
            raise invalid('%s is required.' % key)
        return None
    value = data[key]
    if not isinstance(value, bool):
        raise invalid('%s must be a boolean.' % key)
    return value


def as_date(data, key, required=True):
    if not present(data, key):
        if required:
            raise invalid('%s is required.' % key)
        return None
    value = data[key]
    if not isinstance(value, str):
        raise invalid('%s must be an ISO 8601 calendar date.' % key)
    parsed = parse_date(value)
    if parsed is None:
        raise invalid('%s must be an ISO 8601 calendar date (YYYY-MM-DD).' % key)
    return parsed


def as_datetime(data, key, required=True):
    if not present(data, key):
        if required:
            raise invalid('%s is required.' % key)
        return None
    value = data[key]
    if not isinstance(value, str):
        raise invalid('%s must be an ISO 8601 UTC timestamp.' % key)
    parsed = parse_datetime(value)
    if parsed is None:
        raise invalid('%s must be an ISO 8601 UTC timestamp.' % key)
    return parsed


def as_id(data, key, required=True):
    """A reference identifier: shape checked here, existence checked earlier by
    the foreign-key rule of the ladder."""
    if not present(data, key):
        if required:
            raise invalid('%s is required.' % key)
        return None
    value = data[key]
    if not isinstance(value, str) or not value.strip():
        raise invalid('%s must be a string identifier.' % key)
    return value


def raw_id(data, key):
    """Return a body reference only when it is a usable string, for the
    foreign-key existence pass that runs before schema validation."""
    if key in data and isinstance(data[key], str) and data[key].strip():
        return data[key]
    return None


# ---------------------------------------------------------------------------
# Query parameters
# ---------------------------------------------------------------------------

_INT_RE = re.compile(r'^[+-]?\d+$')

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def pagination():
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    raw_limit = request.args.get('limit')
    if raw_limit is not None and raw_limit != '':
        if not _INT_RE.match(raw_limit.strip()):
            raise invalid('limit must be an integer.')
        limit = int(raw_limit.strip())
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise invalid('limit must be between %d and %d.' % (LIMIT_MIN, LIMIT_MAX))
    raw_offset = request.args.get('offset')
    if raw_offset is not None and raw_offset != '':
        if not _INT_RE.match(raw_offset.strip()):
            raise invalid('offset must be an integer.')
        offset = int(raw_offset.strip())
        if offset < OFFSET_MIN:
            raise invalid('offset must be at least %d.' % OFFSET_MIN)
    return limit, offset


def query_enum(key, allowed):
    value = request.args.get(key)
    if value is None or value == '':
        return None
    if value not in allowed:
        raise invalid('%s must be one of %s.' % (key, ', '.join(sorted(allowed))))
    return value


def query_value(key):
    value = request.args.get(key)
    if value is None or value == '':
        return None
    return value
