"""Shared utilities: errors, response envelope, auth, time, ids, serialization."""
import random
import string
import uuid
from datetime import datetime, timezone, date
from decimal import Decimal, ROUND_HALF_UP

from flask import request, jsonify, g

from store import store

VALID_ROLES = {"Anonymous", "Resident", "Reviewer", "BudgetAdmin"}
LANGUAGES = {"en", "es", "zh", "vi", "ar"}
PHASE_ORDER = ["DRAFT", "SUBMISSION", "DEVELOPMENT", "VOTING", "SELECTION",
               "IMPLEMENTATION", "CLOSED"]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=None):
    raise ApiError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# Ids & time
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def fmt_iso(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def wall_now():
    return datetime.now(timezone.utc)


def clock_now():
    return store.clock


def parse_iso(s):
    if s is None:
        return None
    if not isinstance(s, str):
        raise ValueError("not a string")
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------
def round_half_up(value):
    """Round a Decimal to whole integer cents, half away from zero (upward)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def base_meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_iso(wall_now()),
    }


def respond(data, response_type="object", status=200, extra_meta=None):
    meta = base_meta()
    if extra_meta:
        meta.update(extra_meta)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def error_body(e):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def authenticate(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in VALID_ROLES:
        err("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers.")
    if role == "Anonymous" and "Anonymous" not in allowed_roles:
        err("ERR_UNAUTHENTICATED", 401, "Anonymous is not permitted on this endpoint.")
    if role not in allowed_roles:
        err("ERR_UNAUTHORIZED", 403, "Role is not permitted to perform this operation.")
    return uid, role


# ---------------------------------------------------------------------------
# Versioning / mutation tracking (bump each resource at most once per request)
# ---------------------------------------------------------------------------
def _touched():
    if not hasattr(g, "_touched_ids"):
        g._touched_ids = set()
    return g._touched_ids


def touch(entity):
    """Advance updated_at and version for a resource mutation, at most once
    per request. Report-backs (no version) are never touched."""
    if entity is None or "version" not in entity:
        return
    tid = id(entity)
    seen = _touched()
    if tid in seen:
        return
    seen.add(tid)
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = fmt_iso(wall_now())


def set_common(entity):
    """Populate id/created_at/updated_at/version and insertion sequence."""
    now = fmt_iso(wall_now())
    entity["id"] = new_id()
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    entity["_seq"] = store.next_seq()
    return entity


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def pub(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def compute_age(dob_str, now):
    try:
        dob = date.fromisoformat(dob_str)
    except Exception:
        return 0
    return now.year - dob.year - (
        1 if (now.month, now.day) < (dob.month, dob.day) else 0
    )


def pub_resident(r):
    d = pub(r)
    d["age"] = compute_age(r.get("date_of_birth"), clock_now())
    return d


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def get_pagination():
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paginate(items):
    """items: list already sorted. Returns (page_slice, pagination_meta)."""
    limit, offset = get_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


# ---------------------------------------------------------------------------
# Request body helpers
# ---------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        err("ERR_VALIDATION", 400, "Request body must be a JSON object.")
    return data


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            err("ERR_VALIDATION", 400, "Missing required field: %s" % f)


def as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        err("ERR_VALIDATION", 400, "Field %s must be an integer." % field)
    return value


def sorted_by_seq(items):
    return sorted(items, key=lambda x: x["_seq"])
