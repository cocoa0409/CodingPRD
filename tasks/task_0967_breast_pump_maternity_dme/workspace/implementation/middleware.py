import re
from datetime import datetime

from flask import request

from errors import ApiError
from response import ok_list

ROLES = {
    "Member",
    "CareCoordinator",
    "InsuranceSpecialist",
    "BillingSpecialist",
    "WarehouseOperator",
    "PlatformAdmin",
}

ALL_ROLES = [
    "Member",
    "CareCoordinator",
    "InsuranceSpecialist",
    "BillingSpecialist",
    "WarehouseOperator",
    "PlatformAdmin",
]

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def authorize(allowed_roles):
    """Validation pipeline priorities 1-2: authentication then authorization."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            "Missing or invalid X-User-ID / X-User-Role headers",
            401,
        )
    if role not in allowed_roles:
        raise ApiError(
            "ERR_FORBIDDEN", "Role is not authorized for this endpoint", 403
        )
    return uid, role


def check_ownership(role, uid, member_id):
    """Pipeline priority 3: a Member may only act on their own resources."""
    if role == "Member" and member_id != uid:
        raise ApiError(
            "ERR_OWNERSHIP_VIOLATION",
            "Members may only act on their own resources",
            403,
        )


def body():
    raw = request.get_data()
    if not raw:
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object", 400)
    return data


def get_or_404(collection, rid, error_id):
    ent = collection.get(rid) if isinstance(rid, str) else None
    if ent is None:
        raise ApiError(error_id, "Resource not found: %s" % rid, 404)
    return ent


# ---- shape validators (pipeline priority 5) ----


def req_str(b, k):
    v = b.get(k)
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", "Missing or invalid field: %s" % k, 400)
    return v


def opt_str(b, k, default=None):
    v = b.get(k, default)
    if v is not None and not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", "Invalid field: %s" % k, 400)
    return v


def req_int(b, k):
    v = b.get(k)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", "Missing or invalid field: %s" % k, 400)
    return v


def opt_int(b, k, default):
    v = b.get(k, default)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", "Invalid field: %s" % k, 400)
    return v


def opt_bool(b, k, default):
    v = b.get(k, default)
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", "Invalid field: %s" % k, 400)
    return v


def opt_num(b, k, default):
    v = b.get(k, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", "Invalid field: %s" % k, 400)
    return v


def parse_date(s):
    if not isinstance(s, str) or not _DATE_RE.match(s):
        raise ApiError("ERR_VALIDATION", "Invalid ISO date: %r" % (s,), 400)
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise ApiError("ERR_VALIDATION", "Invalid ISO date: %r" % (s,), 400)


def req_date(b, k):
    return parse_date(req_str(b, k))


def opt_date(b, k, default=None):
    if k not in b or b.get(k) is None:
        return default
    return parse_date(b.get(k))


def req_enum(b, k, allowed):
    v = req_str(b, k)
    if v not in allowed:
        raise ApiError(
            "ERR_VALIDATION", "Invalid value for %s: %s" % (k, v), 400
        )
    return v


def opt_enum(b, k, allowed, default):
    if k not in b or b.get(k) is None:
        return default
    return req_enum(b, k, allowed)


def public(ent):
    return {k: v for k, v in ent.items() if not k.startswith("_")}


def _parse_int_param(raw, name):
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", "Invalid %s parameter" % name, 400)


def paginate(items):
    """Sort by created_at ascending (insertion order breaks ties) and apply
    limit/offset per PRD section 2.3."""
    items = sorted(items, key=lambda e: e["_seq"])
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10 if raw_limit is None else _parse_int_param(raw_limit, "limit")
    offset = 0 if raw_offset is None else _parse_int_param(raw_offset, "offset")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_VALIDATION", "limit must be between 1 and 100", 400)
    if offset < 0:
        raise ApiError("ERR_VALIDATION", "offset must be >= 0", 400)
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([public(e) for e in page], limit, offset, total)


def filter_query(items, mapping):
    out = list(items)
    for param, key in mapping.items():
        v = request.args.get(param)
        if v is not None:
            out = [e for e in out if e.get(key) is not None and str(e.get(key)) == v]
    return out


def scope_member_list(items, role, uid):
    """Member callers only ever see their own records in list responses."""
    if role != "Member":
        return list(items)
    qmid = request.args.get("member_id")
    if qmid is not None and qmid != uid:
        raise ApiError(
            "ERR_OWNERSHIP_VIOLATION",
            "Members may only access their own resources",
            403,
        )
    return [e for e in items if e.get("member_id") == uid]
