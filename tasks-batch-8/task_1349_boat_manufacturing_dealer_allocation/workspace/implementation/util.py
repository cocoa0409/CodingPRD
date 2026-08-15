"""Response envelope, auth middleware, and request validation helpers.

Envelope and header names read from SCAFFOLD §1.0 / PRD §2.1-§2.3.
"""
import random
import string
from flask import request, jsonify

from store import CLOCK, fmt_dt, parse_dt, parse_date


# ---------------------------------------------------------------- errors
class ApiError(Exception):
    def __init__(self, status, error_id, message):
        super().__init__(message)
        self.status = status
        self.error_id = error_id
        self.message = message


ERR_AUTH = 'ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER'
ERR_PERMS = 'ERR_INSUFFICIENT_PERMISSIONS'
ERR_INVALID = 'ERR_INVALID_REQUEST'


def invalid(msg):
    raise ApiError(400, ERR_INVALID, msg)


def not_found(error_id, msg):
    raise ApiError(404, error_id, msg)


# ---------------------------------------------------------------- envelope
def _meta():
    return {
        'api_request_id': 'req_' + ''.join(
            random.choices(string.ascii_letters + string.digits, k=24)),
        'api_request_timestamp': fmt_dt(CLOCK.now()),
    }


def respond(data, code=200, rtype='object', page=None):
    meta = _meta()
    if page is not None:
        meta.update(page)
    body = {'meta': meta, 'response_type': rtype, 'data': data}
    return jsonify(body), code


def error_response(status, error_id, message):
    body = {
        'meta': _meta(),
        'response_type': 'error',
        'data': {'error_id': error_id, 'message': message},
    }
    return jsonify(body), status


# ---------------------------------------------------------------- pagination
def pagination_params():
    raw_limit = request.args.get('limit')
    raw_offset = request.args.get('offset')
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        invalid('limit and offset must be integers')
    # PRD §2.3: limit default 10, min 1, max 100; offset default 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def list_response(items, serialize):
    """Lists sorted by creation timestamp ascending (PRD §2.3)."""
    items = sorted(items, key=lambda r: (r['_cts'], r['_seq']))
    limit, offset = pagination_params()
    total = len(items)
    page_items = items[offset:offset + limit]
    page = {
        'limit': limit,
        'offset': offset,
        'total_count': total,
        'has_more': offset + len(page_items) < total,
    }
    return respond([serialize(r) for r in page_items], 200, 'array', page)


# ---------------------------------------------------------------- auth
ROLES = {
    'SystemAdmin', 'AllocationManager', 'ProductionPlanner',
    'ComplianceOfficer', 'WarrantyAdministrator', 'DealerPrincipal', 'Any',
}


def auth_context():
    """Validation family 1: headers present, non-empty, declared role."""
    uid = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if (uid is None or not str(uid).strip()
            or role is None or not str(role).strip()
            or role not in ROLES):
        raise ApiError(400, ERR_AUTH,
                       'X-User-ID and X-User-Role headers must be present, '
                       'non-empty, and name a declared role')
    return uid, role


def require_roles(role, *allowed):
    """Validation family 2: role permitted for the endpoint."""
    if role not in allowed:
        raise ApiError(403, ERR_PERMS,
                       'Role %s is not permitted for this endpoint' % role)


# ---------------------------------------------------------------- body
def json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        invalid('Request body must be a JSON object')
    return data


def present(data, name):
    return name in data and data[name] is not None


def need(data, name):
    if not present(data, name):
        invalid('Missing required field: %s' % name)
    return data[name]


def as_str(v, name):
    if not isinstance(v, str) or not v.strip():
        invalid('Field %s must be a non-empty string' % name)
    return v


def as_int(v, name):
    if isinstance(v, bool) or not isinstance(v, int):
        invalid('Field %s must be an integer' % name)
    return v


def as_num(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        invalid('Field %s must be a number' % name)
    return v


def as_enum(v, name, allowed):
    if v not in allowed:
        invalid('Field %s must be one of %s' % (name, ', '.join(sorted(allowed))))
    return v


def as_date(v, name):
    d = parse_date(v)
    if d is None:
        invalid('Field %s must be a well-formed ISO date' % name)
    return d


def as_datetime(v, name):
    dt = parse_dt(v)
    if dt is None:
        invalid('Field %s must be a well-formed ISO 8601 datetime' % name)
    return dt


def get_or_404(coll, rid, error_id, label):
    rec = coll.get(rid)
    if rec is None:
        not_found(error_id, '%s not found: %s' % (label, rid))
    return rec
