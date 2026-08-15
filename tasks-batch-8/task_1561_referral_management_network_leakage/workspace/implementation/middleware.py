"""Auth header extraction and role checking (validation priorities 1 and 2)."""
from flask import request

from errors import fail

ROLES = {
    'NetworkAdmin',
    'ReferralCoordinator',
    'ReferringProvider',
    'SpecialistProvider',
    'ComplianceAuditor',
}

ALL_ROLES = list(ROLES)


def authenticate(allowed_roles):
    uid = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if not uid or not role or role not in ROLES:
        fail('ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER', 401,
             'X-User-ID and X-User-Role headers are required and role must be a declared role')
    if role not in allowed_roles:
        fail('ERR_UNAUTHORIZED_ROLE', 403, 'Role is not permitted for this endpoint')
    return uid, role
