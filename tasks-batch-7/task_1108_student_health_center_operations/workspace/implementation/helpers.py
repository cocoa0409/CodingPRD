"""Response envelope, error type, auth middleware, and request validation
helpers. All structural names (headers, envelope fields, pagination params,
role names) come from SCAFFOLD.yaml / PRD.md verbatim."""
import random
import string
from datetime import datetime, timezone, date

from flask import request, jsonify

from store import clock

VALID_ROLES = {
    "Student", "FrontDeskStaff", "Nurse", "Clinician",
    "Pharmacist", "BillingOfficer", "HealthAdmin",
}


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def err_invalid_request(msg="Malformed request"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def gen_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def fmt_date(d):
    return d.isoformat()


def parse_dt(value, field):
    if not isinstance(value, str):
        raise err_invalid_request("%s must be an ISO8601 datetime string" % field)
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err_invalid_request("%s must be an ISO8601 datetime string" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value, field):
    if not isinstance(value, str):
        raise err_invalid_request("%s must be an ISO date string (YYYY-MM-DD)" % field)
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise err_invalid_request("%s must be an ISO date string (YYYY-MM-DD)" % field)


def envelope_ok(data, response_type="object", status=200, pagination=None):
    meta = {
        "api_request_id": gen_request_id(),
        "api_request_timestamp": fmt_dt(clock.now()),
    }
    if pagination is not None:
        meta.update(pagination)
    return jsonify({"meta": meta, "response_type": response_type, "data": data}), status


def envelope_error(error_id, status, message):
    meta = {
        "api_request_id": gen_request_id(),
        "api_request_timestamp": fmt_dt(clock.now()),
    }
    return jsonify({
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), status


def require_auth(allowed_roles=None):
    """Validation step 1-2: X-User-ID and X-User-Role must be present and the
    role recognized; then role authorization per endpoint."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in VALID_ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
            "X-User-ID and X-User-Role headers must be present and valid",
        )
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN", 403, "Role not permitted for this endpoint")
    return uid, role


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return data


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_present(body, field):
    if field not in body or body[field] is None:
        raise err_invalid_request("Missing required field: %s" % field)
    return body[field]


def req_string(body, field):
    v = req_present(body, field)
    if not isinstance(v, str):
        raise err_invalid_request("%s must be a string" % field)
    return v


def req_int(body, field):
    v = req_present(body, field)
    if not is_int(v):
        raise err_invalid_request("%s must be an integer" % field)
    return v


def req_enum(body, field, allowed):
    v = req_present(body, field)
    if v not in allowed:
        raise err_invalid_request("%s must be one of %s" % (field, sorted(allowed)))
    return v


def opt_enum(body, field, allowed):
    """Optional enum field: absent or null -> None; present invalid -> 400."""
    if field not in body or body[field] is None:
        return None
    v = body[field]
    if v not in allowed:
        raise err_invalid_request("%s must be one of %s" % (field, sorted(allowed)))
    return v


def pagination_params():
    """limit (default 10, min 1, max 100) and offset (default 0)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def list_response(items, serialize):
    """Sorted by created_at ascending; paginated envelope."""
    items = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(items)
    limit, offset = pagination_params()
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return envelope_ok([serialize(e) for e in page], response_type="array",
                       status=200, pagination=pagination)
