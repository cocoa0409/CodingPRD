"""Error type, response envelope helpers, auth middleware."""
import secrets
from flask import jsonify, request

from store import wall_now, fmt_meta_ts

ROLES = {"ContractorAdmin", "Estimator", "FieldTechnician", "Adjuster", "Customer"}

ERROR_STATUS = {
    "ERR_MISSING_AUTH_HEADER": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_SOD_VIOLATION": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_CLAIM_NOT_PAYABLE": 409,
    "ERR_SUPPLEMENT_NOT_PERMITTED": 409,
    "ERR_ESTIMATE_NOT_EDITABLE": 409,
    "ERR_INVOICE_NOT_ISSUABLE": 409,
    "ERR_ROUND_NOT_OPEN": 409,
    "ERR_AUTHORIZATION_MISSING": 409,
    "ERR_CONTAINMENT_REQUIRED": 422,
    "ERR_MOISTURE_GATE_FAILED": 422,
    "ERR_INSPECTION_INCOMPLETE": 422,
    "ERR_INSPECTION_EVIDENCE_INSUFFICIENT": 422,
    "ERR_SUPPLEMENT_EVIDENCE_INSUFFICIENT": 422,
    "ERR_DUPLICATE_INITIAL_ESTIMATE": 409,
    "ERR_DUPLICATE_ACTIVE_INVOICE": 409,
    "ERR_INSPECTION_SCHEDULE_CONFLICT": 409,
    "ERR_DISPOSITION_LINE_MISMATCH": 422,
    "ERR_CODE_UPGRADES_PENDING": 409,
    "ERR_PRICE_WINDOW_OVERLAP": 409,
    "ERR_POLICY_WINDOW_VIOLATION": 422,
    "ERR_PRICE_WINDOW_VIOLATION": 422,
    "ERR_AUTHORIZATION_EXPIRED": 422,
    "ERR_ORDINANCE_NOT_COVERED": 422,
    "ERR_ORDINANCE_CAP_EXHAUSTED": 422,
    "ERR_PAYMENT_EXCEEDS_OUTSTANDING": 422,
    "ERR_DEDUCTIBLE_OVERPAID": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http_status = ERROR_STATUS[error_id]
        self.message = message or error_id
        super().__init__(self.message)


def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(12),
        "api_request_timestamp": fmt_meta_ts(wall_now()),
    }


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
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def auth():
    """Priority 1: presence of X-User-ID / X-User-Role and a declared role."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_MISSING_AUTH_HEADER",
                       "X-User-ID and X-User-Role headers are required and the role must be a declared role")
    return uid, role


def require_roles(role, allowed):
    """Priority 2: caller role must be in the endpoint's role list."""
    if role not in allowed:
        raise ApiError("ERR_ROLE_NOT_PERMITTED", "Role %s is not permitted for this operation" % role)


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


# ---------------------------------------------------------------------------
# Payload validation helpers (priority 4)
# ---------------------------------------------------------------------------

def req_field(data, name):
    if name not in data or data[name] is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
    return data[name]


def opt_field(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    return data[name]


def as_str(value, name):
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be a string" % name)
    return value


def as_bool(value, name):
    if not isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be a boolean" % name)
    return value


def as_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be an integer" % name)
    return value


def as_num(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be a number" % name)
    return value


def as_enum(value, name, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field %s must be one of %s" % (name, ", ".join(sorted(allowed))))
    return value


def as_dt(value, name):
    from store import parse_dt
    dt = parse_dt(value)
    if dt is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be an ISO 8601 datetime" % name)
    return dt


def paginate_args():
    """Parse and validate limit/offset query parameters."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer")
        if str(raw_limit).strip() != str(limit) and not str(raw_limit).strip().lstrip("+").isdigit():
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer")
        if not str(raw_offset).strip().lstrip("+").isdigit() and str(raw_offset).strip() != str(offset):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def sorted_items(records):
    """created_at ascending; insertion sequence breaks ties."""
    return sorted(records, key=lambda r: (r["_created_instant"], r["_seq"]))


def page(records, filters=None):
    items = sorted_items(records)
    if filters:
        for key, val in filters.items():
            if val is not None:
                items = [r for r in items if r.get(key) == val]
    limit, offset = paginate_args()
    total = len(items)
    return ok_list(items[offset:offset + limit], limit, offset, total)


def public(rec):
    """Strip internal bookkeeping keys for the wire."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}
