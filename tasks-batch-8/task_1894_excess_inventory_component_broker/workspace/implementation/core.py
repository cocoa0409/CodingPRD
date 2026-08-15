"""Core infrastructure: in-memory store, logical clock, envelope, auth, validation."""

import random
import string
import threading
import uuid
from datetime import datetime, timezone

from flask import g, jsonify, request

# ----------------------------- error catalogue ------------------------------
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"
ERR_FORBIDDEN_OWNERSHIP = "ERR_FORBIDDEN_OWNERSHIP"
ERR_SELLER_NOT_FOUND = "ERR_SELLER_NOT_FOUND"
ERR_CUSTOMER_NOT_FOUND = "ERR_CUSTOMER_NOT_FOUND"
ERR_STORAGE_BIN_NOT_FOUND = "ERR_STORAGE_BIN_NOT_FOUND"
ERR_BUY_OFFER_NOT_FOUND = "ERR_BUY_OFFER_NOT_FOUND"
ERR_LOT_NOT_FOUND = "ERR_LOT_NOT_FOUND"
ERR_LISTING_NOT_FOUND = "ERR_LISTING_NOT_FOUND"
ERR_SALES_ORDER_NOT_FOUND = "ERR_SALES_ORDER_NOT_FOUND"
ERR_CONSIGNMENT_AGREEMENT_NOT_FOUND = "ERR_CONSIGNMENT_AGREEMENT_NOT_FOUND"
ERR_RETURN_CASE_NOT_FOUND = "ERR_RETURN_CASE_NOT_FOUND"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_LISTING_NOT_ACTIVE = "ERR_LISTING_NOT_ACTIVE"
ERR_LOT_NOT_IN_STOCK = "ERR_LOT_NOT_IN_STOCK"
ERR_LOT_QUARANTINED = "ERR_LOT_QUARANTINED"
ERR_ORDER_NOT_DELIVERED = "ERR_ORDER_NOT_DELIVERED"
ERR_AGREEMENT_NOT_ACTIVE = "ERR_AGREEMENT_NOT_ACTIVE"
ERR_LOT_NOT_CONSIGNMENT = "ERR_LOT_NOT_CONSIGNMENT"
ERR_COUNTERFEIT_SUSPECTED = "ERR_COUNTERFEIT_SUSPECTED"
ERR_PROVENANCE_DOCUMENT_REQUIRED = "ERR_PROVENANCE_DOCUMENT_REQUIRED"
ERR_CONSIGNMENT_WINDOW_INVALID = "ERR_CONSIGNMENT_WINDOW_INVALID"
ERR_CONSIGNMENT_WINDOW_OVERLAP = "ERR_CONSIGNMENT_WINDOW_OVERLAP"
ERR_NO_CURRENT_CONSIGNMENT_AGREEMENT = "ERR_NO_CURRENT_CONSIGNMENT_AGREEMENT"
ERR_BIN_CAPACITY_EXCEEDED = "ERR_BIN_CAPACITY_EXCEEDED"
ERR_QUANTITY_EXCEEDS_AVAILABLE = "ERR_QUANTITY_EXCEEDS_AVAILABLE"
ERR_ASKING_BELOW_COST_FLOOR = "ERR_ASKING_BELOW_COST_FLOOR"
ERR_ESCROW_OVERPAYMENT = "ERR_ESCROW_OVERPAYMENT"
ERR_CONSIGNMENT_SELLER_MISMATCH = "ERR_CONSIGNMENT_SELLER_MISMATCH"
ERR_INVALID_FEE_BPS = "ERR_INVALID_FEE_BPS"
ERR_DUPLICATE_BIN_CODE = "ERR_DUPLICATE_BIN_CODE"
ERR_INSUFFICIENT_CUSTOMER_CREDIT = "ERR_INSUFFICIENT_CUSTOMER_CREDIT"
ERR_INVALID_AMOUNT = "ERR_INVALID_AMOUNT"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


# ------------------------------- data store ---------------------------------
class Store:
    def __init__(self):
        self.sellers = {}
        self.customers = {}
        self.bins = {}
        self.offers = {}
        self.lots = {}
        self.agreements = {}
        self.snapshots = {}
        self.listings = {}
        self.orders = {}
        self.escrow = {}
        self.return_cases = {}
        self.seq = 0
        # Logical clock startup default: exactly 2026-08-01T00:00:00Z
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


DB = Store()
LOCK = threading.RLock()

ROLES = ("BrokerOps", "Inspector", "FinanceAdmin", "Seller", "Customer")


def next_seq():
    DB.seq += 1
    return DB.seq


# ------------------------------ time handling -------------------------------
def now_dt():
    return DB.clock


def iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO 8601 string into an aware UTC datetime; None on failure."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ----------------------------- entity helpers -------------------------------
def new_id():
    return str(uuid.uuid4())


def new_entity():
    ts = now_dt()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(e):
    e["updated_at"] = now_dt()
    e["version"] += 1


# ------------------------------- envelope -----------------------------------
def _meta():
    return {
        "api_request_id": "req_"
        + "".join(random.choices(string.ascii_letters + string.digits, k=20)),
        "api_request_timestamp": iso(now_dt()),
    }


def ok_object(data, code=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), code


def ok_list(items, total, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(items)) < total
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def err_response(error_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# --------------------------------- auth -------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED,
            401,
            "Missing or invalid X-User-ID / X-User-Role headers",
        )
    g.uid = uid
    g.role = role


def require_roles(*roles):
    if g.role not in roles:
        raise ApiError(ERR_FORBIDDEN_ROLE, 403, "Role not permitted for this endpoint")


def forbid_ownership(message="Caller does not own this resource"):
    raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403, message)


# --------------------------- payload validation -----------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data


def _present(data, name):
    return name in data and data[name] is not None


def _bad(name):
    raise ApiError(ERR_INVALID_REQUEST, 400, "Missing or invalid field: %s" % name)


def req_str(data, name):
    if not _present(data, name) or not isinstance(data[name], str):
        _bad(name)
    return data[name]


def opt_str(data, name, default=None):
    if not _present(data, name):
        return default
    if not isinstance(data[name], str):
        _bad(name)
    return data[name]


def req_int(data, name):
    if (
        not _present(data, name)
        or isinstance(data[name], bool)
        or not isinstance(data[name], int)
    ):
        _bad(name)
    return data[name]


def opt_int(data, name, default=None):
    if not _present(data, name):
        return default
    if isinstance(data[name], bool) or not isinstance(data[name], int):
        _bad(name)
    return data[name]


def req_enum(data, name, values):
    if not _present(data, name) or data[name] not in values:
        _bad(name)
    return data[name]


def opt_enum(data, name, values, default=None):
    if not _present(data, name):
        return default
    if data[name] not in values:
        _bad(name)
    return data[name]


def req_dt(data, name):
    if not _present(data, name):
        _bad(name)
    dt = parse_dt(data[name])
    if dt is None:
        _bad(name)
    return dt


# ------------------------------ pagination ----------------------------------
def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid pagination parameters")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def list_response(records, serializer):
    limit, offset = pagination()
    total = len(records)
    page = records[offset : offset + limit]
    return ok_list([serializer(r) for r in page], total, limit, offset)
