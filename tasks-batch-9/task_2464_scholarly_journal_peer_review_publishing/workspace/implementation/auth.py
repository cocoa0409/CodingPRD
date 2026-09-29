"""Role-based access control and identity resolution (PRD Sections 2.1, 2.10)."""

from flask import request

from db import store
from errors import ApiError

ROLES = (
    "SystemAdmin",
    "EditorInChief",
    "HandlingEditor",
    "Reviewer",
    "Author",
    "ProductionStaff",
)

EDITOR_ROLES = ("EditorInChief", "HandlingEditor")
REQUIRED_LEVEL = {"EditorInChief": "CHIEF", "HandlingEditor": "HANDLING"}


class Actor:
    __slots__ = ("role", "user_id", "editor", "reviewer", "author")

    def __init__(self, role, user_id):
        self.role = role
        self.user_id = user_id
        self.editor = None
        self.reviewer = None
        self.author = None


def authorise(*allowed_roles):
    """Ladder rules 1-3 plus the role_level half of ERR_EDITOR_LEVEL_MISMATCH."""
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise ApiError("ERR_ROLE_HEADER_MISSING")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")

    user_id = request.headers.get("X-User-ID")
    actor = Actor(role, user_id)

    if role in EDITOR_ROLES:
        if not user_id or user_id not in store.editors:
            raise ApiError("ERR_IDENTITY_NOT_FOUND")
        actor.editor = store.editors[user_id]
        if actor.editor["role_level"] != REQUIRED_LEVEL[role]:
            raise ApiError("ERR_EDITOR_LEVEL_MISMATCH")
    elif role == "Reviewer":
        if not user_id or user_id not in store.reviewers:
            raise ApiError("ERR_IDENTITY_NOT_FOUND")
        actor.reviewer = store.reviewers[user_id]
    elif role == "Author":
        if not user_id or user_id not in store.authors:
            raise ApiError("ERR_IDENTITY_NOT_FOUND")
        actor.author = store.authors[user_id]
    return actor


def require_editor_journal(actor, manuscript):
    """An editor acting on a manuscript of another journal is a level mismatch."""
    if actor.editor is None:
        return
    if actor.editor["journal_id"] != manuscript["journal_id"]:
        raise ApiError("ERR_EDITOR_LEVEL_MISMATCH")
