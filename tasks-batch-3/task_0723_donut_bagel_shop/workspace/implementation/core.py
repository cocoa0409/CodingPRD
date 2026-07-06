"""Core support: in-memory store, response envelope, errors, auth, helpers."""
import uuid
import random
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import g, request, jsonify


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"ShopAdmin", "BakeManager", "Cashier", "RouteDriver", "WholesaleClient"}

MARKDOWN_PCT = Decimal("0.40")
REWARD_VALUE_CENTS = 1200
PUNCHES_PER_REWARD = 10
CATERING_DEPOSIT_THRESHOLD_CENTS = 4050
DEPOSIT_PCT = Decimal("0.25")
CATERING_SLOT_CAPACITY = 2
ROUTE_BUFFER_MINUTES = 30

CLOCK_DEFAULT = "2026-03-01T00:00:00Z"

ALLERGEN_VALUES = {"WHEAT", "EGG", "MILK", "SOY", "NUT", "SESAME"}
CATEGORY_VALUES = {"DONUT", "BAGEL"}


# ---------------------------------------------------------------------------
# In-memory store (starts empty every boot; no seeding)
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.products = {}
        self.production_days = {}
        self.bake_batches = {}
        self.retail_orders = {}
        self.loyalty_accounts = {}
        self.wholesale_accounts = {}
        self.standing_orders = {}
        self.wholesale_deliveries = {}
        self.pre_orders = {}
        # payments recorded against wholesale accounts: list of {account_id, amount_cents}
        self.wholesale_payments = []
        self.clock = CLOCK_DEFAULT


db = Store()


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
# Time / id helpers
# ---------------------------------------------------------------------------
def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def _now_iso_precise():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


def request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def round_half_up(value):
    """value: Decimal -> int cents."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_iso(s):
    """Parse an ISO8601 instant (Z or offset) into an aware datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Common-field bookkeeping
# ---------------------------------------------------------------------------
def stamp_create(rec):
    ts = _now_iso_precise()
    rec["id"] = new_id()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    return rec


def touch(rec):
    rec["updated_at"] = _now_iso_precise()
    rec["version"] = rec.get("version", 1) + 1
    return rec


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _meta(extra=None):
    m = {
        "api_request_id": getattr(g, "api_request_id", request_id()),
        "api_request_timestamp": getattr(g, "api_request_ts", _now_iso_precise()),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def err_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def get_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_MISSING_AUTH", 401, "Missing or invalid auth headers")
    return uid, role


def require_roles(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403, "Role not permitted for this operation")


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def get_pagination():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 422, "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 422, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(records):
    """records: full filtered list (already sorted). Returns (page, limit, offset, total)."""
    limit, offset = get_pagination()
    total = len(records)
    page = records[offset:offset + limit]
    return page, limit, offset, total


def sort_by_created(records):
    return sorted(records, key=lambda r: (r["created_at"], r["id"]))


# ---------------------------------------------------------------------------
# Existence / body helpers
# ---------------------------------------------------------------------------
def get_or_404(table, _id):
    rec = table.get(_id)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced resource does not exist")
    return rec


def body_json():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 422, "Request body must be a JSON object")
    return data


def require_fields(body, fields):
    for f in fields:
        if body.get(f) is None:
            raise ApiError("ERR_INVALID_REQUEST", 422, f"Missing required field: {f}")
