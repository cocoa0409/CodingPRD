"""Audit event single-read endpoint."""

from flask import Blueprint

from envelope import ok
from helpers import get_audit_event
from security import INTERNAL_ROLES, auth, require_roles

bp = Blueprint("audit", __name__)


@bp.get("/audit-events/<aid>")
def get_one_audit_event(aid):
    _, role = auth()
    require_roles(role, INTERNAL_ROLES)
    return ok(dict(get_audit_event(aid)))
