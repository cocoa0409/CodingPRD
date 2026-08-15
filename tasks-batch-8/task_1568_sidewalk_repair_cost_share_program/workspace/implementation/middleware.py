"""Auth middleware: X-User-ID / X-User-Role headers, role gating, and
entity-backed identity resolution (PropertyOwner / Contractor)."""
from functools import wraps

from flask import g, request

import db as dbmod
from errors import ApiError, forbidden_role, not_found, unauthenticated

ROLES = {
    'ProgramCoordinator', 'Inspector', 'PropertyOwner', 'Contractor',
    'ForestryOfficer', 'FinanceOfficer', 'HearingOfficer',
}

ALL_ROLES = sorted(ROLES)


def authenticate():
    uid = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if not uid or not role or role not in ROLES:
        raise unauthenticated()
    if role == 'PropertyOwner' and uid not in dbmod.db.owners:
        raise not_found('owner')
    if role == 'Contractor' and uid not in dbmod.db.contractors:
        raise not_found('contractor')
    return uid, role


def require_roles(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid, role = authenticate()
            if role not in roles:
                raise forbidden_role()
            g.uid = uid
            g.role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco
