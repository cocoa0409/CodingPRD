"""Authentication, endpoint authorisation and resource-ownership checks.

PRD 2.1: every request carries X-User-ID and X-User-Role. The six roles are
PlatformAdmin, Organizer, FinanceAdmin, Attendee, SpeakerUser, SponsorUser.
"""

from flask import g, request

from errors import ApiError

ROLES = (
    "PlatformAdmin",
    "Organizer",
    "FinanceAdmin",
    "Attendee",
    "SpeakerUser",
    "SponsorUser",
)


def authenticate():
    """Priority 1: headers present and role recognised."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.role = role


def authorize(*roles):
    """Priority 2: the acting role appears in the endpoint's role list."""
    if g.role not in roles:
        raise ApiError("ERR_UNAUTHORIZED")


def own_event(event):
    """Organizer ownership: X-User-ID must equal Event.organizer_user_id."""
    if g.role == "Organizer" and g.user_id != event.get("organizer_user_id"):
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def own_entity(expected_id):
    """Entity-backed ownership: X-User-ID must equal the given foreign key."""
    if g.user_id != expected_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
