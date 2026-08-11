"""Auth, body well-formedness, existence, pagination — validation chain §2.6."""
import math
import re
from datetime import datetime

from flask import request

from .db import db
from .errors import ApiError

ROLES = ['OpsAdmin', 'CatalogManager', 'InventoryClerk', 'QualityManager',
         'AccountManager', 'Customer']

DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def get_context():
    """Stage 1: both headers present, role declared."""
    uid = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if not uid or not role or role not in ROLES:
        raise ApiError('ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER',
                       'X-User-ID and X-User-Role headers must both be present '
                       'and X-User-Role must be a declared role')
    return uid, role


def require_role(role, allowed):
    """Stage 2: role must be in the endpoint's roles list."""
    if role not in allowed:
        raise ApiError('ERR_FORBIDDEN_ROLE',
                       'Role %s is not authorized for this endpoint' % role)


def get_body():
    """Parse the JSON request body. Empty body -> {}. Malformed -> 400."""
    if request.content_length in (None, 0) and not request.data:
        return {}
    data = request.get_json(silent=True, force=False)
    if data is None:
        # try parsing anyway (missing content-type)
        data = request.get_json(silent=True, force=True)
    if data is None:
        raise ApiError('ERR_INVALID_REQUEST', 'Request body must be valid JSON')
    if not isinstance(data, dict):
        raise ApiError('ERR_INVALID_REQUEST', 'Request body must be a JSON object')
    return data


# ---- field validators (stage 5) ----

def check_unknown(body, allowed_fields):
    for k in body:
        if k not in allowed_fields:
            raise ApiError('ERR_INVALID_REQUEST', 'Unknown field: %s' % k)


def req_field(body, name):
    if name not in body or body[name] is None:
        raise ApiError('ERR_INVALID_REQUEST', 'Missing required field: %s' % name)
    return body[name]


def as_str(body, name, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise ApiError('ERR_INVALID_REQUEST', 'Missing required field: %s' % name)
        return default
    v = body[name]
    if not isinstance(v, str):
        raise ApiError('ERR_INVALID_REQUEST', 'Field %s must be a string' % name)
    return v


def as_bool(body, name, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise ApiError('ERR_INVALID_REQUEST', 'Missing required field: %s' % name)
        return default
    v = body[name]
    if type(v) is not bool:
        raise ApiError('ERR_INVALID_REQUEST', 'Field %s must be a boolean' % name)
    return v


def as_int(body, name, required=True, default=None, min_value=None, max_value=None):
    if name not in body or body[name] is None:
        if required:
            raise ApiError('ERR_INVALID_REQUEST', 'Missing required field: %s' % name)
        return default
    v = body[name]
    if type(v) is not int:
        raise ApiError('ERR_INVALID_REQUEST', 'Field %s must be an integer' % name)
    if min_value is not None and v < min_value:
        raise ApiError('ERR_INVALID_REQUEST',
                       'Field %s must be >= %s' % (name, min_value))
    if max_value is not None and v > max_value:
        raise ApiError('ERR_INVALID_REQUEST',
                       'Field %s must be <= %s' % (name, max_value))
    return v


def as_number(body, name, required=True, default=None, min_value=None, max_value=None):
    if name not in body or body[name] is None:
        if required:
            raise ApiError('ERR_INVALID_REQUEST', 'Missing required field: %s' % name)
        return default
    v = body[name]
    if type(v) is bool or not isinstance(v, (int, float)):
        raise ApiError('ERR_INVALID_REQUEST', 'Field %s must be a number' % name)
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        raise ApiError('ERR_INVALID_REQUEST', 'Field %s must be finite' % name)
    if min_value is not None and v < min_value:
        raise ApiError('ERR_INVALID_REQUEST',
                       'Field %s must be >= %s' % (name, min_value))
    if max_value is not None and v > max_value:
        raise ApiError('ERR_INVALID_REQUEST',
                       'Field %s must be <= %s' % (name, max_value))
    return v


def as_enum(body, name, members, required=True, default=None):
    v = as_str(body, name, required=required, default=default)
    if v is None:
        return None
    if v not in members:
        raise ApiError('ERR_INVALID_REQUEST',
                       'Field %s must be one of %s' % (name, ', '.join(members)))
    return v


def as_date(body, name, required=True, default=None):
    v = as_str(body, name, required=required, default=default)
    if v is None:
        return None
    if not DATE_RE.match(v):
        raise ApiError('ERR_INVALID_REQUEST',
                       'Field %s must be an ISO date YYYY-MM-DD' % name)
    try:
        datetime.strptime(v, '%Y-%m-%d')
    except ValueError:
        raise ApiError('ERR_INVALID_REQUEST',
                       'Field %s is not a valid calendar date' % name)
    return v


def as_datetime(body, name, required=True):
    v = as_str(body, name, required=required)
    dt = parse_iso8601(v)
    if dt is None:
        raise ApiError('ERR_INVALID_REQUEST',
                       'Field %s must be an ISO 8601 instant' % name)
    return dt


def parse_iso8601(s):
    if not isinstance(s, str):
        return None
    t = s.strip()
    if t.endswith('Z'):
        t = t[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        from datetime import timezone
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def id_or_none(body, name):
    """Body id value usable for stage-4 existence only when present and a string."""
    v = body.get(name)
    return v if isinstance(v, str) else None


# ---- existence helpers (stage 4) ----

def get_path_resource(collection, rid, error_id):
    rec = collection.get(rid)
    if rec is None:
        raise ApiError(error_id, 'Resource %s does not exist' % rid)
    return rec


def check_body_id(collection, body, field, error_id):
    """Stage 4 for body-referenced ids (only when present and a string)."""
    v = id_or_none(body, field)
    if v is not None and v not in collection:
        raise ApiError(error_id, 'Referenced %s %s does not exist' % (field, v))
    return v


# ---- pagination ----

def pagination_params():
    limit_raw = request.args.get('limit')
    offset_raw = request.args.get('offset')
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError('ERR_INVALID_REQUEST', 'limit must be an integer')
        if str(limit_raw).strip() != str(limit):
            raise ApiError('ERR_INVALID_REQUEST', 'limit must be an integer')
        if limit < 1 or limit > 100:
            raise ApiError('ERR_INVALID_REQUEST', 'limit must be between 1 and 100')
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError('ERR_INVALID_REQUEST', 'offset must be an integer')
        if str(offset_raw).strip() != str(offset):
            raise ApiError('ERR_INVALID_REQUEST', 'offset must be an integer')
        if offset < 0:
            raise ApiError('ERR_INVALID_REQUEST', 'offset must be >= 0')
    return limit, offset


def paginate(items, serializer):
    """Sort by creation order, apply equality filters already applied by caller."""
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    return [serializer(x) for x in page], {
        'limit': limit,
        'offset': offset,
        'total_count': total,
        'has_more': offset + len(page) < total,
    }


def apply_filters(items, filters):
    out = []
    for it in items:
        ok = True
        for field, value in filters.items():
            if value is None:
                continue
            if it.get(field) != value:
                ok = False
                break
        if ok:
            out.append(it)
    return out
