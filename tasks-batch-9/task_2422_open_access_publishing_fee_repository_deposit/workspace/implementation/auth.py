"""Authentication, authorisation and ownership (PRD 2.1, precedence rules 1/2/4)."""
import functools

from flask import g, request

from errors import ApiError

ROLES = (
    "AgreementAdmin",
    "ScholCommLibrarian",
    "FundManager",
    "RepositoryCurator",
    "CorrespondingAuthor",
)

ALL_ROLES = list(ROLES)


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401)
    return user_id, role


def endpoint(roles):
    """Rule 1 then rule 2, before anything else about the request is inspected."""
    allowed = tuple(roles)

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            user_id, role = authenticate()
            if role not in allowed:
                raise ApiError("ERR_UNAUTHORIZED", 403)
            g.user_id = user_id
            g.role = role
            return view(*args, **kwargs)

        return wrapper

    return decorator


def require_owner(author_id):
    """Rule 4: only a CorrespondingAuthor is subject to the ownership check."""
    if g.role != "CorrespondingAuthor":
        return
    if author_id is None or author_id != g.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403)
