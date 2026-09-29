"""Identity headers, RBAC and ownership scope (PRD 2.1, ladder steps 1-4)."""
from flask import request

import db
from errors import ApiError

ROLES = ("Anonymous", "NetworkAdmin", "FiscalOfficer", "QualityCoach", "Provider", "Substitute")


class Actor(object):
    __slots__ = ("role", "user_id")

    def __init__(self, role, user_id):
        self.role = role
        self.user_id = user_id

    @property
    def is_provider(self):
        return self.role == "Provider"

    @property
    def is_substitute(self):
        return self.role == "Substitute"


def require_auth(allowed_roles):
    """Ladder steps 1-3: role authentication, identity authentication, role authorization."""
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role must be one of the six declared roles.")
    user_id = request.headers.get("X-User-ID")
    if user_id is None or user_id == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID is required.")
    if role == "Provider" and user_id not in db.providers:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID does not resolve to a provider.")
    if role == "Substitute" and user_id not in db.substitutes:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID does not resolve to a substitute.")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    return Actor(role, user_id)


def allow_anonymous():
    """POST /fccn/providers/apply is exempt from both header checks."""
    role = request.headers.get("X-User-Role")
    if role is not None and role != "" and role != "Anonymous":
        raise ApiError("ERR_FORBIDDEN_ROLE")
    return Actor("Anonymous", request.headers.get("X-User-ID") or "")


def scope_provider(actor, provider_id):
    """Ladder step 4: a Provider actor may only address its own resources."""
    if actor.is_provider and provider_id != actor.user_id:
        raise ApiError("ERR_PROVIDER_SCOPE_VIOLATION")


def scope_substitute(actor, substitute_id):
    """Ladder step 4: a Substitute actor may only address their own assignments."""
    if actor.is_substitute and substitute_id != actor.user_id:
        raise ApiError("ERR_SUBSTITUTE_SCOPE_VIOLATION")
