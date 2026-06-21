"""Auth header extraction, role checking, ownership, and request parsing.

Header names (PRD 2.1):
  X-User-ID    — acting principal
  X-User-Role  — Anonymous | MemberOperator | FacilityManager | ComplianceOfficer
"""
from flask import request

from errors import ApiError

VALID_ROLES = {"Anonymous", "MemberOperator", "FacilityManager", "ComplianceOfficer"}


def get_identity():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED when either header is
    missing/blank or the role is not one of the four recognized roles."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in VALID_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return user_id, role


def require_roles(role, allowed):
    """ERR_UNAUTHORIZED when role is not in the allowed set for the operation."""
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED")


def require_owner(role, user_id, owner_member_id):
    """For an entity-backed MemberOperator acting on a member-owned resource,
    X-User-ID must equal the resource's member_id (PRD 2.1)."""
    if role == "MemberOperator" and user_id != owner_member_id:
        raise ApiError("ERR_FORBIDDEN_NOT_OWNER")


def get_json_body():
    """Parse the JSON body leniently; an absent/invalid body becomes {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST")
    return data


def parse_pagination():
    """limit in [1,100] default 10; offset >= 0 default 0. Out-of-range ->
    ERR_VALIDATION (PRD 2.3)."""
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION")
        if offset < 0:
            raise ApiError("ERR_VALIDATION")

    return limit, offset
