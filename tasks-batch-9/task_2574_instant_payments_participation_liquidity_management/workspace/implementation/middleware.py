"""Authentication, role checking and ParticipantAdmin ownership scope."""

from flask import request

from errors import ApiError

ROLES = (
    "NetworkOperator",
    "ParticipantAdmin",
    "LiquidityOfficer",
    "PaymentOperator",
    "FraudReviewer",
    "CoreBankingSystem",
)

PARTICIPANT_ADMIN = "ParticipantAdmin"


def caller():
    """Rung 1 of the rejection ladder: authentication."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "The X-User-ID header is required.")
    if role is None or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "The X-User-Role header is required.")
    role = str(role).strip()
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "The X-User-Role header names an unknown role.")
    return str(user_id).strip(), role


def authorize(allowed_roles):
    """Rungs 1 and 2: authentication then endpoint role membership."""
    user_id, role = caller()
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Role %s may not perform this operation." % role)
    return user_id, role


def require_scope(user_id, role, participant_id):
    """Rung 3: a ParticipantAdmin only ever acts inside its own participant."""
    if role != PARTICIPANT_ADMIN:
        return
    if participant_id is None or participant_id != user_id:
        raise ApiError(
            "ERR_PARTICIPANT_SCOPE_VIOLATION",
            "A ParticipantAdmin may only act within its own participant.",
        )


def scope_filter_value(user_id, role, requested):
    """Scope a list filter for a ParticipantAdmin caller.

    A ParticipantAdmin naming another participant in a filter is a scope
    violation; naming nothing is narrowed to its own participant.
    """
    if role != PARTICIPANT_ADMIN:
        return requested
    if requested is not None and requested != user_id:
        raise ApiError(
            "ERR_PARTICIPANT_SCOPE_VIOLATION",
            "A ParticipantAdmin may only list resources of its own participant.",
        )
    return user_id
