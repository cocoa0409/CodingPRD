"""Core plumbing: API errors, response envelope, auth, parsing/validation.

Every structural name (headers, envelope fields, pagination params, error
IDs) follows the task's PRD/scaffold exactly:
  - headers: X-User-ID / X-User-Role
  - envelope: {"meta": {...}, "response_type": ..., "data": ...}
  - pagination: limit / offset / total_count / has_more (default 10/0, 1..100)
"""

import random
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

import store

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_unauthenticated(msg="Missing or invalid X-User-ID / X-User-Role headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_forbidden(msg="The caller is not permitted to perform this operation"):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def err_not_found(msg="Referenced resource does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_invalid(msg="The request body is invalid"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_state(msg="The resource is not in a state that permits this operation"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# ---------------------------------------------------------------------------


def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta():
    # The program runs on a logical clock rather than wall-clock time (PRD 2.7).
    return {
        "api_request_id": _req_id(),
        "api_request_timestamp": store.fmt_ts(store.clock_now()),
    }


def to_jsonable(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, dict):
        return {k: to_jsonable(x) for k, x in v.items() if not k.startswith("_")}
    if isinstance(v, list):
        return [to_jsonable(x) for x in v]
    return v


def ok(data, status=200, response_type="object", pagination=None):
    meta = _meta()
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": to_jsonable(data)}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def ok_list(items, pagination):
    return ok(items, status=200, response_type="array", pagination=pagination)


def err_response(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    resp = jsonify(body)
    resp.status_code = e.http_status
    return resp


# ---------------------------------------------------------------------------
# Auth (PRD 2.1, validation priorities 1-2)
# ---------------------------------------------------------------------------

ROLES = {"ProgramAdmin", "ProgramCoordinator", "Observer", "Debriefer", "VesselOperator", "EMReviewer"}
ENTITY_ROLES = {
    "Observer": "observers",
    "Debriefer": "debriefers",
    "VesselOperator": "operators",
    "EMReviewer": "em_reviewers",
}
ALL_ROLES = ("ProgramAdmin", "ProgramCoordinator", "Observer", "Debriefer", "VesselOperator", "EMReviewer")


def actor():
    """Authenticate the caller. Returns {"id", "role", "entity"}."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err_unauthenticated()
    ent = None
    if role in ENTITY_ROLES:
        ent = store.db[ENTITY_ROLES[role]].get(uid)
        if ent is None:
            raise err_unauthenticated("X-User-ID does not resolve to an existing " + role)
        if ent["status"] == "SUSPENDED":
            raise err_forbidden("The acting " + role + " is SUSPENDED")
    return {"id": uid, "role": role, "entity": ent}


def require_roles(*roles):
    a = actor()
    if a["role"] not in roles:
        raise err_forbidden("Role " + a["role"] + " may not perform this operation")
    return a


# ---------------------------------------------------------------------------
# Request body + field validation (priority 4 schema)
# ---------------------------------------------------------------------------


def body():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise err_invalid("Request body must be a JSON object")
    return b


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_str(b, f):
    v = b.get(f)
    if v is None or not isinstance(v, str) or v == "":
        raise err_invalid("Field '%s' is required and must be a string" % f)
    return v


def opt_str(b, f):
    v = b.get(f)
    if v is None:
        return None
    if not isinstance(v, str):
        raise err_invalid("Field '%s' must be a string" % f)
    return v


def req_bool(b, f):
    v = b.get(f)
    if v is None or not isinstance(v, bool):
        raise err_invalid("Field '%s' is required and must be a boolean" % f)
    return v


def req_int(b, f):
    v = b.get(f)
    if v is None or not is_int(v):
        raise err_invalid("Field '%s' is required and must be an integer" % f)
    return v


def opt_int(b, f):
    v = b.get(f)
    if v is None:
        return None
    if not is_int(v):
        raise err_invalid("Field '%s' must be an integer" % f)
    return v


def req_num(b, f):
    v = b.get(f)
    if v is None or not is_num(v):
        raise err_invalid("Field '%s' is required and must be a number" % f)
    return v


def opt_num(b, f):
    v = b.get(f)
    if v is None:
        return None
    if not is_num(v):
        raise err_invalid("Field '%s' must be a number" % f)
    return v


def req_enum(b, f, allowed):
    v = b.get(f)
    if v is None or not isinstance(v, str) or v not in allowed:
        raise err_invalid("Field '%s' is required and must be one of %s" % (f, sorted(allowed)))
    return v


def opt_enum(b, f, allowed):
    v = b.get(f)
    if v is None:
        return None
    if not isinstance(v, str) or v not in allowed:
        raise err_invalid("Field '%s' must be one of %s" % (f, sorted(allowed)))
    return v


def parse_dt(s):
    """Parse an ISO 8601 date/datetime; date-only values become UTC midnight."""
    if not isinstance(s, str):
        raise err_invalid("Expected an ISO 8601 date/datetime string")
    t = s.strip()
    try:
        if len(t) == 10:
            dt = datetime.strptime(t, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        raise err_invalid("Malformed ISO 8601 date/datetime: %r" % s)
    return dt


def req_dt(b, f):
    v = b.get(f)
    if v is None:
        raise err_invalid("Field '%s' is required" % f)
    parse_dt(v)
    return v


def opt_dt(b, f):
    v = b.get(f)
    if v is None:
        return None
    parse_dt(v)
    return v


def dec(v):
    return Decimal(str(v))


def round4(v):
    return Decimal(v).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def round2(v):
    return Decimal(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round0(v):
    return Decimal(v).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def req_decimal2(b, f):
    """A numeric field carried at 2 decimal places (PRD 2.6); stored as Decimal."""
    v = req_num(b, f)
    d = dec(v)
    if d.as_tuple().exponent < -2:
        raise err_invalid("Field '%s' must carry at most 2 decimal places" % f)
    return d


# ---------------------------------------------------------------------------
# Existence + pagination
# ---------------------------------------------------------------------------


def get_or_404(collection, rid, label="Resource"):
    e = store.db[collection].get(rid)
    if e is None:
        raise err_not_found("%s %s does not exist" % (label, rid))
    return e


def parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_invalid("Query parameter 'limit' must be an integer")
        if str(limit) != raw_limit.strip() and not raw_limit.strip().lstrip("+").isdigit():
            raise err_invalid("Query parameter 'limit' must be an integer")
        if limit < 1 or limit > 100:
            raise err_invalid("Query parameter 'limit' must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_invalid("Query parameter 'offset' must be an integer")
        if str(offset) != raw_offset.strip() and not raw_offset.strip().lstrip("+").isdigit():
            raise err_invalid("Query parameter 'offset' must be an integer")
        if offset < 0:
            raise err_invalid("Query parameter 'offset' must be >= 0")
    return limit, offset


def list_response(collection, filters=None):
    """filters: dict of query-param -> entity field equality checks."""
    limit, offset = parse_pagination()
    items = list(store.db[collection].values())
    if filters:
        for param, field in filters.items():
            val = request.args.get(param)
            if val is not None:
                items = [e for e in items if str(e.get(field)) == val]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return ok_list(page, pagination)
