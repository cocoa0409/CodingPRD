"""Authentication & RBAC helpers.

PRD §2.1: every request carries two mandatory headers:
  - X-User-ID   : the acting user's id (the Patron.id when role is Patron;
                  an opaque operator id for Librarian / BranchManager)
  - X-User-Role : one of exactly Patron, Librarian, BranchManager

Missing/unknown role or missing id -> ERR_UNAUTHENTICATED (401).
Role not permitted for the operation -> ERR_FORBIDDEN (403).
A Patron acting on a resource it does not own -> ERR_FORBIDDEN (403).
"""

from flask import request

import errors

ROLE_PATRON = "Patron"
ROLE_LIBRARIAN = "Librarian"
ROLE_MANAGER = "BranchManager"

KNOWN_ROLES = {ROLE_PATRON, ROLE_LIBRARIAN, ROLE_MANAGER}


class Caller:
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_patron(self):
        return self.role == ROLE_PATRON

    @property
    def is_librarian(self):
        return self.role == ROLE_LIBRARIAN

    @property
    def is_manager(self):
        return self.role == ROLE_MANAGER


def authenticate():
    """Validate auth headers (priority 1) and return a Caller, or raise."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise errors.unauthenticated()
    return Caller(user_id, role)


def require_roles(caller, allowed):
    """Authorization (priority 2): the caller's role must be in `allowed`."""
    if caller.role not in allowed:
        raise errors.forbidden()


def require_owner_if_patron(caller, owner_patron_id):
    """A Patron may only act on a resource whose patron_id == X-User-ID.
    Librarians and managers are exempt from the ownership comparison.
    """
    if caller.is_patron and caller.user_id != owner_patron_id:
        raise errors.forbidden()
