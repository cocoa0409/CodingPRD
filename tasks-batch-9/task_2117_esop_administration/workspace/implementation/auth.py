"""Authentication, RBAC and the request wrapper (PRD 2.1, validation 1 and 2).

Every request must carry X-User-ID and X-User-Role.  X-User-Role must name one
of the five declared roles.  PlanSponsor, Appraiser, Trustee and
PlanAdministrator are opaque operator identities; Participant is entity-backed
and its X-User-ID is the id of the acting Participant record.
"""

import sys
import traceback
from functools import wraps

from flask import g, request

import responses
from db import LOCK
from errors import ApiError, fail

PLAN_SPONSOR = "PlanSponsor"
APPRAISER = "Appraiser"
TRUSTEE = "Trustee"
PLAN_ADMINISTRATOR = "PlanAdministrator"
PARTICIPANT = "Participant"

DECLARED_ROLES = (PLAN_SPONSOR, APPRAISER, TRUSTEE, PLAN_ADMINISTRATOR, PARTICIPANT)

# Every GET except the repurchase forecast is open to all five roles.
ALL_ROLES = list(DECLARED_ROLES)
READ_ROLES = [PLAN_SPONSOR, TRUSTEE, PLAN_ADMINISTRATOR, APPRAISER, PARTICIPANT]
FORECAST_ROLES = [PLAN_SPONSOR, TRUSTEE, PLAN_ADMINISTRATOR]


def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role or user_role not in DECLARED_ROLES:
        fail("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.user_role = user_role
    if user_role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE")


def caller_id():
    return g.get("user_id")


def caller_role():
    return g.get("user_role")


def is_participant_caller():
    return g.get("user_role") == PARTICIPANT


def endpoint(roles):
    """Wrap a view: serialise, authenticate, authorize, envelope errors."""

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            with LOCK:
                try:
                    authenticate(roles)
                    return view(*args, **kwargs)
                except ApiError as exc:
                    return responses.error(exc.error_id, exc.message, exc.http_status)
                except Exception:  # pragma: no cover - defensive
                    traceback.print_exc(file=sys.stderr)
                    return responses.error(
                        "ERR_INVALID_REQUEST",
                        "The request could not be processed.",
                        400,
                    )

        return wrapper

    return decorator
