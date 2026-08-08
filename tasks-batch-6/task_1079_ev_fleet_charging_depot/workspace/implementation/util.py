"""Errors, response envelope, auth, pagination, and calculation helpers."""
from decimal import Decimal, ROUND_HALF_UP
from flask import request, jsonify

import db

# ---------------------------------------------------------------------------
# Constants (declared in scaffold/PRD)
# ---------------------------------------------------------------------------
MIN_READY_SOC_PCT = 80
COOLDOWN_BUFFER_MINUTES = 30

KNOWN_ROLES = {"FleetManager", "DepotOperator", "MaintenanceTech", "Driver", "FinanceManager"}

CONNECTORS = {"CCS", "CHADEMO", "J1772", "NACS"}
SEVERITIES = {"LOW", "MEDIUM", "HIGH"}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _meta(extra=None):
    m = {
        "api_request_id": db.request_id(),
        "api_request_timestamp": db.iso_out(db.now()),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, is_list=False, pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": "array" if is_list else "object",
        "data": data,
    }
    return jsonify(body), status


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def authenticate():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers.")
    return user_id, role


def require_roles(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation.")


# ---------------------------------------------------------------------------
# Body / field validation helpers
# ---------------------------------------------------------------------------
def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", 422, "Request body must be a JSON object.")
    return body


def require_fields(body, fields):
    for f in fields:
        if body.get(f) is None:
            raise ApiError("ERR_VALIDATION", 422, f"Missing required field: {f}")


def as_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError("ERR_VALIDATION", 422, f"{name} must be a number.")
    return value


def check_soc(value, name="soc"):
    v = as_number(value, name)
    if v < 0 or v > 100:
        raise ApiError("ERR_VALIDATION", 422, f"{name} must be between 0 and 100.")
    return v


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def paginate(items):
    """items already sorted. Returns (page_items, meta_dict)."""
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta


def sorted_by_created(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


# ---------------------------------------------------------------------------
# Money / rounding
# ---------------------------------------------------------------------------
def D(x):
    return Decimal(str(x))


def round_half_up_cents(value):
    """value: Decimal or number -> int whole cents, round half up."""
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Tariff windows
# ---------------------------------------------------------------------------
def rate_at(tariff_windows, hour):
    """Return rate_cents_per_kwh of the window covering the given UTC hour."""
    for w in tariff_windows:
        start = w["start_hour_utc"]
        end = w["end_hour_utc"]
        if start <= end:
            covered = start <= hour < end
        else:  # wrapping window
            covered = hour >= start or hour < end
        if covered:
            return w["rate_cents_per_kwh"]
    return 0
