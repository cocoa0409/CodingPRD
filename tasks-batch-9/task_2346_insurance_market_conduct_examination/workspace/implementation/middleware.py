"""Authentication and role-based access control (PRD §2.1, bands 1-2 of §2.11)."""

import re
from functools import wraps

from flask import g, request

from errors import ApiError

ROLE_MARKET_ANALYST = "MarketAnalyst"
ROLE_EXAMINER_IN_CHARGE = "ExaminerInCharge"
ROLE_SUPERVISING_EXAMINER = "SupervisingExaminer"
ROLE_MULTISTATE_COORDINATOR = "MultistateCoordinator"
ROLE_INSURER_RESPONDENT = "InsurerRespondent"

ALL_ROLES = (
    ROLE_MARKET_ANALYST,
    ROLE_EXAMINER_IN_CHARGE,
    ROLE_SUPERVISING_EXAMINER,
    ROLE_MULTISTATE_COORDINATOR,
    ROLE_INSURER_RESPONDENT,
)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def is_uuid(value):
    return bool(value) and bool(_UUID_RE.match(value.strip()))


def authorize(*roles):
    """Require a well-formed X-User-ID and an X-User-Role inside the role set."""

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get(USER_ID_HEADER)
            if not user_id or not is_uuid(user_id):
                raise ApiError(
                    "ERR_UNAUTHENTICATED",
                    "A well-formed X-User-ID header is required.",
                )
            role = request.headers.get(USER_ROLE_HEADER)
            if role not in roles:
                raise ApiError(
                    "ERR_ROLE_NOT_PERMITTED",
                    "Role %s may not call this endpoint." % (role or "<missing>"),
                )
            g.user_id = user_id.strip()
            g.role = role
            return view(*args, **kwargs)

        return wrapper

    return decorator


def clock_authorize(view):
    """The logical-clock endpoint is the single exception to X-User-ID (PRD §2.1).

    All five roles may drive it; a role header carrying anything else is refused.
    """

    @wraps(view)
    def wrapper(*args, **kwargs):
        role = request.headers.get(USER_ROLE_HEADER)
        if role is not None and role not in ALL_ROLES:
            raise ApiError(
                "ERR_ROLE_NOT_PERMITTED",
                "Role %s may not call this endpoint." % role,
            )
        g.user_id = (request.headers.get(USER_ID_HEADER) or "").strip()
        g.role = role
        return view(*args, **kwargs)

    return wrapper


def current_user_id():
    return getattr(g, "user_id", None)


def current_role():
    return getattr(g, "role", None)


def is_respondent():
    return current_role() == ROLE_INSURER_RESPONDENT
