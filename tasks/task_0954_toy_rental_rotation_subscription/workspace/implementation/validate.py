"""Auth header extraction, role checks, ownership, body-shape validation, pagination.

Body-shape validation runs LAST in the pipeline (priority 11): field-level
problems are collected but only raised after all domain checks pass, and the
unknown-key rejection is likewise deferred.
"""
from flask import request

from errors import (
    ApiError,
    forbidden_ownership,
    unauthenticated,
    unauthorized_role,
    validation,
)

ROLES = {"Anonymous", "Member", "OperationsManager", "CustomerService", "PlatformAdmin"}


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise unauthenticated()
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise unauthorized_role()


def require_ownership(role, uid, owner_member_id):
    """Entity-backed ownership: only Member callers are compared."""
    if role == "Member" and uid != owner_member_id:
        raise forbidden_ownership()


def body():
    """Request JSON body as dict; malformed JSON or non-object -> ERR_VALIDATION."""
    if not request.data:
        return {}
    data = request.get_json(silent=True, force=True)
    if data is None:
        raise validation("Request body is not valid JSON.")
    if not isinstance(data, dict):
        raise validation("Request body must be a JSON object.")
    return data


# ---------------------------------------------------------------------------
# Field validators.  Each returns (value, ok).
# ---------------------------------------------------------------------------

def _is_str(v):
    return isinstance(v, str)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


class FieldSpec:
    def __init__(self, name, required, kind, **kw):
        self.name = name
        self.required = required
        self.kind = kind
        self.kw = kw


def F(name, required, kind, **kw):
    return FieldSpec(name, required, kind, **kw)


def _check(spec, value):
    """Return True when value conforms to the spec."""
    k = spec.kind
    if k == "str":
        return _is_str(value)
    if k == "int":
        if not _is_int(value):
            return False
        lo = spec.kw.get("min")
        hi = spec.kw.get("max")
        if lo is not None and value < lo:
            return False
        if hi is not None and value > hi:
            return False
        ne = spec.kw.get("nonzero")
        if ne and value == 0:
            return False
        return True
    if k == "number":
        if not _is_num(value):
            return False
        lo = spec.kw.get("min")  # inclusive
        hi = spec.kw.get("max")  # exclusive when hi_exclusive else inclusive
        if lo is not None and value < lo:
            return False
        if hi is not None:
            if spec.kw.get("hi_exclusive") and not (value < hi):
                return False
            if not spec.kw.get("hi_exclusive") and value > hi:
                return False
        return True
    if k == "enum":
        return _is_str(value) and value in spec.kw["values"]
    if k == "date":
        from timestamps import parse_date
        return parse_date(value) is not None
    if k == "datetime":
        from timestamps import parse_datetime
        return parse_datetime(value) is not None
    if k == "str_array":
        return isinstance(value, list) and all(_is_str(x) for x in value)
    if k == "enum_array":
        return isinstance(value, list) and all(
            _is_str(x) and x in spec.kw["values"] for x in value
        )
    if k == "any":
        return True
    return False


class ShapeResult:
    def __init__(self):
        self.values = {}
        self.ok = True


def parse_fields(data, specs):
    """Validate known fields; collect problems without raising.

    Domain checks run on .values; shape failure is deferred via .ok and
    finalized by finalize_shape() after domain checks (priority 11 last).
    """
    res = ShapeResult()
    allowed = {s.name for s in specs}
    for key in data:
        if key not in allowed:
            res.ok = False
    for spec in specs:
        if spec.name not in data:
            if spec.required:
                res.ok = False
            continue
        value = data[spec.name]
        if not _check(spec, value):
            res.ok = False
            continue
        res.values[spec.name] = value
    return res


def finalize_shape(res):
    if not res.ok:
        raise validation()


def parse_pagination():
    """limit / offset query params: defaults 10 / 0, clamped to 1..100 / >=0."""
    def _as_int(raw):
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = _as_int(limit_raw) if limit_raw is not None else 10
    offset = _as_int(offset_raw) if offset_raw is not None else 0
    if limit is None:
        limit = 10
    if offset is None:
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paginate(sorted_items):
    limit, offset = parse_pagination()
    total = len(sorted_items)
    page = sorted_items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return page, meta


def query_filter(name):
    v = request.args.get(name)
    return v if v else None
