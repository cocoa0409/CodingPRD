"""Core infrastructure: in-memory store, logical clock, ids, timestamps,
response envelope, errors, auth."""
import uuid
import random
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from flask import request, jsonify

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.clients = {}
        self.properties = {}
        self.engineers = {}
        self.studies = {}
        self.asset_components = {}
        self.qre_line_items = {}
        self.reports = {}
        self.audit_cases = {}
        self.amended_returns = {}
        self.fee_invoices = {}
        self._seq = 0
        # Logical clock — startup default per PRD §2.6
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()

ROLES = {"StudyManager", "Engineer", "Reviewer", "CPA"}


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def fmt_ts(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def real_now():
    return datetime.now(timezone.utc)


def parse_iso(s):
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", 400, "Invalid datetime")
    v = s.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 400, "Invalid datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


# ---------------------------------------------------------------------------
# Common field helpers
# ---------------------------------------------------------------------------
def base_fields(with_version=True):
    now = real_now()
    d = {
        "id": new_id(),
        "created_at": now,
        "_seq": db.next_seq(),
    }
    if with_version:
        d["updated_at"] = now
        d["version"] = 1
    return d


def touch(entity):
    """Refresh updated_at and bump version on a mutation."""
    entity["updated_at"] = real_now()
    if "version" in entity:
        entity["version"] = entity.get("version", 1) + 1


def common_out(entity, with_version=True):
    out = {
        "id": entity["id"],
        "created_at": fmt_ts(entity["created_at"]),
    }
    if with_version:
        out["updated_at"] = fmt_ts(entity["updated_at"])
        out["version"] = entity["version"]
    return out


# ---------------------------------------------------------------------------
# Rounding / decimal helpers
# ---------------------------------------------------------------------------
def D(x):
    return Decimal(str(x))


def rhu(value):
    """Round half up to whole integer (cents)."""
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _meta(extra=None):
    m = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_ts(real_now()),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + limit < total_count,
        }),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def err_response(e: ApiError):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def require_role(*allowed):
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid X-User-Role")
    if allowed and role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")
    return role


def user_id():
    return request.headers.get("X-User-ID")


# ---------------------------------------------------------------------------
# Body / field helpers
# ---------------------------------------------------------------------------
def get_body():
    if request.method == "GET":
        return {}
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 400, "Malformed request body")
    return data


def require_fields(body, *names):
    for n in names:
        if n not in body or body[n] is None:
            raise ApiError("ERR_VALIDATION", 400, f"Missing required field: {n}")


def paginate(query):
    try:
        limit = int(query.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(query.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def sort_key(e):
    return (e["created_at"], e["_seq"])
