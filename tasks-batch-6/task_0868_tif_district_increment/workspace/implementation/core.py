"""Core infrastructure: in-memory store, response envelope, auth, errors."""
import random
import string
import uuid
from datetime import datetime, timezone

from flask import g, jsonify, request

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
ROLES = {"MunicipalAdmin", "CountyClerk", "Developer", "TaxingBodyRep"}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# In-memory store (wiped on every process boot)
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.districts = {}
        self.taxing_bodies = {}
        self.developers = {}
        self.project_funds = {}
        self.obligations = {}
        self.increment_records = {}
        self.disbursements = {}
        self.annual_reports = {}
        self.surplus_distributions = {}
        self.surplus_agreements = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# ---------------------------------------------------------------------------
# Helpers: ids, timestamps
# ---------------------------------------------------------------------------
def new_uuid():
    return str(uuid.uuid4())


def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_request_id():
    chars = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(chars, k=20))


# ---------------------------------------------------------------------------
# Entity construction / mutation
# ---------------------------------------------------------------------------
def make_entity(fields, common=True):
    """Build a fresh entity dict with system fields."""
    ts = now_iso()
    ent = dict(fields)
    ent["id"] = new_uuid()
    ent["created_at"] = ts
    ent["_seq"] = db.next_seq()
    if common:
        ent["updated_at"] = ts
        ent["version"] = 1
    return ent


def bump(entity):
    """Refresh updated_at and increment version (common-field entities only)."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _meta(extra=None):
    m = {"api_request_id": new_request_id(), "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def success(data, status=200, response_type="object", meta_extra=None):
    body = {
        "meta": _meta(meta_extra),
        "response_type": response_type,
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(err: ApiError):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    resp = jsonify(body)
    resp.status_code = err.http_status
    return resp


# ---------------------------------------------------------------------------
# Pagination + list response
# ---------------------------------------------------------------------------
def _sort_key(e):
    return (e.get("created_at", ""), e.get("_seq", 0))


def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 422, "limit must be an integer")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100
    if "offset" in args and args.get("offset") != "":
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 422, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def list_response(items):
    """items: list of entity dicts (unsorted). Sorts, paginates, serializes."""
    limit, offset = parse_pagination()
    ordered = sorted(items, key=_sort_key)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return success(
        [serialize(e) for e in page],
        status=200,
        response_type="array",
        meta_extra=meta_extra,
    )


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unknown auth headers")
    g.user_id = user_id
    g.role = role
    return user_id, role


def require_role(allowed):
    """allowed: iterable of role names permitted for the write operation."""
    if g.role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")


# ---------------------------------------------------------------------------
# Body parsing / field validation
# ---------------------------------------------------------------------------
def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", 422, "Body must be a JSON object")
    return body


def require_present(body, key):
    if key not in body or body[key] is None:
        raise ApiError("ERR_VALIDATION", 422, f"Missing required field: {key}")
    return body[key]


def as_int(value, key, minimum=None, maximum=None, exclusive_min=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_VALIDATION", 422, f"{key} must be an integer")
    if minimum is not None and value < minimum:
        raise ApiError("ERR_VALIDATION", 422, f"{key} below minimum")
    if exclusive_min is not None and value <= exclusive_min:
        raise ApiError("ERR_VALIDATION", 422, f"{key} must be > {exclusive_min}")
    if maximum is not None and value > maximum:
        raise ApiError("ERR_VALIDATION", 422, f"{key} above maximum")
    return value


def as_number(value, key):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError("ERR_VALIDATION", 422, f"{key} must be a number")
    return value


def as_str(value, key):
    if not isinstance(value, str) or value == "":
        raise ApiError("ERR_VALIDATION", 422, f"{key} must be a non-empty string")
    return value


def as_enum(value, key, choices):
    if value not in choices:
        raise ApiError("ERR_VALIDATION", 422, f"{key} must be one of {sorted(choices)}")
    return value
