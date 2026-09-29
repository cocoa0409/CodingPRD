"""Header authentication, endpoint authorization and the request wrapper (PRD 2.1, 2.11)."""

import functools

from flask import request

import envelope
import store
from errors import ApiError

DIRECTOR = "LaborRelationsDirector"
ANALYST = "HRDataAnalyst"
COUNSEL = "EmploymentCounsel"
TRAINER = "SupervisorTrainer"
SUPERVISOR = "PlantSupervisor"
BOARD = "BoardAgent"
UNION = "UnionRepresentative"

ALL_ROLES = (DIRECTOR, ANALYST, COUNSEL, TRAINER, SUPERVISOR, BOARD, UNION)
ROLE_SET = frozenset(ALL_ROLES)


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLE_SET:
        raise ApiError("ERR_UNAUTHENTICATED",
                       "X-User-ID and a recognized X-User-Role are required.")
    return user_id, role


def endpoint(roles):
    """Wraps a handler with header authentication (step 1) then endpoint authorization (step 2)."""
    allowed = frozenset(roles)

    def decorator(handler):
        @functools.wraps(handler)
        def wrapper(**path_args):
            with store.LOCK:
                try:
                    user_id, role = authenticate()
                    if role not in allowed:
                        raise ApiError("ERR_ROLE_NOT_PERMITTED",
                                       "Role %s is not authorized for this endpoint." % role)
                    return handler(user_id=user_id, role=role, **path_args)
                except ApiError as exc:
                    return envelope.error_response(exc.error_id, exc.message, exc.http_status)
        return wrapper
    return decorator
