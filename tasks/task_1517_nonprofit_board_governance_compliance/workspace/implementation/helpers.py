"""Response envelope, errors, auth, validation, date and pagination helpers."""
import calendar
import secrets
import uuid
from datetime import datetime, timezone

from flask import jsonify, request

import store


# ---------------------------------------------------------------- errors
class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def err400(msg):
    return ApiError('ERR_INVALID_REQUEST', 400, msg)


# ---------------------------------------------------------------- envelope
def _req_id():
    return 'req_' + secrets.token_hex(12)


def iso(dt):
    """ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f'{dt.microsecond // 1000:03d}Z'


def now_iso():
    return iso(store.get_clock())


def envelope(data, response_type='object', status=200, pagination=None):
    meta = {'api_request_id': _req_id(), 'api_request_timestamp': now_iso()}
    if pagination is not None:
        meta.update(pagination)
    body = {'meta': meta, 'response_type': response_type, 'data': data}
    return jsonify(body), status


def error_envelope(err):
    body = {
        'meta': {'api_request_id': _req_id(), 'api_request_timestamp': now_iso()},
        'response_type': 'error',
        'data': {'error_id': err.error_id, 'message': err.message},
    }
    return jsonify(body), err.status


# ---------------------------------------------------------------- dates
def parse_dt(value, field='date'):
    if not isinstance(value, str):
        raise err400(f'{field} must be an ISO 8601 string')
    t = value.strip()
    if t.endswith('Z'):
        t = t[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise err400(f'{field} must be a valid ISO 8601 datetime')
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def last_day(year, month):
    return calendar.monthrange(year, month)[1]


def add_years(dt, n):
    try:
        return dt.replace(year=dt.year + n)
    except ValueError:  # Feb 29 -> Feb 28
        return dt.replace(year=dt.year + n, day=28)


def add_months(dt, n):
    m = dt.month - 1 + n
    y = dt.year + m // 12
    m = m % 12 + 1
    d = min(dt.day, last_day(y, m))
    return dt.replace(year=y, month=m, day=d)


def new_id():
    return str(uuid.uuid4())


def new_entity():
    ts = now_iso()
    return {'id': new_id(), 'created_at': ts, 'updated_at': ts, 'version': 1,
            '_seq': store.next_seq()}


def touch(e):
    e['updated_at'] = now_iso()
    e['version'] += 1


# ---------------------------------------------------------------- auth
ALL_ROLES = ['GovernanceAdmin', 'BoardChair', 'BoardDirector', 'Treasurer',
             'ComplianceOfficer', 'ExecutiveDirector']
ENTITY_ROLES = {'BoardChair', 'BoardDirector', 'Treasurer'}


def authn():
    """Priority 1: header presence."""
    uid = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if not uid or not uid.strip() or not role or not role.strip():
        raise ApiError('ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER', 400,
                       'X-User-ID and X-User-Role headers must be present and non-empty')
    return uid, role


def require_role(role, allowed):
    """Priority 2: role authorization."""
    if role not in allowed:
        raise ApiError('ERR_FORBIDDEN_FOR_ROLE', 403,
                       f'Role {role} is not authorized for this operation')


def qualified_member(uid, role):
    """Priority 3 (basic): entity-backed role qualification — the caller must
    resolve to an ACTIVE BoardMember with the matching officer_role."""
    if role not in ENTITY_ROLES:
        return None
    m = store.members.get(uid)
    if m is None or m['status'] != 'ACTIVE':
        raise ApiError('ERR_IDENTITY_NOT_QUALIFIED', 403,
                       'X-User-ID is not an ACTIVE BoardMember')
    if role == 'BoardChair' and m['officer_role'] != 'CHAIR':
        raise ApiError('ERR_IDENTITY_NOT_QUALIFIED', 403,
                       'BoardChair requires officer_role CHAIR')
    if role == 'Treasurer' and m['officer_role'] != 'TREASURER':
        raise ApiError('ERR_IDENTITY_NOT_QUALIFIED', 403,
                       'Treasurer requires officer_role TREASURER')
    return m


def check_org_membership(member, role, nonprofit_id):
    """Priority 3 (org scope): the member must belong to the nonprofit being
    acted on."""
    if role not in ENTITY_ROLES or nonprofit_id is None:
        return
    if member is None or member['nonprofit_id'] != nonprofit_id:
        raise ApiError('ERR_IDENTITY_NOT_QUALIFIED', 403,
                       'BoardMember does not belong to the nonprofit being acted on')


# ---------------------------------------------------------------- body validation
def get_body():
    return request.get_json(silent=True) or {}


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def v_str(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err400(f'{field} is required')
        return default
    v = body[field]
    if not isinstance(v, str) or not v.strip():
        raise err400(f'{field} must be a non-empty string')
    return v


def v_int(body, field, required=True, default=None, min_v=None, max_v=None):
    if field not in body or body[field] is None:
        if required:
            raise err400(f'{field} is required')
        return default
    v = body[field]
    if not _is_int(v):
        raise err400(f'{field} must be an integer')
    if min_v is not None and v < min_v:
        raise err400(f'{field} must be >= {min_v}')
    if max_v is not None and v > max_v:
        raise err400(f'{field} must be <= {max_v}')
    return v


def v_bool(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err400(f'{field} is required')
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err400(f'{field} must be a boolean')
    return v


def v_dt(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err400(f'{field} is required')
        return default
    return parse_dt(body[field], field)


def v_list(body, field, required=True, default=None, non_empty=False):
    if field not in body or body[field] is None:
        if required:
            raise err400(f'{field} is required')
        return default
    v = body[field]
    if not isinstance(v, list):
        raise err400(f'{field} must be a list')
    if non_empty and len(v) == 0:
        raise err400(f'{field} must be non-empty')
    return v


def v_enum(body, field, allowed, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err400(f'{field} is required')
        return default
    v = body[field]
    if v not in allowed:
        raise err400(f'{field} must be one of {sorted(allowed)}')
    return v


# ---------------------------------------------------------------- lookup helpers
def lookup(table, rid):
    e = table.get(rid)
    if e is None:
        raise ApiError('ERR_NOT_FOUND', 404, f'Resource {rid} not found')
    return e


def ref_lookup(table, rid, field, nonprofit_id=None):
    e = table.get(rid)
    if e is None or (nonprofit_id is not None and
                     e.get('nonprofit_id') != nonprofit_id):
        raise ApiError('ERR_REFERENCED_NOT_FOUND', 422,
                       f'{field} does not reference an existing resource of this nonprofit')
    return e


# ---------------------------------------------------------------- pagination
def pagination_params():
    raw_limit = request.args.get('limit')
    raw_offset = request.args.get('offset')
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err400('limit must be an integer')
        limit = max(1, min(100, limit))
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err400('offset must be an integer')
        offset = max(0, offset)
    return limit, offset


def list_response(items, serialize):
    """items: entity dicts; sorts by created_at asc and paginates."""
    items = sorted(items, key=lambda e: (e['created_at'], e['_seq']))
    total = len(items)
    limit, offset = pagination_params()
    page = items[offset:offset + limit]
    pagination = {
        'limit': limit,
        'offset': offset,
        'total_count': total,
        'has_more': offset + len(page) < total,
    }
    return envelope([serialize(e) for e in page], response_type='array',
                    pagination=pagination)


def apply_filters(items, filters):
    """filters: dict of field -> raw query value (None means not provided)."""
    out = items
    for field, raw in filters.items():
        if raw is None:
            continue
        out = [e for e in out if _filter_match(e, field, raw)]
    return out


def _filter_match(e, field, raw):
    v = e.get(field)
    if isinstance(v, int) and not isinstance(v, bool):
        try:
            return v == int(raw)
        except (TypeError, ValueError):
            return False
    return v == raw
