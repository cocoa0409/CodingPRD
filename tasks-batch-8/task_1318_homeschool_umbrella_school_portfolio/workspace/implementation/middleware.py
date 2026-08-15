"""Route decorator implementing the §2.8 validation pipeline steps 1-4:
auth header presence -> role admissibility -> parent ownership -> path existence."""
from functools import wraps

from flask import request

from errors import raise_err
from services import core
from validation import ROLES

ALL_ROLES = ["Parent", "Reviewer", "Registrar", "AcademicDirector", "StateAuditor"]


def route(roles, ownership=None, parent_chain=()):
    """Decorator.

    roles: list of admitted X-User-Role values (or ALL_ROLES).
    ownership: (kind, view_kwarg) — when role is Parent, X-User-ID must equal the
        root family id of that entity. Nonexistent entities skip the check here
        (existence 404 follows in step 4).
    parent_chain: ((kind, kwarg, table), ...) resolved left-to-right for 404 and,
        for Parent callers, ownership along the path.
    """
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            # 1. header presence and shape
            if uid is None or uid.strip() == "" or role is None or role.strip() == "":
                raise_err("ERR_MISSING_OR_INVALID_AUTH_HEADER",
                          "X-User-ID and X-User-Role headers are required")
            # 2. role admissibility
            if role not in ROLES or role not in roles:
                raise_err("ERR_FORBIDDEN_ROLE", f"Role {role} is not permitted here")

            # Resolve the ownership anchor entity (may be None if missing)
            anchor = None
            if ownership is not None:
                kind, kwarg = ownership
                anchor = core.root_family_id(kind, kwargs.get(kwarg))

            # 3. parent ownership (when the target family subtree exists)
            if role == "Parent":
                if anchor is not None and uid != anchor:
                        raise_err("ERR_OWNERSHIP_MISMATCH",
                                  "Parent may only access own family's subtree")

            # 4. path existence, left-to-right
            for kind, kwarg, table in parent_chain:
                rec = table.get(kwargs.get(kwarg))
                if rec is None:
                    raise_err("ERR_NOT_FOUND", f"{kind} {kwargs.get(kwarg)} not found")

            request.user_id = uid
            request.user_role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco
