"""Auth extraction, RBAC, and request-body field validation.

Validation priority (PRD §2.7): (1) identity headers -> (2) role permission ->
(3) path-id existence -> (4) body well-formedness -> (5) OCC -> (6) state ->
(7) segregation of duties -> (8) cross-reference consistency -> (9) guideline
in-flight guard -> (10) temporal conflicts -> (11) gold-card thresholds.
"""

from flask import request

import clock
from errors import (
    ApiError,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_NOT_FOUND,
    invalid_request,
    not_found,
)

ROLE_UM_ADMIN = "UMAdmin"
ROLE_POLICY_EDITOR = "ClinicalPolicyEditor"
ROLE_INTAKE = "IntakeSpecialist"
ROLE_REVIEWER = "ClinicalReviewer"
ROLE_MD = "MedicalDirector"
ROLE_APPEALS_CLERK = "AppealsClerk"
ROLE_APPEALS_REVIEWER = "AppealsReviewer"
ROLE_COMPLIANCE = "ComplianceOfficer"

ALL_ROLES = (
    ROLE_UM_ADMIN,
    ROLE_POLICY_EDITOR,
    ROLE_INTAKE,
    ROLE_REVIEWER,
    ROLE_MD,
    ROLE_APPEALS_CLERK,
    ROLE_APPEALS_REVIEWER,
    ROLE_COMPLIANCE,
)


def authorize(*allowed_roles):
    """Priorities 1-2: identity headers, then endpoint role permission.

    Returns the caller's X-User-ID on success.
    """
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or uid == "" or role is None or role == "":
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID and X-User-Role headers must be present and non-empty",
        )
    if role not in allowed_roles:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            403,
            "Role not permitted for this endpoint",
        )
    return uid


def caller_id():
    return request.headers.get("X-User-ID")


def json_body():
    """Best-effort JSON object body; anything else behaves as an empty body so
    required-field checks fire uniformly."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {}
    return data


def get_or_404(table, resource_id, label="resource"):
    rec = table.get(resource_id)
    if rec is None:
        raise not_found(f"{label} {resource_id} does not exist")
    return rec


# ---- body field validators (priority 4 -> ERR_INVALID_REQUEST) ----

_MISSING = object()


def req_str(data, field, nonempty=False):
    v = data.get(field, _MISSING)
    if v is _MISSING or v is None:
        raise invalid_request(f"Missing required field: {field}")
    if not isinstance(v, str):
        raise invalid_request(f"Field {field} must be a string")
    if nonempty and v == "":
        raise invalid_request(f"Field {field} must be non-empty")
    return v


def opt_str(data, field):
    v = data.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise invalid_request(f"Field {field} must be a string")
    return v


def req_bool(data, field):
    v = data.get(field, _MISSING)
    if v is _MISSING or v is None:
        raise invalid_request(f"Missing required field: {field}")
    if type(v) is not bool:
        raise invalid_request(f"Field {field} must be a boolean")
    return v


def req_int(data, field):
    v = data.get(field, _MISSING)
    if v is _MISSING or v is None:
        raise invalid_request(f"Missing required field: {field}")
    if type(v) is not int:
        raise invalid_request(f"Field {field} must be an integer")
    return v


def req_enum(data, field, allowed):
    v = req_str(data, field)
    if v not in allowed:
        raise invalid_request(
            f"Field {field} must be one of {sorted(allowed)}"
        )
    return v


def req_dt(data, field):
    raw = req_str(data, field)
    dt = clock.parse(raw)
    if dt is None:
        raise invalid_request(f"Field {field} must be an ISO 8601 datetime")
    return dt


def opt_dt(data, field):
    v = data.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise invalid_request(f"Field {field} must be an ISO 8601 datetime")
    dt = clock.parse(v)
    if dt is None:
        raise invalid_request(f"Field {field} must be an ISO 8601 datetime")
    return dt
