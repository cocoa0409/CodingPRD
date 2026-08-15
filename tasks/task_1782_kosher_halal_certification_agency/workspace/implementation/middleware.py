"""Auth (PRD §2.1): X-User-ID / X-User-Role extraction, role gating, scope.

Header presence/role validity is validation priority 1 (400). Role permission
is priority 2 (403 ERR_FORBIDDEN_ROLE). ClientContact ownership scope and
FieldSupervisor assignment scope are priority 2.5 (403).
"""
from flask import g, request

from errors import ApiError, err

ROLES = [
    "AgencyAdmin",
    "AccountManager",
    "CertificationReviewer",
    "FieldSupervisor",
    "CertificateOfficer",
    "ClientContact",
]


def get_context():
    """Validate the two auth headers; populate flask.g."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers are required and X-User-Role must "
            "be one of the six declared roles")
    g.user_id = uid
    g.user_role = role
    return uid, role


def require_roles(*allowed):
    if g.user_role not in allowed:
        err("ERR_FORBIDDEN_ROLE",
            "Role %s is not permitted on this endpoint" % g.user_role)


def require_client_scope(owner_client_id):
    """ClientContact may only touch resources owned by its own client id."""
    if g.user_role == "ClientContact" and g.user_id != owner_client_id:
        err("ERR_CLIENT_SCOPE_VIOLATION",
            "ClientContact may only act on resources owned by client %s" % g.user_id)


def require_visit_assignment(visit):
    """FieldSupervisor assignment-scoped actions compare the opaque ids."""
    if g.user_id != visit["inspector_user_id"]:
        err("ERR_NOT_ASSIGNED_INSPECTOR",
            "Only the assigned inspector may perform this action on the visit")


def get_or_404(collection, entity_id, label="Resource"):
    ent = collection.get(entity_id)
    if ent is None:
        raise ApiError("ERR_NOT_FOUND", 404, "%s not found" % label)
    return ent
