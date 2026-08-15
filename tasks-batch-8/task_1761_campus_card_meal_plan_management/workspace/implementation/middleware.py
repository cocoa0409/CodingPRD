"""Auth header extraction, role checking, body validation helpers.

Validation priority (PRD section 2.10) is enforced by the call order in each
handler: auth -> role -> ownership -> body -> path -> body refs ->
idempotency -> state -> OCC -> cross-entity -> fraud/SoD -> temporal ->
uniqueness/eligibility -> funds/thresholds.
"""

from datetime import datetime, timezone

from flask import request, g

from errors import (
    err, ERR_MISSING_AUTH_CONTEXT, ERR_ROLE_NOT_PERMITTED, ERR_VALIDATION,
    ERR_NOT_FOUND,
)

ROLES = {
    "PlatformAdmin", "CardOfficeAdmin", "CardHolder", "DiningServicesManager",
    "BursarOffice", "FraudAnalyst", "SecurityOfficer", "MerchantUser",
    "PointOfSale", "DoorController",
}

HOLDER_TYPES = {"STUDENT_RESIDENT", "STUDENT_COMMUTER", "FACULTY", "STAFF", "AFFILIATE"}
HOUSING_STATUSES = {"ON_CAMPUS", "COMMUTER", "OFF_CAMPUS"}


def authenticate():
    """Priority 1: headers present and role declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        err(ERR_MISSING_AUTH_CONTEXT,
            "X-User-ID and X-User-Role headers are required and the role must be declared")
    g.user_id = user_id
    g.role = role
    return user_id, role


def require_roles(*allowed):
    """Priority 2: caller role in the endpoint's authorized list."""
    if g.role not in allowed:
        err(ERR_ROLE_NOT_PERMITTED, "Caller role is not permitted on this endpoint")


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        err(ERR_VALIDATION, "Request body must be a JSON object")
    return data


def _missing(body, key):
    return key not in body or body[key] is None


def v_str(body, key, required=True):
    if _missing(body, key):
        if required:
            err(ERR_VALIDATION, f"Missing required field: {key}")
        return None
    val = body[key]
    if not isinstance(val, str) or val == "":
        err(ERR_VALIDATION, f"Field {key} must be a non-empty string")
    return val


def v_int(body, key, required=True, min_v=None, max_v=None):
    if _missing(body, key):
        if required:
            err(ERR_VALIDATION, f"Missing required field: {key}")
        return None
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, int):
        err(ERR_VALIDATION, f"Field {key} must be an integer")
    if min_v is not None and val < min_v:
        err(ERR_VALIDATION, f"Field {key} must be >= {min_v}")
    if max_v is not None and val > max_v:
        err(ERR_VALIDATION, f"Field {key} must be <= {max_v}")
    return val


def v_bool(body, key, default=None):
    if _missing(body, key):
        return default
    val = body[key]
    if not isinstance(val, bool):
        err(ERR_VALIDATION, f"Field {key} must be a boolean")
    return val


def v_enum(body, key, values, required=True):
    val = v_str(body, key, required=required)
    if val is None:
        return None
    if val not in values:
        err(ERR_VALIDATION, f"Field {key} must be one of {sorted(values)}")
    return val


def parse_dt_value(val, key):
    if not isinstance(val, str) or not val.strip():
        err(ERR_VALIDATION, f"Field {key} must be an ISO 8601 datetime string")
    t = val.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        err(ERR_VALIDATION, f"Field {key} is not a parseable ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def v_dt(body, key, required=True):
    if _missing(body, key):
        if required:
            err(ERR_VALIDATION, f"Missing required field: {key}")
        return None
    return parse_dt_value(body[key], key)


def fmt_dt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def find_or_404(table, rid):
    row = table.get(rid)
    if row is None:
        err(ERR_NOT_FOUND, "Resource not found")
    return row


def pub(row):
    """Serialize a row: strip internal underscore-prefixed keys."""
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def paginate(rows):
    """Sort by (created_at, insertion seq) ascending; apply limit/offset."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            err(ERR_VALIDATION, "limit must be an integer")
        if isinstance(limit, bool) or limit < 1 or limit > 100:
            err(ERR_VALIDATION, "limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            err(ERR_VALIDATION, "offset must be an integer")
        if isinstance(offset, bool) or offset < 0:
            err(ERR_VALIDATION, "offset must be >= 0")
    rows = sorted(rows, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    total = len(rows)
    page = rows[offset:offset + limit]
    return [pub(r) for r in page], {
        "limit": limit, "offset": offset, "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
