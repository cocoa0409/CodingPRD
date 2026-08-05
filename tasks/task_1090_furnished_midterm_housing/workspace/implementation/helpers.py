"""Auth, ownership, existence, pagination, and body-validation helpers."""
from flask import request
from core import (
    DB, ApiError, KNOWN_ROLES, public,
    PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MIN, PAGE_LIMIT_MAX, PAGE_OFFSET_DEFAULT,
)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def auth_context(anonymous_ok=False):
    """Return (user_id, role). For anonymous_ok endpoints auth headers are optional."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if anonymous_ok:
        return uid, (role or "Anonymous")
    if not uid or not role or role not in KNOWN_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unknown authentication headers")
    return uid, role


def require_role(role, allowed):
    """Coarse endpoint-level role gate."""
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")


def forbid():
    raise ApiError("ERR_UNAUTHORIZED", 403, "Not permitted")


# ---------------------------------------------------------------------------
# Body helpers
# ---------------------------------------------------------------------------
def get_json_body():
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", 422, "Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError("ERR_VALIDATION", 422, f"Missing required field: {f}")


def as_int(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", 422, f"Missing required field: {field}")
        return None
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        # allow integer-valued numbers only
        if isinstance(val, float) and val.is_integer():
            return int(val)
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be an integer")
    return val


# ---------------------------------------------------------------------------
# Existence
# ---------------------------------------------------------------------------
def get_or_404(table, rid):
    rec = DB.tables[table].get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"{table[:-1]} not found")
    return rec


def lookup(table, rid):
    return DB.tables[table].get(rid)


# ---------------------------------------------------------------------------
# Pagination + listing
# ---------------------------------------------------------------------------
def parse_pagination():
    args = request.args
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    if "limit" in args and args.get("limit") != "":
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 422, "limit must be an integer")
        if limit < PAGE_LIMIT_MIN:
            limit = PAGE_LIMIT_MIN
        elif limit > PAGE_LIMIT_MAX:
            limit = PAGE_LIMIT_MAX
    if "offset" in args and args.get("offset") != "":
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 422, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(records):
    """records: list of raw entity dicts (already filtered). Sorts by _seq asc."""
    limit, offset = parse_pagination()
    ordered = sorted(records, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [public(r) for r in page], limit, offset, total


def filter_records(table, **filters):
    out = []
    for r in DB.tables[table].values():
        ok = True
        for k, v in filters.items():
            if v is not None and r.get(k) != v:
                ok = False
                break
        if ok:
            out.append(r)
    return out
