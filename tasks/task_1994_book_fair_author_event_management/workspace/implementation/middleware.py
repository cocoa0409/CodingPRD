"""Auth header extraction and role checking (PRD section 2.1, validations 1-4)."""

from functools import wraps

from flask import g, request

import db
from errors import fail

ALL_ROLES = ("Organizer", "SchoolCoordinator", "PublisherRep", "AuthorRep", "Cashier", "LineStaff")

# Entity-backed roles: X-User-ID is the id of a Party of this kind.
ENTITY_ROLE_KIND = {
    "SchoolCoordinator": "SCHOOL",
    "PublisherRep": "PUBLISHER",
    "AuthorRep": "AUTHOR",
}


def require_roles(*roles):
    """Decorator enforcing the auth ladder: headers -> role -> party -> kind."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role:
                fail("ERR_MISSING_HEADERS", "X-User-ID and X-User-Role headers are required")
            if role not in roles:
                fail("ERR_ROLE_FORBIDDEN", "Role %s is not authorized for this endpoint" % role)
            party = None
            if role in ENTITY_ROLE_KIND:
                party = db.parties.get(user_id)
                if party is None:
                    fail("ERR_PARTY_NOT_FOUND", "X-User-ID references no existing Party")
                if party["kind"] != ENTITY_ROLE_KIND[role]:
                    fail(
                        "ERR_ROLE_PARTY_KIND_MISMATCH",
                        "Party kind %s does not match role %s" % (party["kind"], role),
                    )
            g.user_id = user_id
            g.role = role
            g.party = party
            return fn(*args, **kwargs)

        return wrapper

    return deco


def require_scope(party_id):
    """Priority-6 party-scope check for entity-backed roles (PRD section 2.10)."""
    if g.role in ENTITY_ROLE_KIND and g.party["id"] != party_id:
        fail("ERR_PARTY_SCOPE_MISMATCH", "Acting party is not the resource's scoped party")
