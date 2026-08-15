"""Response envelope, errors, auth/RBAC, pagination helpers."""
import functools
import uuid
from datetime import datetime, timezone

from flask import g, jsonify, request

# Error IDs (from the PRD §5 catalogue / scaffold §1.6)
ERR_MISSING_AUTH_HEADER = "ERR_MISSING_AUTH_HEADER"
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_CROSS_REFERENCE_MISMATCH = "ERR_CROSS_REFERENCE_MISMATCH"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
ERR_DUPLICATE = "ERR_DUPLICATE"
ERR_NO_SPEC_PARAMETERS = "ERR_NO_SPEC_PARAMETERS"
ERR_PARAMETER_BOUNDS_INVALID = "ERR_PARAMETER_BOUNDS_INVALID"
ERR_SPEC_NOT_YET_EFFECTIVE = "ERR_SPEC_NOT_YET_EFFECTIVE"
ERR_SUPERSEDES_NOT_EFFECTIVE = "ERR_SUPERSEDES_NOT_EFFECTIVE"
ERR_SPEC_IN_USE = "ERR_SPEC_IN_USE"
ERR_NO_EFFECTIVE_SPEC = "ERR_NO_EFFECTIVE_SPEC"
ERR_SPEC_NOT_EFFECTIVE = "ERR_SPEC_NOT_EFFECTIVE"
ERR_ACTIVE_SOURCES_EXIST = "ERR_ACTIVE_SOURCES_EXIST"
ERR_OPEN_SUBSTITUTIONS_EXIST = "ERR_OPEN_SUBSTITUTIONS_EXIST"
ERR_QUALIFICATION_IN_PROGRESS = "ERR_QUALIFICATION_IN_PROGRESS"
ERR_QUALIFICATION_SCORE_TOO_LOW = "ERR_QUALIFICATION_SCORE_TOO_LOW"
ERR_DOCUMENT_PACK_INCOMPLETE = "ERR_DOCUMENT_PACK_INCOMPLETE"
ERR_SUPPLIER_NOT_QUALIFIED = "ERR_SUPPLIER_NOT_QUALIFIED"
ERR_OPEN_CAPAS_EXIST = "ERR_OPEN_CAPAS_EXIST"
ERR_DECLARATION_MISSING = "ERR_DECLARATION_MISSING"
ERR_SOURCE_NOT_ACTIVE = "ERR_SOURCE_NOT_ACTIVE"
ERR_ACTIVE_CONTRACT_EXISTS = "ERR_ACTIVE_CONTRACT_EXISTS"
ERR_CONTRACT_WINDOW_NOT_OPEN = "ERR_CONTRACT_WINDOW_NOT_OPEN"
ERR_CONTRACT_WINDOW_OVERLAP = "ERR_CONTRACT_WINDOW_OVERLAP"
ERR_MEASURED_VALUES_INCOMPLETE = "ERR_MEASURED_VALUES_INCOMPLETE"
ERR_FINDINGS_UNDISPOSITIONED = "ERR_FINDINGS_UNDISPOSITIONED"
ERR_FINDINGS_REQUIRE_REJECTION = "ERR_FINDINGS_REQUIRE_REJECTION"
ERR_DEVIATION_SCORE_TOO_HIGH = "ERR_DEVIATION_SCORE_TOO_HIGH"
ERR_REGULATORY_SIGNOFF_REQUIRED = "ERR_REGULATORY_SIGNOFF_REQUIRED"
ERR_REGULATORY_SIGNOFF_NOT_REQUIRED = "ERR_REGULATORY_SIGNOFF_NOT_REQUIRED"
ERR_IMPACT_DELTA_EXCEEDS_THRESHOLD = "ERR_IMPACT_DELTA_EXCEEDS_THRESHOLD"
ERR_AUDIT_WINDOW_NOT_OPEN = "ERR_AUDIT_WINDOW_NOT_OPEN"
ERR_AUDIT_ALREADY_OPEN = "ERR_AUDIT_ALREADY_OPEN"
# Temporal-guard id used by scaffold validation row 8 for declaration-collect
# window violations and CAPA due_date guards (not separately catalogued).
ERR_TEMPORAL_GUARD_VIOLATION = "ERR_TEMPORAL_GUARD_VIOLATION"

ALL_ROLES = (
    "SpecAuthor",
    "QualityManager",
    "ProcurementManager",
    "SupplierQualityEngineer",
    "RegulatoryAffairs",
    "PlatformAdmin",
)


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def _meta():
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    return {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": ts,
    }


def respond_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def respond_list(items, total_count, limit, offset, code=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), code


def respond_error(error_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def err(error_id, status, message):
    raise ApiError(error_id, status, message)


def invalid(message):
    err(ERR_INVALID_REQUEST, 400, message)


def not_found(message="resource not found"):
    err(ERR_NOT_FOUND, 404, message)


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def require_roles(*roles):
    """Auth (priority 1) then RBAC (priority 2)."""

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if uid is None or role is None or uid == "" or role == "":
                err(
                    ERR_MISSING_AUTH_HEADER,
                    400,
                    "X-User-ID and X-User-Role headers are required",
                )
            if role not in roles:
                err(ERR_FORBIDDEN_ROLE, 403, "role not permitted for this endpoint")
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco


def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            invalid("limit must be an integer")
        if str(raw_limit).strip() != str(limit) and not (
            str(raw_limit).strip().lstrip("+").isdigit()
        ):
            invalid("limit must be an integer")
        if limit < 1 or limit > 100:
            invalid("limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            invalid("offset must be an integer")
        if not str(raw_offset).strip().lstrip("+").lstrip("-").isdigit():
            invalid("offset must be an integer")
        if offset < 0:
            invalid("offset must be >= 0")
    return limit, offset


def sorted_rows(rows):
    """Global list ordering: created_at ASC, insertion sequence tie-break."""
    return sorted(rows, key=lambda r: (r["_created_dt"], r["_seq"]))


def list_page(rows, serializer, limit, offset):
    rows = sorted_rows(rows)
    total = len(rows)
    page = rows[offset : offset + limit]
    return respond_list([serializer(r) for r in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Field validation helpers
# ---------------------------------------------------------------------------

def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_int(value):
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float) and value.is_integer():
        return True
    return False


def require_str(data, field):
    value = data.get(field)
    if not isinstance(value, str) or value == "":
        invalid(f"{field} is required and must be a non-empty string")
    return value


def require_bool(data, field):
    value = data.get(field)
    if not isinstance(value, bool):
        invalid(f"{field} is required and must be a boolean")
    return value


def require_number(data, field):
    value = data.get(field)
    if not is_number(value):
        invalid(f"{field} is required and must be a number")
    return value


def require_int(data, field):
    value = data.get(field)
    if not is_int(value):
        invalid(f"{field} is required and must be an integer")
    return int(value)


def parse_bool_query(raw, field):
    if raw is None:
        return None
    low = raw.strip().lower()
    if low == "true":
        return True
    if low == "false":
        return False
    invalid(f"{field} must be true or false")
