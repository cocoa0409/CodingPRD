"""Error type, response envelope helpers, auth, and request validation."""
import re
from datetime import date, datetime, timezone

from flask import request, jsonify

import db

ALL_ROLES = [
    "ProgramAdmin", "CareCoordinator", "ReferringProvider", "Dietitian",
    "LogisticsCoordinator", "Driver", "BillingSpecialist", "PayerReviewer",
    "Member",
]

DIET_TYPES = ["RENAL", "DIABETIC", "RENAL_DIABETIC", "CARDIAC"]


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def invalid_request(msg):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg)


def not_found(msg="Resource not found"):
    raise ApiError("ERR_NOT_FOUND", 404, msg)


# ---------------------------------------------------------------------------
# Response envelope (per PRD section 2.2)
# ---------------------------------------------------------------------------

def _meta():
    return {
        "api_request_id": db.new_request_id(),
        "api_request_timestamp": db.now_iso(),
    }


def envelope_ok(data, response_type="object", status=200, pagination=None):
    meta = _meta()
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def envelope_error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def pub(rec):
    """Public view of a stored record: strip internal underscore-prefixed keys."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Auth (PRD section 2.1)
# ---------------------------------------------------------------------------

def authenticate(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or uid.strip() == "" or role is None or role.strip() == "":
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
            "X-User-ID and X-User-Role headers must be present and non-empty")
    uid = uid.strip()
    role = role.strip()
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED_ROLE", 403,
                       "Role not permitted for this endpoint")
    return uid, role


# ---------------------------------------------------------------------------
# Body and field validation
# ---------------------------------------------------------------------------

def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        invalid_request("Request body must be a JSON object")
    return data


def _missing(name):
    invalid_request(f"Missing required field: {name}")


def f_str(body, name, required=True):
    if name not in body or body[name] is None:
        if required:
            _missing(name)
        return None
    v = body[name]
    if not isinstance(v, str):
        invalid_request(f"Field {name} must be a string")
    if v == "":
        invalid_request(f"Field {name} must be a non-empty string")
    return v


def f_int(body, name, required=True, min_val=None):
    if name not in body or body[name] is None:
        if required:
            _missing(name)
        return None
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        invalid_request(f"Field {name} must be an integer")
    if min_val is not None and v < min_val:
        invalid_request(f"Field {name} must be >= {min_val}")
    return v


def f_number(body, name, required=True):
    if name not in body or body[name] is None:
        if required:
            _missing(name)
        return None
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        invalid_request(f"Field {name} must be a number")
    return v


def f_list(body, name, required=True):
    if name not in body or body[name] is None:
        if required:
            _missing(name)
        return None
    v = body[name]
    if not isinstance(v, list):
        invalid_request(f"Field {name} must be an array")
    for el in v:
        if not isinstance(el, str):
            invalid_request(f"Field {name} must be an array of strings")
    return list(v)


def f_enum(body, name, values, required=True):
    v = f_str(body, name, required=required)
    if v is None:
        return None
    if v not in values:
        invalid_request(f"Field {name} must be one of {values}")
    return v


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def f_date(body, name, required=True):
    v = f_str(body, name, required=required)
    if v is None:
        return None
    if not _DATE_RE.match(v):
        invalid_request(f"Field {name} must be an ISO date (YYYY-MM-DD)")
    try:
        date.fromisoformat(v)
    except ValueError:
        invalid_request(f"Field {name} must be a valid ISO date (YYYY-MM-DD)")
    return v


def parse_iso_datetime(s):
    """Parse an ISO 8601 timestamp; returns an aware UTC datetime or None."""
    if not isinstance(s, str):
        return None
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def f_datetime(body, name, required=True):
    """Validate an ISO 8601 datetime field; returns (raw_string, datetime)."""
    v = f_str(body, name, required=required)
    if v is None:
        return None, None
    dt = parse_iso_datetime(v)
    if dt is None:
        invalid_request(f"Field {name} must be an ISO 8601 timestamp")
    return v, dt


_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def f_time(body, name, required=True):
    v = f_str(body, name, required=required)
    if v is None:
        return None
    if not _TIME_RE.match(v):
        invalid_request(f"Field {name} must be a time in HH:MM format")
    return v


# ---------------------------------------------------------------------------
# Pagination (PRD section 2.3): limit/offset, defaults 10/0, limit in [1,100]
# ---------------------------------------------------------------------------

def pagination_args():
    limit_s = request.args.get("limit")
    offset_s = request.args.get("offset")
    limit = 10
    if limit_s is not None:
        try:
            limit = int(limit_s)
        except (TypeError, ValueError):
            invalid_request("Query parameter limit must be an integer")
        if limit < 1 or limit > 100:
            invalid_request("Query parameter limit must be between 1 and 100")
    offset = 0
    if offset_s is not None:
        try:
            offset = int(offset_s)
        except (TypeError, ValueError):
            invalid_request("Query parameter offset must be an integer")
        if offset < 0:
            invalid_request("Query parameter offset must be >= 0")
    return limit, offset


def paginated(views):
    limit, offset = pagination_args()
    total = len(views)
    page = views[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return envelope_ok(page, "array", 200, meta)
