"""Auth header extraction and role/ownership checks (PRD §2.1, pipeline
stages 1-2)."""
from flask import request

from errors import ApiError

ROLES = {'Anonymous', 'Parent', 'Consultant', 'PracticeAdmin'}


def user_context():
    uid = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if not uid or not role or role not in ROLES:
        raise ApiError('ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER', 400,
                       'X-User-ID and X-User-Role headers must be present and '
                       'the role must be recognized')
    return uid, role


def require_role(role, *allowed):
    if role not in allowed:
        raise ApiError('ERR_FORBIDDEN', 403,
                       'Role not permitted for this endpoint')


def forbidden(message='Identity does not match the resource owner or assignee'):
    raise ApiError('ERR_FORBIDDEN', 403, message)


def check_parent_owns_case(uid, role, case):
    if role == 'Parent' and case['family_id'] != uid:
        forbidden()


def check_consultant_assigned(uid, role, case):
    if role == 'Consultant' and case['consultant_id'] != uid:
        forbidden()
