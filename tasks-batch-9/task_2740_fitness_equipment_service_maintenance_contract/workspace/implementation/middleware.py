"""Authentication, role gating and identity binding (ladder rungs 1-5)."""
from flask import request

import db
from errors import ApiError

CONTRACT_ADMIN = "ContractAdministrator"
SERVICE_COORDINATOR = "ServiceCoordinator"
PARTS_PLANNER = "PartsPlanner"
FIELD_TECHNICIAN = "FieldTechnician"
SAFETY_INSPECTOR = "SafetyInspector"
CLUB_MANAGER = "ClubManager"

ALL_ROLES = (
    CONTRACT_ADMIN,
    SERVICE_COORDINATOR,
    PARTS_PLANNER,
    FIELD_TECHNICIAN,
    SAFETY_INSPECTOR,
    CLUB_MANAGER,
)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def auth(*allowed_roles):
    """Rung 1 then rung 2. Returns the principal context."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if not user_id or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required")
    if not role or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is required")
    role = str(role).strip()
    user_id = str(user_id).strip()
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Unknown role %s" % role)
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_ROLE_FORBIDDEN", "%s may not perform this operation" % role)
    return {"user_id": user_id, "role": role}


def require_inspector(ctx):
    """Rung 5: the SafetyInspector's Technician row must carry the certification."""
    tech = db.technicians.get(ctx["user_id"])
    if tech is None or not tech.get("is_safety_inspector"):
        raise ApiError("ERR_INSPECTOR_NOT_CERTIFIED")
    return tech


def require_club_scope(ctx, club_id):
    """Rung 3: a ClubManager may only reach rows inside its own club."""
    if ctx["role"] == CLUB_MANAGER and ctx["user_id"] != club_id:
        raise ApiError("ERR_CLUB_SCOPE_FORBIDDEN")


def require_assigned(ctx, assigned_technician_id):
    """Rung 4: a FieldTechnician may only act on its own work item."""
    if ctx["role"] == FIELD_TECHNICIAN and ctx["user_id"] != assigned_technician_id:
        raise ApiError("ERR_TECHNICIAN_NOT_ASSIGNED")


def body():
    """Request body as a dict; an absent or non-object body reads as empty."""
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object")
    return payload
