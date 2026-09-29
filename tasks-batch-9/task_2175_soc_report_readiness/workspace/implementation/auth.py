"""Authentication, role checks and pagination parsing (PRD 2.1, 2.3, 2.7)."""
from flask import request

import store
from errors import ApiError

ROLES = (
    "ComplianceLead",
    "ControlOwner",
    "EvidenceReviewer",
    "Auditor",
    "AccountExecutive",
    "SubserviceContact",
    "PlatformAdmin",
)

ALL_ROLES = list(ROLES)
READ_ROLES = list(ROLES)


def authenticate(allowed_roles):
    """Steps 1-4 of PRD 2.7. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or user_id.strip() == "" or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE")
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    if "SubserviceContact" in allowed_roles and role == "SubserviceContact":
        org = store.DB["subservice_organizations"].get(user_id)
        if org is None or org["method"] != "INCLUSIVE":
            raise ApiError("ERR_SUBSERVICE_NOT_INCLUSIVE")
    return user_id, role


def check_action_role(role, action, action_roles):
    """A permitted-on-the-endpoint role that is not the named actor for the
    requested action value is rejected with ERR_ROLE_NOT_PERMITTED (PRD 2.1)."""
    if not isinstance(action, str):
        return
    allowed = action_roles.get(action)
    if allowed is None:
        return
    if role not in allowed:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {}
    return data


def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_PAGINATION")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION")
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total
