"""Auth header extraction, role checking, body parsing, pagination (PRD §2.1-2.3)."""

from flask import request

from errors import (
    ApiError,
    ERR_FORBIDDEN_ROLE,
    ERR_INVALID_REQUEST,
    ERR_MISSING_AUTH,
)

ALL_ROLES = {
    "WireOpsAdmin",
    "WireOperator",
    "WireApprover",
    "SanctionsScreener",
    "ComplianceOfficer",
    "FraudAnalyst",
    "RepairSpecialist",
    "WireInvestigator",
    "BeneficiaryBank",
    "Auditor",
}

# Read access: every internal role plus the auditor (PRD §3.11).
ALL_INTERNAL = (
    "WireOpsAdmin",
    "WireOperator",
    "WireApprover",
    "SanctionsScreener",
    "FraudAnalyst",
    "RepairSpecialist",
    "WireInvestigator",
    "Auditor",
)
SANCTIONS_READ = ALL_INTERNAL + ("ComplianceOfficer",)
RECALL_READ = ALL_INTERNAL + ("BeneficiaryBank",)
AUDIT_READ = ("WireOpsAdmin", "Auditor", "ComplianceOfficer")


def require_roles(*roles):
    """Priorities 1-2: header presence, then role authorization."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or role is None or not uid.strip() or not role.strip():
        raise ApiError(*ERR_MISSING_AUTH, "X-User-ID and X-User-Role headers must be present and non-empty.")
    if role not in ALL_ROLES or role not in roles:
        raise ApiError(*ERR_FORBIDDEN_ROLE, f"Role '{role}' is not permitted for this endpoint.")
    return uid, role


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        if request.data:
            raise ApiError(*ERR_INVALID_REQUEST, "Request body must be a JSON object.")
        return {}
    if not isinstance(data, dict):
        raise ApiError(*ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return data


def validate_body(data, spec):
    """Schema conformance (priority 4): required fields, types, enum domains,
    unknown keys rejected. spec: name -> (kind, required, domain|None).
    kind in {'str','int','posint','bool'}."""
    for key in data:
        if key not in spec:
            raise ApiError(*ERR_INVALID_REQUEST, f"Unknown field: {key}")
    for name, (kind, required, domain) in spec.items():
        if name not in data:
            if required:
                raise ApiError(*ERR_INVALID_REQUEST, f"Missing required field: {name}")
            continue
        v = data[name]
        if kind == "str":
            if not isinstance(v, str):
                raise ApiError(*ERR_INVALID_REQUEST, f"Field {name} must be a string.")
        elif kind == "int":
            if isinstance(v, bool) or not isinstance(v, int):
                raise ApiError(*ERR_INVALID_REQUEST, f"Field {name} must be an integer.")
        elif kind == "posint":
            if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
                raise ApiError(*ERR_INVALID_REQUEST, f"Field {name} must be a strictly positive integer.")
        elif kind == "bool":
            if not isinstance(v, bool):
                raise ApiError(*ERR_INVALID_REQUEST, f"Field {name} must be a boolean.")
        if domain is not None and v not in domain:
            raise ApiError(*ERR_INVALID_REQUEST, f"Field {name} must be one of {sorted(domain)}.")


def require_fk(data, field, mapping, what):
    """Body-supplied foreign references resolve at the existence priority (3),
    ahead of full schema validation (4)."""
    if field in data and isinstance(data[field], str):
        if data[field] not in mapping:
            raise ApiError(  # ERR_NOT_FOUND
                "ERR_NOT_FOUND", 404, f"The referenced {what} does not exist."
            )


def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit, offset = 10, 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(*ERR_INVALID_REQUEST, "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError(*ERR_INVALID_REQUEST, "limit must be between 1 and 100.")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(*ERR_INVALID_REQUEST, "offset must be an integer.")
        if offset < 0:
            raise ApiError(*ERR_INVALID_REQUEST, "offset must be >= 0.")
    return limit, offset
