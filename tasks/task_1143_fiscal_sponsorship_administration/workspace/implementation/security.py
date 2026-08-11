"""Auth, role authorization, ownership anchors, and request-body validation.

Validation pipeline order (PRD §2.11) is normative:
  1. body schema (ERR_VALIDATION, 400)
  2. enum membership (ERR_INVALID_ENUM, 400)
  3. authentication (ERR_UNAUTHENTICATED, 401)
  4. role authorization (ERR_UNAUTHORIZED_ROLE, 403)
  5. ownership (ERR_NOT_RESOURCE_OWNER, 403)
  6. path id resolution left-to-right (404s)
  7. state guards (409s)
  then domain rules in their defined sequence.
"""

from flask import request

from errors import (
    ERR_INVALID_ENUM,
    ERR_NOT_RESOURCE_OWNER,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED_ROLE,
    ERR_VALIDATION,
    raise_err,
)

ROLES = {
    "Applicant",
    "ProjectLead",
    "ProgramOfficer",
    "ComplianceOfficer",
    "FinanceOfficer",
    "SponsorAdmin",
    "Donor",
}

# Every GET endpoint is authorized for all roles except Donor (PRD §4).
READ_ROLES = ROLES - {"Donor"}


# ---------------------------------------------------------------------------
# Body extraction + schema (pipeline step 1) and enums (step 2)
# ---------------------------------------------------------------------------


def body():
    """Request JSON body as a dict; an absent body counts as {}."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None or not isinstance(data, dict):
        raise_err(ERR_VALIDATION, "Request body must be a JSON object")
    return data


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_field(data, field):
    if field not in data or data[field] is None:
        raise_err(ERR_VALIDATION, "Missing required field: %s" % field)
    return data[field]


def req_str(data, field):
    v = req_field(data, field)
    if not isinstance(v, str):
        raise_err(ERR_VALIDATION, "Field %s must be a string" % field)
    return v


def opt_str(data, field):
    if field not in data or data[field] is None:
        return None
    if not isinstance(data[field], str):
        raise_err(ERR_VALIDATION, "Field %s must be a string" % field)
    return data[field]


def req_int(data, field):
    v = req_field(data, field)
    if not is_int(v):
        raise_err(ERR_VALIDATION, "Field %s must be an integer" % field)
    return v


def opt_int(data, field):
    if field not in data or data[field] is None:
        return None
    if not is_int(data[field]):
        raise_err(ERR_VALIDATION, "Field %s must be an integer" % field)
    return data[field]


def req_number(data, field):
    v = req_field(data, field)
    if not is_number(v):
        raise_err(ERR_VALIDATION, "Field %s must be a number" % field)
    return v


def opt_bool(data, field):
    if field not in data or data[field] is None:
        return None
    if not isinstance(data[field], bool):
        raise_err(ERR_VALIDATION, "Field %s must be a boolean" % field)
    return data[field]


def check_enum(value, field, members):
    if value not in members:
        raise_err(
            ERR_INVALID_ENUM,
            "Field %s must be one of %s" % (field, ", ".join(sorted(members))),
        )
    return value


def req_enum(data, field, members):
    v = req_field(data, field)
    if not isinstance(v, str):
        raise_err(ERR_VALIDATION, "Field %s must be a string" % field)
    return check_enum(v, field, members)


def opt_enum(data, field, members):
    if field not in data or data[field] is None:
        return None
    if not isinstance(data[field], str):
        raise_err(ERR_VALIDATION, "Field %s must be a string" % field)
    return check_enum(data[field], field, members)


# ---------------------------------------------------------------------------
# Auth (steps 3-5)
# ---------------------------------------------------------------------------


def auth():
    """Returns (user_id, role). Missing/blank headers or an undeclared role
    name -> ERR_UNAUTHENTICATED (401)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not uid.strip() or role is None or not role.strip():
        raise_err(ERR_UNAUTHENTICATED, "X-User-ID and X-User-Role headers are required")
    if role not in ROLES:
        raise_err(ERR_UNAUTHENTICATED, "Unrecognized role: %s" % role)
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise_err(ERR_UNAUTHORIZED_ROLE, "Role %s is not authorized for this endpoint" % role)


def require_owner(uid, anchor):
    if uid != anchor:
        raise_err(ERR_NOT_RESOURCE_OWNER, "X-User-ID does not match the resource owner")
