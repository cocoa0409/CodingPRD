"""Authentication and RBAC: PRD 2.1 and 2.8 rungs 1 through 5."""

from functools import wraps

from flask import request

from errors import ApiError
from store import db

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

ROLE_CHIEF = "ChiefPerfusionist"
ROLE_PERFUSIONIST = "Perfusionist"
ROLE_SURGEON = "Surgeon"
ROLE_CONTRACT_ADMIN = "ContractAdmin"
ROLE_BIOMED = "BiomedTech"

ALL_ROLES = (ROLE_CHIEF, ROLE_PERFUSIONIST, ROLE_SURGEON, ROLE_CONTRACT_ADMIN, ROLE_BIOMED)

PERFUSIONIST_BACKED = (ROLE_CHIEF, ROLE_PERFUSIONIST)
SURGEON_BACKED = (ROLE_SURGEON,)


class Actor(object):
    def __init__(self, user_id, role, perfusionist=None, surgeon=None):
        self.user_id = user_id
        self.role = role
        self.perfusionist = perfusionist
        self.surgeon = surgeon

    @property
    def is_chief_role(self):
        return self.role == ROLE_CHIEF

    @property
    def perfusionist_id(self):
        return self.perfusionist["id"] if self.perfusionist else None


def authenticate(allowed_roles):
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)

    # Rung 1 -- both headers present and non-empty.
    if not user_id or not str(user_id).strip() or not role or not str(role).strip():
        raise ApiError("ERR_MISSING_AUTH_HEADERS")
    user_id = str(user_id)
    role = str(role)

    # Rung 2 -- the role names one of the five recognised roles.
    if role not in ALL_ROLES:
        raise ApiError("ERR_INVALID_ROLE")

    # Rung 3 -- the role is admitted by this endpoint.
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")

    actor = Actor(user_id, role)

    # Rung 4 -- entity-backed identities must resolve.
    if role in PERFUSIONIST_BACKED:
        row = db.perfusionists.get(user_id)
        if row is None:
            raise ApiError("ERR_ACTOR_NOT_FOUND")
        actor.perfusionist = row
    elif role in SURGEON_BACKED:
        row = db.surgeons.get(user_id)
        if row is None:
            raise ApiError("ERR_ACTOR_NOT_FOUND")
        actor.surgeon = row

    # Rung 5 -- a caller acting as ChiefPerfusionist must be flagged is_chief.
    if role == ROLE_CHIEF and not actor.perfusionist.get("is_chief"):
        raise ApiError("ERR_NOT_CHIEF_PERFUSIONIST")

    return actor


def endpoint(roles):
    """Wrap a handler with the auth ladder and whole-request serialisation."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            with db.lock:
                actor = authenticate(tuple(roles))
                return fn(actor, *args, **kwargs)

        return wrapper

    return decorator
