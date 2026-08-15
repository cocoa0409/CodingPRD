"""Auth header extraction and role checking per PRD 2.1."""
from flask import request

from errors import ApiError

ROLES = {'Organizer', 'RegistrationDesk', 'Participant', 'Judge', 'Vendor'}


def get_auth():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED."""
    user_id = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if not user_id or not role or role not in ROLES:
        raise ApiError('ERR_UNAUTHENTICATED', 401,
                       'Missing or unrecognized X-User-Role / X-User-ID headers')
    return user_id, role


def require_roles(*allowed):
    """Authenticate and check endpoint role grant."""
    user_id, role = get_auth()
    if role not in allowed:
        raise ApiError('ERR_FORBIDDEN', 403, 'Role not permitted for this endpoint')
    return user_id, role


def check_participant_owns(user_id, role, registrant_id):
    if role == 'Participant' and registrant_id != user_id:
        raise ApiError('ERR_OWNERSHIP_VIOLATION', 403,
                       'Participant may act only on own resources')


def check_judge_owns(user_id, role, judge_id):
    if role == 'Judge' and judge_id != user_id:
        raise ApiError('ERR_OWNERSHIP_VIOLATION', 403,
                       'Judge may act only on own score sheets')


def check_vendor_owns(user_id, role, application_id):
    if role == 'Vendor' and application_id != user_id:
        raise ApiError('ERR_OWNERSHIP_VIOLATION', 403,
                       'Vendor may act only on own booth application')
