"""Auth header extraction and RBAC (PRD 2.1, precedence steps 1-4)."""
from flask import request

from db import db
from errors import ApiError

STUDIO_EXECUTIVE = "StudioExecutive"
SHOWRUNNER = "Showrunner"
WRITER = "Writer"
GUILD_ADMINISTRATOR = "GuildAdministrator"
LEGAL_COUNSEL = "LegalCounsel"

ALL_ROLES = (
    STUDIO_EXECUTIVE,
    SHOWRUNNER,
    WRITER,
    GUILD_ADMINISTRATOR,
    LEGAL_COUNSEL,
)

# PRD 2.1: Writer and Showrunner are entity-backed -- X-User-ID must be an
# existing Writer id. The other three roles carry opaque identifiers.
ENTITY_BACKED = (WRITER, SHOWRUNNER)


class Actor(object):
    __slots__ = ("user_id", "role", "writer")

    def __init__(self, user_id, role, writer):
        self.user_id = user_id
        self.role = role
        self.writer = writer


def require(*permitted):
    """Steps 1-4 of the validation precedence in PRD 2.11."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    # 1. both auth headers present and non-empty
    if user_id is None or role is None or str(user_id).strip() == "" or str(role).strip() == "":
        raise ApiError("ERR_MISSING_AUTH_HEADERS")
    user_id = str(user_id).strip()
    role = str(role).strip()
    # 2. the role is one of the five declared roles
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE")
    # 3. the role is permitted on this endpoint
    if permitted and role not in permitted:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    # 4. an entity-backed acting role resolves to an existing writer
    writer = None
    if role in ENTITY_BACKED:
        writer = db.writers.get(user_id)
        if writer is None:
            raise ApiError("ERR_ACTING_WRITER_NOT_FOUND")
    return Actor(user_id, role, writer)


def fetch(table, key, error_id):
    """Path/body resource resolution -- raises the table's not-found error."""
    if not isinstance(key, str):
        raise ApiError(error_id)
    row = table.get(key)
    if row is None:
        raise ApiError(error_id)
    return row
