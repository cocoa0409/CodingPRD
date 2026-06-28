"""Auth header extraction and RBAC checks (PRD §2.1, §2.11; SCAFFOLD §1.4, §1.7).

Every request must carry two mandatory headers (PRD §2.1):
  X-User-ID    -> the acting user's id
  X-User-Role  -> one of exactly four roles, spelled precisely:
                  SchedulingCoordinator, Proctor, ReviewOfficer, Candidate

Missing header or unknown role -> ERR_UNAUTHENTICATED (401).
Well-formed but not permitted for the operation -> ERR_FORBIDDEN (403).
"""
from flask import request

import errors

ROLES = {"SchedulingCoordinator", "Proctor", "ReviewOfficer", "Candidate"}


def authenticate():
    """Validate the two mandatory headers; return (user_id, role).

    Raises ERR_UNAUTHENTICATED when either header is absent or X-User-Role is
    not one of the four recognized roles (PRD §2.1, validation priority 1).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise errors.unauthenticated()
    return user_id, role


def require_roles(role, allowed):
    """Authorization check (PRD §2.1 / validation priority 2).

    `allowed` is an iterable of role names permitted for the operation. If the
    acting role is not among them, raise ERR_FORBIDDEN.
    """
    if role not in allowed:
        raise errors.forbidden()
