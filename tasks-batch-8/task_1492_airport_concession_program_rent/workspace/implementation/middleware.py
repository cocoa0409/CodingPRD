"""Authentication and role helpers (PRD section 2.1, validation stages 1-2)."""
import re
from datetime import datetime

from flask import g, request

from db import db
from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN, ERR_INVALID_REQUEST

ROLES = ('AirportAdmin', 'ConcessionAnalyst', 'Tenant', 'Auditor')

_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_MONTH_RE = re.compile(r'^\d{4}-\d{2}$')


def authenticate():
    uid = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if not uid or not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401,
                       'Missing or unknown X-User-Role / X-User-ID headers')
    g.user_id = uid
    g.role = role


def require_roles(*roles):
    if g.role not in roles:
        raise ApiError(ERR_FORBIDDEN, 403, 'Role not permitted on this endpoint')


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def body_json():
    data = request.get_json(force=True, silent=True)
    if data is None:
        if request.data:
            raise ApiError(ERR_INVALID_REQUEST, 400, 'Malformed JSON request body')
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, 'Request body must be a JSON object')
    return data


def req_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v == '':
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       'Required field missing or malformed: {0}'.format(name))
    return v


def req_int(body, name):
    v = body.get(name)
    if not is_int(v):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       'Required field missing or malformed: {0}'.format(name))
    return v


def opt_int(body, name):
    if name not in body or body[name] is None:
        return None
    if not is_int(body[name]):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       'Field malformed: {0}'.format(name))
    return body[name]


def valid_date_str(s):
    if not isinstance(s, str) or not _DATE_RE.match(s):
        return False
    try:
        datetime.strptime(s, '%Y-%m-%d')
        return True
    except ValueError:
        return False


def req_date(body, name):
    v = body.get(name)
    if not valid_date_str(v):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       'Required field missing or malformed: {0}'.format(name))
    return v


def valid_month_str(s):
    if not isinstance(s, str) or not _MONTH_RE.match(s):
        return False
    try:
        datetime.strptime(s, '%Y-%m')
        return True
    except ValueError:
        return False


def req_month(body, name):
    v = body.get(name)
    if not valid_month_str(v):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       'Required field missing or malformed: {0}'.format(name))
    return v


def require_lease_owner(lease):
    """Tenant-scoped rule: lease.tenant_id must equal the acting X-User-ID."""
    if lease['tenant_id'] != g.user_id:
        raise ApiError(ERR_FORBIDDEN, 403,
                       'Tenant may act only on records of its own leases')
