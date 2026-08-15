"""Core infrastructure: in-memory store, logical clock, errors, envelope, auth, parsing, pagination."""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone

from flask import jsonify, request

UTC = timezone.utc

# ------------------------------------------------------------------ store
# In-memory only. The store starts EMPTY on every boot; nothing is seeded.
db = {
    "employees": {},
    "venues": {},
    "arrangements": {},
    "orders": {},
    "snapshots": {},
    "disclosures": {},
    "reviews": {},
    "alerts": {},
    "cases": {},
    "trades": {},
    "restricted": {},
    "comm_items": {},
    "lexicon": {},
    "policies": {},
    "training": {},
}

# ------------------------------------------------------------------ logical clock
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
_clock = {"now": CLOCK_START}


def now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


# ------------------------------------------------------------------ errors
class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def fail(error_id, status, message):
    raise ApiError(error_id, status, message)


# ------------------------------------------------------------------ ids / timestamps
def new_id():
    return str(uuid.uuid4())


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def parse_dt(v, field):
    if not isinstance(v, str):
        fail("ERR_INVALID_REQUEST", 400, field + " must be an ISO 8601 datetime string")
    s = v.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        fail("ERR_INVALID_REQUEST", 400, field + " is not a valid ISO 8601 datetime")
    if d.tzinfo is None:
        d = d.replace(tzinfo=UTC)
    return d.astimezone(UTC)


# ------------------------------------------------------------------ envelope
def _meta():
    rid = "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return {"api_request_id": rid, "api_request_timestamp": fmt_dt(now())}


def ok(data, rtype="object", status=200, page=None):
    meta = _meta()
    if page:
        meta.update(page)
    return jsonify({"meta": meta, "response_type": rtype, "data": data}), status


def err_body(e):
    return jsonify({"meta": _meta(), "response_type": "error",
                    "data": {"error_id": e.error_id, "message": e.message}}), e.status


# ------------------------------------------------------------------ pagination
def paginate(items):
    args = request.args
    try:
        limit = int(args.get("limit", "10"))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", "0"))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page_items = items[offset:offset + limit]
    return page_items, {"limit": limit, "offset": offset,
                        "total_count": total, "has_more": offset + limit < total}


def sorted_rows(rows):
    """List responses are sorted by created_at ascending (stable for ties)."""
    return sorted(rows, key=lambda r: r["created_at"])


# ------------------------------------------------------------------ auth
ROLES = ("OpsAdmin", "ComplianceAdmin", "SurveillanceAnalyst", "FilingOfficer",
         "BestExAnalyst", "CommitteeMember", "CoveredEmployee")


def identity():
    role = request.headers.get("X-User-Role")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", 401, "X-User-Role header missing or not a declared role")
    return request.headers.get("X-User-ID"), role


def require_roles(*roles):
    uid, role = identity()
    if role not in roles:
        fail("ERR_FORBIDDEN", 403, "role %s is not permitted for this endpoint" % role)
    return uid


def require_any_role():
    uid, _ = identity()
    return uid


def require_transition_roles(target_roles):
    """target_roles: dict of to_status -> set of permitted roles. Returns (uid, body)."""
    uid, role = identity()
    if not any(role in rs for rs in target_roles.values()):
        fail("ERR_FORBIDDEN", 403, "role %s is not permitted for this endpoint" % role)
    body = get_body()
    to = body.get("to_status")
    if isinstance(to, str) and to in target_roles and role not in target_roles[to]:
        fail("ERR_FORBIDDEN", 403, "role %s is not permitted for transition target %s" % (role, to))
    return uid, body


# ------------------------------------------------------------------ body / field helpers
def get_body():
    data = request.get_data()
    if not data:
        return {}
    body = None
    try:
        body = request.get_json(silent=True)
    except Exception:
        body = None
    if body is None or not isinstance(body, dict):
        fail("ERR_INVALID_REQUEST", 400, "request body must be a JSON object")
    return body


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        fail("ERR_INVALID_REQUEST", 400, field + " is required and must be a non-empty string")
    return v


def req_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        fail("ERR_INVALID_REQUEST", 400, field + " is required and must be an integer")
    return v


def req_num(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        fail("ERR_INVALID_REQUEST", 400, field + " is required and must be a number")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        fail("ERR_INVALID_REQUEST", 400, field + " must be one of: " + ", ".join(sorted(allowed)))
    return v


def req_dt_field(body, field):
    return parse_dt(body.get(field), field)


def opt_dt_field(body, field):
    if field not in body or body[field] is None:
        return None
    return parse_dt(body[field], field)


# ------------------------------------------------------------------ resource helpers
def new_resource():
    t = now()
    return {"id": new_id(), "created_at": t, "updated_at": t, "version": 1}


def bump(r):
    r["updated_at"] = now()
    r["version"] += 1


def get_or_404(kind, rid):
    r = db[kind].get(rid) if isinstance(rid, str) else None
    if r is None:
        fail("ERR_NOT_FOUND", 404, "resource %s not found" % rid)
    return r
