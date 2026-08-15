"""Shared helpers: errors, response envelope, auth, validation, timestamps."""
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request, jsonify

import db

ROLES = {
    "PlantManager", "ComplianceOfficer", "Regulator", "ProcurementManager",
    "RouteDispatcher", "ScalehouseOperator", "ProductionSupervisor",
    "QualityLabTech", "SalesManager", "FinanceAnalyst", "Any",
}


class ApiError(Exception):
    def __init__(self, error_id, status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.status = status
        self.message = message or error_id


def fail(error_id, status, message=None):
    raise ApiError(error_id, status, message)


# ---------------- envelope ----------------

def iso_z(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def ok(data, status=200, resp_type="object", pagination=None):
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": iso_z(datetime.now(timezone.utc)),
    }
    if pagination is not None:
        meta.update(pagination)
    return jsonify({"meta": meta, "response_type": resp_type, "data": data}), status


def error_body(error_id, message):
    return {
        "meta": {
            "api_request_id": "req_" + uuid.uuid4().hex[:20],
            "api_request_timestamp": iso_z(datetime.now(timezone.utc)),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# ---------------- auth ----------------

def caller():
    """Validation priority 1: header presence + declared role."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        fail("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
             "X-User-ID and X-User-Role headers must be present and X-User-Role must name a declared role")
    return uid, role


def require_role(role, *allowed):
    """Validation priority 3: role must be listed for the endpoint."""
    if role not in allowed:
        fail("ERR_INSUFFICIENT_PERMISSIONS", 403, "Role not permitted for this endpoint")


# ---------------- body validation (priority 2: ERR_INVALID_REQUEST) ----------------

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def body_json():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return data


def _bad(field, msg):
    fail("ERR_INVALID_REQUEST", 400, f"{field}: {msg}")


def v_str(b, f, required=True, default=None):
    v = b.get(f)
    if v is None:
        if required:
            _bad(f, "required")
        return default
    if not isinstance(v, str) or v == "":
        _bad(f, "must be a non-empty string")
    return v


def v_int(b, f, minv=None, required=True, default=None):
    v = b.get(f)
    if v is None:
        if required:
            _bad(f, "required")
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(f, "must be an integer")
    if minv is not None and v < minv:
        _bad(f, f"must be >= {minv}")
    return v


def v_num(b, f, required=True, default=None):
    v = b.get(f)
    if v is None:
        if required:
            _bad(f, "required")
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad(f, "must be a number")
    return v


def v_bool(b, f, required=True, default=None):
    v = b.get(f)
    if v is None:
        if required:
            _bad(f, "required")
        return default
    if not isinstance(v, bool):
        _bad(f, "must be a boolean")
    return v


def v_enum(b, f, allowed, required=True, default=None):
    v = b.get(f)
    if v is None:
        if required:
            _bad(f, "required")
        return default
    if not isinstance(v, str) or v not in allowed:
        _bad(f, "must be one of " + ",".join(sorted(allowed)))
    return v


def parse_date_str(s):
    if not isinstance(s, str) or not DATE_RE.match(s):
        return None
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return None
    return s


def v_date(b, f, required=True, default=None):
    v = b.get(f)
    if v is None:
        if required:
            _bad(f, "required")
        return default
    if parse_date_str(v) is None:
        _bad(f, "must be a YYYY-MM-DD date")
    return v


def parse_dt(s):
    """Parse an ISO8601 timestamp to an aware UTC datetime, or None."""
    if not isinstance(s, str):
        return None
    t = s.strip()
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def v_datetime(b, f, whole_hour=False, required=True, default=None):
    v = b.get(f)
    if v is None:
        if required:
            _bad(f, "required")
        return default
    dt = parse_dt(v)
    if dt is None:
        _bad(f, "must be an ISO8601 timestamp")
    if whole_hour and (dt.minute or dt.second or dt.microsecond):
        _bad(f, "must fall on a whole hour")
    return v


def v_list(b, f, required=True, default=None, non_empty=False):
    v = b.get(f)
    if v is None:
        if required:
            _bad(f, "required")
        return default
    if not isinstance(v, list):
        _bad(f, "must be a list")
    if non_empty and len(v) == 0:
        _bad(f, "must be non-empty")
    return v


def rhu(x, places=0):
    """Round half-up; returns Decimal."""
    q = Decimal(1) if places == 0 else Decimal(1).scaleb(-places)
    if not isinstance(x, Decimal):
        x = Decimal(str(x))
    return x.quantize(q, rounding=ROUND_HALF_UP)


# ---------------- entity helpers ----------------

def stamp_new(ent, common=True):
    ent["id"] = str(uuid.uuid4())
    ent["_seq"] = db.next_seq()
    ent["created_at"] = iso_z(db.now())
    if common:
        ent["updated_at"] = ent["created_at"]
        ent["version"] = 1


def touch(ent):
    ent["updated_at"] = iso_z(db.now())
    ent["version"] += 1


def view(ent):
    return {k: v for k, v in ent.items() if not k.startswith("_")}


def get_or_404(store, rid, error_id):
    ent = db.STORES[store].get(rid)
    if ent is None:
        fail(error_id, 404, f"resource not found: {rid}")
    return ent


def sorted_items(store_name, filters=None):
    items = list(db.STORES[store_name].values())
    if filters:
        for k, v in filters.items():
            if v is not None:
                items = [x for x in items if x.get(k) == v]
    items.sort(key=lambda x: (x["created_at"], x["_seq"]))
    return items


def paginate(items, viewfn=view):
    """Returns flask response for a list endpoint."""
    args = request.args
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", 400, "offset must be an integer")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return ok([viewfn(x) for x in page], 200, resp_type="array", pagination=pagination)
