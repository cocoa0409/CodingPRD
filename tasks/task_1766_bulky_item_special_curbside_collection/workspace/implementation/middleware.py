"""Auth header extraction, role checking, Resident ownership checks (PRD 2.1)."""
import re
from datetime import datetime, timezone

from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN, ERR_INVALID_REQUEST

ROLES = {'Resident', 'Driver', 'Inspector', 'Dispatcher'}

_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def actor():
    """Priority 1: X-User-Role and X-User-ID present; role recognized."""
    uid = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if not uid or not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED,
                       'Missing or unrecognized X-User-Role / X-User-ID headers', 401)
    return uid, role


def require_roles(*roles):
    """Priority 2 (role part): role permitted on this endpoint."""
    uid, role = actor()
    if role not in roles:
        raise ApiError(ERR_FORBIDDEN, 'Role not permitted on this endpoint', 403)
    return uid, role


def require_own_household(uid, household_id):
    """Priority 2 (ownership part): Resident X-User-ID must equal owning Household id."""
    if uid != household_id:
        raise ApiError(ERR_FORBIDDEN,
                       'Resident does not own the household-scoped resource', 403)


def body_json():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 'Request body must be a JSON object', 400)
    return data


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_bool(v):
    return isinstance(v, bool)


def parse_datetime(value):
    """Parse ISO 8601 datetime (accepts trailing Z or offset); normalize to UTC."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith('Z') or s.endswith('z'):
        s = s[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Strict ISO yyyy-mm-dd -> date, else None."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        return None
