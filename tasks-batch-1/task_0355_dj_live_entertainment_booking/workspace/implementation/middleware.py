"""Auth header extraction and role checking.

Headers (PRD §2.1):
  X-User-ID    — caller identity (opaque for operators, entity id for participants)
  X-User-Role  — one of StudioAdmin, BookingAgent, Performer, Client

Priority 1: ERR_UNAUTHENTICATED (401) when X-User-ID or X-User-Role missing, or
            X-User-Role is not a recognized role.
Priority 2: ERR_FORBIDDEN_ROLE (403) when the role is not permitted for the
            endpoint.
"""
from flask import request

from errors import forbidden_role, unauthenticated

ROLES = {"StudioAdmin", "BookingAgent", "Performer", "Client"}


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Validate auth headers. Returns a Caller or raises ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise unauthenticated()
    if role not in ROLES:
        raise unauthenticated("Unknown role")
    return Caller(user_id, role)


def require_roles(caller, allowed):
    if caller.role not in allowed:
        raise forbidden_role()
