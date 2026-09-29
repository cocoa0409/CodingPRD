"""Auth header extraction, identity resolution and RBAC."""
from flask import request

import db
from errors import fail

ROLES = [
    "HRComplianceAdmin",
    "PolicyAuthor",
    "LegalCounsel",
    "LocalizationSpecialist",
    "Employee",
    "PeopleManager",
]

ENTITY_BACKED = {
    "Employee": "employees",
    "PeopleManager": "employees",
    "LegalCounsel": "legal_reviewers",
}

ALL_ROLES = list(ROLES)


class Actor(object):
    def __init__(self, user_id, role, entity=None):
        self.user_id = user_id
        self.role = role
        self.entity = entity

    @property
    def is_admin(self):
        return self.role == "HRComplianceAdmin"


def authorize(endpoint_roles):
    """Run screening steps 1-4 in the pinned order and return the Actor."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip() or not role or not role.strip():
        fail("ERR_MISSING_AUTH_HEADERS", "X-User-ID and X-User-Role headers are required")
    user_id = user_id.strip()
    role = role.strip()
    if role not in ROLES:
        fail("ERR_UNKNOWN_ROLE", "Unknown role: %s" % role)
    entity = None
    endpoint_roles = list(endpoint_roles)
    needs_identity = any(r in endpoint_roles for r in ("Employee", "PeopleManager", "LegalCounsel"))
    if needs_identity and role in ENTITY_BACKED:
        entity = db.get(ENTITY_BACKED[role], user_id)
        if entity is None:
            fail("ERR_ACTOR_IDENTITY_UNKNOWN", "Acting identity %s not found" % user_id)
    if role not in endpoint_roles:
        fail("ERR_ROLE_NOT_PERMITTED", "Role %s may not call this endpoint" % role)
    return Actor(user_id, role, entity)
