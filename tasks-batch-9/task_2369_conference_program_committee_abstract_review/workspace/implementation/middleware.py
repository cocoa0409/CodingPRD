"""Auth bands 1-3 (PRD sections 2.1 / 2.11)."""

from functools import wraps

from flask import g, request

from db import db
from errors import fail

ROLE_ADMIN = "ConferenceAdmin"
ROLE_CHAIR = "ProgramChair"
ROLE_REVIEWER = "Reviewer"
ROLE_AUTHOR = "Author"
ROLE_PRESS = "PressOfficer"

ALL_ROLES = (ROLE_ADMIN, ROLE_CHAIR, ROLE_REVIEWER, ROLE_AUTHOR, ROLE_PRESS)

ENTITY_BACKED = (ROLE_CHAIR, ROLE_REVIEWER, ROLE_AUTHOR)


class Actor(object):
    __slots__ = ("user_id", "role", "member", "author")

    def __init__(self, user_id, role, member=None, author=None):
        self.user_id = user_id
        self.role = role
        self.member = member
        self.author = author

    @property
    def is_admin(self):
        return self.role == ROLE_ADMIN

    @property
    def is_chair(self):
        return self.role == ROLE_CHAIR

    @property
    def is_reviewer(self):
        return self.role == ROLE_REVIEWER

    @property
    def is_author(self):
        return self.role == ROLE_AUTHOR

    @property
    def is_press(self):
        return self.role == ROLE_PRESS

    @property
    def member_id(self):
        return self.member["id"] if self.member else None

    @property
    def author_id(self):
        return self.author["id"] if self.author else None


def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")

    # Band 1 — headers present, non-empty, role recognised.
    if not user_id or not user_id.strip() or not role or not role.strip():
        fail("ERR_MISSING_AUTH_HEADERS")
    user_id = user_id.strip()
    role = role.strip()
    if role not in ALL_ROLES:
        fail("ERR_MISSING_AUTH_HEADERS", "X-User-Role is not a recognised role name.")

    # Band 2 — role authorised for this endpoint.
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED")

    # Band 3 — entity-backed identity resolution.
    member = None
    author = None
    if role == ROLE_CHAIR:
        member = db.members.get(user_id)
        if member is None or member["member_role"] != "CHAIR":
            fail("ERR_IDENTITY_NOT_FOUND")
    elif role == ROLE_REVIEWER:
        member = db.members.get(user_id)
        if member is None or member["member_role"] != "REVIEWER":
            fail("ERR_IDENTITY_NOT_FOUND")
    elif role == ROLE_AUTHOR:
        author = db.authors.get(user_id)
        if author is None:
            fail("ERR_IDENTITY_NOT_FOUND")

    actor = Actor(user_id, role, member, author)
    g.actor = actor
    return actor


def endpoint(*allowed_roles):
    """Decorator: performs auth bands 1-3, then hands `actor` to the view."""

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            actor = authenticate(allowed_roles)
            return view(actor, *args, **kwargs)

        return wrapper

    return decorator
