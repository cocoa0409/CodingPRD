"""Envelope, errors, auth, datetime, pagination, and schema helpers."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

ERR_VALIDATION = "ERR_INVALID_REQUEST"
ERR_AUTH = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"
ERR_FORBIDDEN = "ERR_FORBIDDEN"

ROLES = {
    "Inventor",
    "TechTransferOfficer",
    "LicensingManager",
    "ComplianceOfficer",
    "ComplianceDirector",
    "FinanceOfficer",
    "FinanceDirector",
    "SystemAdmin",
}


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta():
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    return {"api_request_id": _request_id(), "api_request_timestamp": ts}


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.status


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is not None:
        uid = uid.strip()
    if role is not None:
        role = role.strip()
    if not uid or not role or role not in ROLES:
        raise ApiError(ERR_AUTH, 400, "X-User-ID or X-User-Role header missing or malformed")
    return uid, role


def require(*allowed_roles):
    """Authenticate and enforce endpoint role permission."""
    uid, role = auth()
    if allowed_roles and role not in allowed_roles:
        raise ApiError(ERR_FORBIDDEN, 403, "Role %s is not permitted for this operation" % role)
    return uid, role


# ---------------------------------------------------------------------------
# Datetimes (ISO 8601 UTC, second precision for comparisons)
# ---------------------------------------------------------------------------

def parse_dt(value):
    if not isinstance(value, str):
        raise ApiError(ERR_VALIDATION, 400, "Datetime value must be an ISO 8601 string")
    s = value.strip()
    if not s:
        raise ApiError(ERR_VALIDATION, 400, "Datetime value must be a non-empty string")
    candidate = s[:-1] + "+00:00" if s.endswith(("Z", "z")) else s
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        raise ApiError(ERR_VALIDATION, 400, "Malformed ISO 8601 datetime: %s" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.replace(microsecond=0)


def fmt_dt(dt):
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise ApiError(ERR_VALIDATION, 400, "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError(ERR_VALIDATION, 400, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise ApiError(ERR_VALIDATION, 400, "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError(ERR_VALIDATION, 400, "offset must be >= 0")
    return limit, offset


def paginate(records):
    """records: list of dicts with created_at/seq. Returns Flask response."""
    limit, offset = pagination_params()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total


# ---------------------------------------------------------------------------
# Body schema validation
# ---------------------------------------------------------------------------

def get_body():
    if not request.data:
        return {}
    data = request.get_json(force=True, silent=True)
    if data is None:
        raise ApiError(ERR_VALIDATION, 400, "Request body is not valid JSON")
    if not isinstance(data, dict):
        raise ApiError(ERR_VALIDATION, 400, "Request body must be a JSON object")
    return data


def check_schema(body, spec):
    """spec: {field: (required: bool, validator: fn) -> cleaned value}.

    A JSON null value is treated as absent. Unknown fields are rejected.
    """
    unknown = [k for k in body.keys() if k not in spec]
    if unknown:
        raise ApiError(ERR_VALIDATION, 400, "Unknown payload field(s): %s" % ", ".join(sorted(unknown)))
    out = {}
    for field, (required, validator) in spec.items():
        if field not in body or body[field] is None:
            if required:
                raise ApiError(ERR_VALIDATION, 400, "Missing required field: %s" % field)
            continue
        out[field] = validator(body[field])
    return out


def v_str(v):
    if not isinstance(v, str):
        raise ApiError(ERR_VALIDATION, 400, "Expected a string value")
    return v


def v_nonempty_str(v):
    if not isinstance(v, str) or not v.strip():
        raise ApiError(ERR_VALIDATION, 400, "Expected a non-empty string value")
    return v


def v_int(v):
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_VALIDATION, 400, "Expected an integer value")
    return v


def v_int_range(lo, hi):
    def _f(v):
        v = v_int(v)
        if v < lo or v > hi:
            raise ApiError(ERR_VALIDATION, 400, "Integer value out of range [%s, %s]" % (lo, hi))
        return v
    return _f


def v_int_min(lo):
    def _f(v):
        v = v_int(v)
        if v < lo:
            raise ApiError(ERR_VALIDATION, 400, "Integer value must be >= %s" % lo)
        return v
    return _f


def v_enum(*options):
    def _f(v):
        if not isinstance(v, str) or v not in options:
            raise ApiError(ERR_VALIDATION, 400, "Value must be one of: %s" % ", ".join(options))
        return v
    return _f


def v_dt(v):
    return parse_dt(v)


def v_shares(v):
    if not isinstance(v, list):
        raise ApiError(ERR_VALIDATION, 400, "adjusted_shares must be an array")
    out = []
    for item in v:
        if not isinstance(item, dict):
            raise ApiError(ERR_VALIDATION, 400, "adjusted_shares entries must be objects")
        extra = [k for k in item.keys() if k not in ("entry_id", "share_bp")]
        if extra:
            raise ApiError(ERR_VALIDATION, 400, "Unknown adjusted_shares field(s): %s" % ", ".join(sorted(extra)))
        if "entry_id" not in item or "share_bp" not in item:
            raise ApiError(ERR_VALIDATION, 400, "adjusted_shares entries require entry_id and share_bp")
        entry_id = item["entry_id"]
        if not isinstance(entry_id, str):
            raise ApiError(ERR_VALIDATION, 400, "entry_id must be a string")
        share_bp = v_int_range(1, 10000)(item["share_bp"])
        out.append({"entry_id": entry_id, "share_bp": share_bp})
    return out
