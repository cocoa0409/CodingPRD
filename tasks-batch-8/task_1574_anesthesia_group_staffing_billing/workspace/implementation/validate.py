"""Auth, request-schema validation, and pagination helpers."""
import re
from datetime import datetime, timezone

from flask import request

from errors import ApiError, err_missing_headers, err_invalid_request

ROLES = {
    "GroupAdministrator",
    "Scheduler",
    "AttendingAnesthesiologist",
    "CRNA",
    "BillingSpecialist",
    "ComplianceAuditor",
}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


def auth(allowed_roles):
    """Validation layers 1-2: header presence/role validity, then role authorization."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err_missing_headers()
    if role not in allowed_roles:
        raise ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403,
                       "Role %s is not permitted for this endpoint" % role)
    return uid, role


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def valid_date_str(v):
    if not isinstance(v, str) or not _DATE_RE.match(v):
        return False
    try:
        datetime.strptime(v, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def valid_month_str(v):
    if not isinstance(v, str) or not _MONTH_RE.match(v):
        return False
    mm = int(v[5:7])
    return 1 <= mm <= 12


def parse_iso8601(v):
    """Parse an ISO 8601 timestamp to an aware UTC datetime; None if malformed."""
    if not isinstance(v, str):
        return None
    s = v.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def check_body(body, spec):
    """Layer 3 schema check.

    spec: {name: {"kind": "str"|"int"|"bool"|"date"|"iso8601"|("enum", (...)),
                  "req": bool, "min": int|None, "max": int|None}}
    Unknown fields -> ERR_INVALID_REQUEST.
    """
    for key in body:
        if key not in spec:
            raise err_invalid_request("Unknown field: %s" % key)
    for name, rule in spec.items():
        required = rule.get("req", False)
        if name not in body:
            if required:
                raise err_invalid_request("Missing required field: %s" % name)
            continue
        v = body[name]
        kind = rule["kind"]
        if kind == "str":
            if not isinstance(v, str):
                raise err_invalid_request("Field %s must be a string" % name)
        elif kind == "int":
            if not _is_int(v):
                raise err_invalid_request("Field %s must be an integer" % name)
            if rule.get("min") is not None and v < rule["min"]:
                raise err_invalid_request("Field %s below minimum" % name)
            if rule.get("max") is not None and v > rule["max"]:
                raise err_invalid_request("Field %s above maximum" % name)
        elif kind == "bool":
            if not isinstance(v, bool):
                raise err_invalid_request("Field %s must be a boolean" % name)
        elif kind == "date":
            if not valid_date_str(v):
                raise err_invalid_request("Field %s must be a YYYY-MM-DD date" % name)
        elif kind == "iso8601":
            if parse_iso8601(v) is None:
                raise err_invalid_request("Field %s must be an ISO 8601 timestamp" % name)
        elif isinstance(kind, tuple) and kind[0] == "enum":
            if not isinstance(v, str) or v not in kind[1]:
                raise err_invalid_request("Field %s must be one of %s" % (name, ",".join(kind[1])))


def parse_pagination(args):
    """limit (default 10, 1..100) and offset (default 0, >= 0)."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_invalid_request("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_invalid_request("offset must be an integer")
        if offset < 0:
            raise err_invalid_request("offset must be >= 0")
    return limit, offset


def sort_and_page(records, args):
    """Sort by created_at ascending (creation order) and apply pagination."""
    limit, offset = parse_pagination(args)
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    return ordered[offset:offset + limit], limit, offset, total


def apply_filters(records, args, allowed):
    """Exact-match query filters for the endpoint's declared filter params."""
    out = list(records)
    for f in allowed:
        val = args.get(f)
        if val is not None:
            out = [r for r in out if r.get(f) == val]
    return out
