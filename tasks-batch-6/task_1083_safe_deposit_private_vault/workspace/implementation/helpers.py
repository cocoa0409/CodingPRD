"""Errors, response envelope, auth, pagination, and record helpers."""
import random
import string
from flask import request, jsonify

import store
from store import DB, new_id, wall_now_iso, next_seq

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Convenience error factories -------------------------------------------------
def err_unauth(msg="Authentication required"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_forbidden(msg="Role not permitted for this operation"):
    return ApiError("ERR_FORBIDDEN_FOR_ROLE", 403, msg)


def err_not_found(msg="Referenced resource does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_invalid_request(msg="Malformed request body"):
    return ApiError("ERR_INVALID_REQUEST", 422, msg)


def err_validation(msg="Invalid query parameter"):
    return ApiError("ERR_VALIDATION", 400, msg)


def err_state(msg="Resource not in a valid state"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {"api_request_id": _request_id(), "api_request_timestamp": wall_now_iso()}
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, response_type="object", meta_extra=None):
    body = {
        "meta": _meta(meta_extra),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(items) < total_count,
    }
    return ok(items, 200, "array", meta_extra)


def error_response(exc):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": exc.error_id, "message": exc.message},
    }
    return jsonify(body), exc.http_status


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
VALID_ROLES = {"VaultAdmin", "BillingClerk", "VaultOfficer", "ComplianceOfficer", "Renter"}


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in VALID_ROLES:
        raise err_unauth()
    return uid, role


def require_role(role, allowed):
    """allowed is a set of role names; 'Any' means any authenticated role."""
    if "Any" in allowed:
        return
    if role not in allowed:
        raise err_forbidden()


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def parse_pagination():
    args = request.args
    limit_raw = args.get("limit", "10")
    offset_raw = args.get("offset", "0")
    try:
        limit = int(limit_raw)
    except (TypeError, ValueError):
        raise err_validation("limit must be an integer")
    try:
        offset = int(offset_raw)
    except (TypeError, ValueError):
        raise err_validation("offset must be an integer")
    if limit < 1 or limit > 100:
        raise err_validation("limit out of range")
    if offset < 0:
        raise err_validation("offset out of range")
    return limit, offset


def paginate(records):
    """records: already-sorted list of stored dicts. Returns (page, limit, offset, total)."""
    limit, offset = parse_pagination()
    total = len(records)
    page = records[offset:offset + limit]
    return page, limit, offset, total


# ---------------------------------------------------------------------------
# JSON body
# ---------------------------------------------------------------------------
def get_body():
    if request.method in ("POST", "PUT", "PATCH"):
        data = request.get_json(silent=True)
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise err_invalid_request("Request body must be a JSON object")
        return data
    return {}


# ---------------------------------------------------------------------------
# Record lifecycle
# ---------------------------------------------------------------------------
COMMON_LESS = "access_events"  # collection with no version/updated_at


def make_record(fields, common=True):
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = wall_now_iso()
    rec["_seq"] = next_seq()
    if common:
        rec["updated_at"] = wall_now_iso()
        rec["version"] = 1
    return rec


def touch(rec):
    """Bump version + updated_at on a mutation."""
    if "version" in rec:
        rec["version"] += 1
        rec["updated_at"] = wall_now_iso()


def public(rec):
    """Strip internal fields for the response."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------
def get_or_404(collection, rid):
    rec = DB[collection].get(rid)
    if rec is None:
        raise err_not_found(f"{collection} {rid} not found")
    return rec


def fk_or_404(collection, rid):
    """Validate a body foreign key; None is treated as not-provided by caller."""
    rec = DB[collection].get(rid)
    if rec is None:
        raise err_not_found(f"{collection} {rid} not found")
    return rec


def sorted_records(collection):
    return sorted(DB[collection].values(), key=lambda r: r["_seq"])
