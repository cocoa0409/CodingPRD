"""Auth: X-User-ID / X-User-Role extraction, entity resolution, RBAC gate."""
from flask import g, request

import db
from errors import err

ROLES = {
    "EHSAdministrator",
    "Manager",
    "Employee",
    "VendingTechnician",
    "SafetyOfficer",
    "FinanceAnalyst",
    "ComplianceAuditor",
    "Any",
}

ENTITY_BACKED = {"Manager", "Employee"}


def authenticate():
    """Priority 1: headers present, role declared, entity-backed id resolves."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID / X-User-Role missing or role undeclared")
    employee = None
    if role in ENTITY_BACKED:
        employee = db.employees.get(uid)
        if employee is None:
            err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                "X-User-ID does not resolve to an existing Employee")
    g.user_id = uid
    g.role = role
    g.employee = employee


def require_roles(*allowed):
    """Priority 2: endpoint role gate, including the Manager is_manager flag."""
    role = g.role
    if "Any" not in allowed and role not in allowed:
        err("ERR_INSUFFICIENT_PERMISSIONS", "role not permitted for this endpoint")
    if role == "Manager" and not g.employee.get("is_manager"):
        err("ERR_INSUFFICIENT_PERMISSIONS",
            "Manager role requires an Employee with is_manager true")
