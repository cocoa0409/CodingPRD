"""Auth header extraction, role checks, body/field validators, pagination."""
import re

from flask import request

import db
from errors import (
    ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED, ERR_INVALID_REQUEST,
    ERR_INVALID_FORMAT, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_ALREADY_TERMINAL,
    ERR_CLIENT_NOT_OWNER, ERR_ENGINEER_NOT_ASSIGNED,
)

ROLES = ('Client', 'Engineer', 'QAChecker', 'StudioManager')

UPC_RE = re.compile(r'^[0-9]{12}$')
ISRC_RE = re.compile(r'^[A-Z]{2}[A-Z0-9]{3}[0-9]{7}$')
SHA256_RE = re.compile(r'^[0-9a-f]{64}$')

# Terminal states with no outgoing transitions: further actions -> ERR_ALREADY_TERMINAL
TERMINAL_NO_EXIT = {
    'Client': {'TERMINATED'},
    'Project': {'CANCELLED'},
    'SessionSlot': {'RELEASED', 'CONSUMED', 'CANCELLED'},
    'SourceAsset': {'PASSED', 'WAIVED'},
    'RevisionRound': {'APPROVED', 'REJECTED', 'EXPIRED'},
    'Deliverable': {'RETIRED'},
    'MetadataTag': {'VERIFIED', 'REVOKED'},
    'ArchiveBundle': {'RESTORED', 'FAILED'},
}


def auth():
    """Guard priority 1: authentication."""
    uid = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if not uid or not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401,
                       'X-User-ID and X-User-Role headers are required and role must be declared')
    return uid, role


def require_roles(role, allowed):
    """Guard priority 2: authorization."""
    if role not in allowed:
        raise ApiError(ERR_UNAUTHORIZED, 403, 'Role does not have permission for this endpoint')


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, 'Request body must be a JSON object')
    return data


def req_field(data, field):
    if field not in data or data[field] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, 'Missing required field: %s' % field)
    return data[field]


def opt_field(data, field, default=None):
    val = data.get(field, default)
    return val


def as_str(val, field):
    if not isinstance(val, str) or val == '':
        raise ApiError(ERR_INVALID_REQUEST, 400, 'Field %s must be a non-empty string' % field)
    return val


def as_int(val, field):
    if isinstance(val, bool) or not isinstance(val, int):
        raise ApiError(ERR_INVALID_REQUEST, 400, 'Field %s must be an integer' % field)
    return val


def as_num(val, field):
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ApiError(ERR_INVALID_REQUEST, 400, 'Field %s must be a number' % field)
    return val


def as_bool(val, field):
    if not isinstance(val, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, 'Field %s must be a boolean' % field)
    return val


def as_enum(val, field, allowed):
    if not isinstance(val, str) or val not in allowed:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       'Field %s must be one of %s' % (field, ', '.join(allowed)))
    return val


def as_datetime(val, field):
    try:
        return db.parse_dt(val)
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_FORMAT, 400, 'Field %s has an invalid datetime format' % field)


def pagination_args():
    limit = 10
    offset = 0
    raw_limit = request.args.get('limit')
    raw_offset = request.args.get('offset')
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise ApiError(ERR_INVALID_REQUEST, 400, 'limit must be an integer')
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, 400, 'limit must be between 1 and 100')
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise ApiError(ERR_INVALID_REQUEST, 400, 'offset must be an integer')
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, 'offset must be >= 0')
    return limit, offset


def bool_filter(param):
    raw = request.args.get(param)
    if raw is None:
        return None
    if raw.lower() == 'true':
        return True
    if raw.lower() == 'false':
        return False
    raise ApiError(ERR_INVALID_REQUEST, 400, '%s must be true or false' % param)


def get_or_404(store, rid):
    rec = store.get(rid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 404, 'Resource not found: %s' % rid)
    return rec


def ensure_state(entity, rec, status_field, allowed):
    """Guard priority 5: state admissibility with terminal-state distinction."""
    st = rec[status_field]
    if st in allowed:
        return st
    if st in TERMINAL_NO_EXIT.get(entity, set()):
        raise ApiError(ERR_ALREADY_TERMINAL, 409,
                       '%s is already in terminal state %s' % (entity, st))
    raise ApiError(ERR_INVALID_STATE, 409,
                   '%s in state %s does not permit the requested transition' % (entity, st))


def check_client_owner(uid, role, project):
    if role == 'Client' and project['client_id'] != uid:
        raise ApiError(ERR_CLIENT_NOT_OWNER, 403,
                       'Client attempting action on a project they do not own')


def check_client_owner_id(uid, role, client_id):
    if role == 'Client' and client_id != uid:
        raise ApiError(ERR_CLIENT_NOT_OWNER, 403,
                       'Client attempting action on a resource they do not own')


def check_engineer_assigned(uid, role, project):
    if role == 'Engineer' and project.get('assigned_engineer_id') != uid:
        raise ApiError(ERR_ENGINEER_NOT_ASSIGNED, 403,
                       'Engineer attempting action on a project not assigned to them')
