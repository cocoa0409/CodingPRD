"""Authentication, role authorization and ownership scope (PRD 2.1, 2.7).

Screening order is the contract: 1 authentication, 2 role authorization
(including sub-operation ownership on the three multiplexing endpoints),
3 path resolution, 4 ownership scope.
"""

import functools

from flask import g, request

from errors import api_error

STATE_OFFICER = "StateAssessmentOfficer"
DISTRICT_COORDINATOR = "DistrictTestCoordinator"
SCHOOL_COORDINATOR = "SchoolTestCoordinator"
PROCTOR = "Proctor"

ALL_ROLES = (STATE_OFFICER, DISTRICT_COORDINATOR, SCHOOL_COORDINATOR, PROCTOR)
ROLE_SET = set(ALL_ROLES)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


class Actor:
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def json_body():
    """Request body as a dict; a missing or non-object body reads as empty."""
    if not hasattr(g, "json_body"):
        payload = request.get_json(silent=True)
        g.json_body = payload if isinstance(payload, dict) else {}
    return g.json_body


def authenticate():
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if not user_id or not user_id.strip():
        raise api_error("ERR_UNAUTHENTICATED")
    if not role or not role.strip():
        raise api_error("ERR_UNAUTHENTICATED")
    if role not in ROLE_SET:
        raise api_error("ERR_UNAUTHENTICATED")
    return Actor(user_id, role)


# --------------------------------------------------------------------------
# Sub-operation ownership on the three multiplexing endpoints (PRD 2.1)
# --------------------------------------------------------------------------
SESSION_TO_STATUS_VALUES = {"SCHEDULED", "ACTIVE", "CLOSED", "CANCELLED"}
SESSION_ROLE_OPERATIONS = {
    SCHOOL_COORDINATOR: {"SCHEDULED", "CANCELLED"},
    PROCTOR: {"ACTIVE", "CLOSED"},
}

REPORT_TO_STATUS_VALUES = {"SUBMITTED", "WITHDRAWN", "UNDER_REVIEW", "RETURNED_FOR_INFO", "ADJUDICATED"}
REPORT_ROLE_OPERATIONS = {
    PROCTOR: {"SUBMITTED", "WITHDRAWN"},
    STATE_OFFICER: {"UNDER_REVIEW", "RETURNED_FOR_INFO", "ADJUDICATED"},
}

CUSTODY_EVENT_TYPES = {
    "RECEIPT",
    "TRANSFER_TO_SCHOOL",
    "SESSION_CHECKOUT",
    "SESSION_CHECKIN",
    "RETURN_TO_DISTRICT",
    "DESTRUCTION",
}
CUSTODY_ROLE_OPERATIONS = {
    DISTRICT_COORDINATOR: {"RECEIPT", "DESTRUCTION"},
    SCHOOL_COORDINATOR: {"TRANSFER_TO_SCHOOL", "RETURN_TO_DISTRICT"},
    PROCTOR: {"SESSION_CHECKOUT", "SESSION_CHECKIN"},
}


def _sub_operation_guard(field, declared_values, ownership):
    def guard(actor):
        requested = json_body().get(field)
        # A value that is not a declared member of the field's enum is a body
        # well-formedness problem (check 5), not a role problem.
        if not isinstance(requested, str) or requested not in declared_values:
            return
        if requested not in ownership.get(actor.role, set()):
            raise api_error("ERR_ROLE_NOT_PERMITTED")

    return guard


session_transition_guard = _sub_operation_guard(
    "to_status", SESSION_TO_STATUS_VALUES, SESSION_ROLE_OPERATIONS
)
report_transition_guard = _sub_operation_guard(
    "to_status", REPORT_TO_STATUS_VALUES, REPORT_ROLE_OPERATIONS
)
custody_event_guard = _sub_operation_guard(
    "event_type", CUSTODY_EVENT_TYPES, CUSTODY_ROLE_OPERATIONS
)


def endpoint(*roles, **options):
    """Wrap a view with check 1 (authentication) and check 2 (role authorization)."""
    sub_operation = options.get("sub_operation")
    allowed = set(roles)

    def decorator(view):
        @functools.wraps(view)
        def wrapper(**kwargs):
            actor = authenticate()
            if actor.role not in allowed:
                raise api_error("ERR_ROLE_NOT_PERMITTED")
            if sub_operation is not None:
                sub_operation(actor)
            return view(actor, **kwargs)

        return wrapper

    return decorator


# --------------------------------------------------------------------------
# Check 3 — path resolution, left to right
# --------------------------------------------------------------------------
def resolve(collection, identifier, error_id):
    entity = collection.get(identifier)
    if entity is None:
        raise api_error(error_id)
    return entity


# --------------------------------------------------------------------------
# Check 4 — ownership scope
# --------------------------------------------------------------------------
def scope_violation():
    raise api_error("ERR_SCOPE_VIOLATION")


def require_scope(condition):
    if not condition:
        scope_violation()


def body_reference(field):
    """A body-supplied identifier used by a scope check. Absent or non-string
    values defer to body well-formedness (check 5) / body resolution (check 6)."""
    value = json_body().get(field)
    if isinstance(value, str) and value.strip():
        return value
    return None
