"""Helpers: time, ids, decimals, validation, envelopes."""

import re
import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from flask import request, jsonify

from errors import err
from store import db


# ---------- time ----------

def now_iso() -> str:
    """Logical clock timestamp in ISO8601 UTC with 3 fractional digits, Z suffix."""
    dt = db.clock
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def today_date() -> date:
    return db.clock.date()


def parse_iso_date(s):
    """Parse YYYY-MM-DD into date; returns None if invalid."""
    if not isinstance(s, str):
        return None
    try:
        y, m, d = s.split("-")
        return date(int(y), int(m), int(d))
    except (ValueError, AttributeError):
        return None


def parse_iso_datetime(s):
    """Parse an ISO8601 datetime; returns timezone-aware datetime or None."""
    if not isinstance(s, str):
        return None
    try:
        t = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, AttributeError):
        return None


def iso_to_date(s):
    """Take an ISO timestamp or date string and return the UTC date."""
    if not isinstance(s, str):
        return None
    if "T" in s:
        dt = parse_iso_datetime(s)
        return dt.date() if dt else None
    return parse_iso_date(s)


# ---------- ids ----------

_REQID_ALPHABET = string.ascii_letters + string.digits


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    return "req_" + "".join(secrets.choice(_REQID_ALPHABET) for _ in range(22))


# ---------- decimals / money ----------

DEC4_RE = re.compile(r"^-?\d+\.\d{4}$")
COVERAGE_RE = re.compile(r"^0\.\d{2}$")


def parse_decimal4(s):
    """Parse a decimal-dollar string with exactly 4 fraction digits. Returns Decimal or None."""
    if not isinstance(s, str) or not DEC4_RE.match(s):
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def parse_coverage_pct(s):
    """Parse insurance_coverage_pct: decimal 0.00..0.99, e.g. '0.60'."""
    if not isinstance(s, str) or not COVERAGE_RE.match(s):
        return None
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    if d < Decimal("0.00") or d > Decimal("0.99"):
        return None
    return d


def round_half_up_int(d: Decimal) -> int:
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp_str(d: Decimal) -> str:
    return str(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def line_value_cents(quantity: int, unit_cost: Decimal) -> int:
    return round_half_up_int(Decimal(quantity) * unit_cost * Decimal(100))


# ---------- envelopes ----------

def success_object(payload, status=200):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": now_iso(),
        },
        "response_type": "object",
        "data": payload,
    }
    return jsonify(body), status


def success_list(items, total_count, limit, offset):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": now_iso(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(error_id: str, http_status: int, message: str):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": now_iso(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


# ---------- pagination ----------

def get_pagination():
    """Parse limit/offset from query params; raises ApiError(ERR_INVALID_REQUEST) on bad values."""
    try:
        limit_raw = request.args.get("limit", None)
        offset_raw = request.args.get("offset", None)
        limit = 10
        offset = 0
        if limit_raw is not None:
            limit = int(limit_raw)
        if offset_raw is not None:
            offset = int(offset_raw)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", 400, "Invalid limit/offset")
    if limit < 1 or limit > 100 or offset < 0:
        raise err("ERR_INVALID_REQUEST", 400, "limit must be 1..100 and offset >= 0")
    return limit, offset


def paginate(items):
    limit, offset = get_pagination()
    total = len(items)
    page = items[offset: offset + limit]
    return success_list(page, total, limit, offset)


# ---------- auth / roles ----------

ROLES = {
    "ProgramAdministrator",
    "CaseWorker",
    "AppealsOfficer",
    "Patient",
    "Prescriber",
    "PharmacyDispenser",
}


def require_auth():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", 401, "Missing or invalid X-User-ID / X-User-Role")
    return uid, role


def require_role(*allowed):
    uid, role = require_auth()
    if role not in allowed:
        raise err("ERR_FORBIDDEN", 403, "Role not permitted for this endpoint")
    return uid, role


# ---------- body validation ----------

def get_json_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", 400, "Body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", 400, f"Missing required field: {f}")


def require_string(body, name):
    v = body.get(name)
    if not isinstance(v, str) or not v:
        raise err("ERR_INVALID_REQUEST", 400, f"Field {name} must be a non-empty string")
    return v


def require_int(body, name, minimum=None, maximum=None):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", 400, f"Field {name} must be an integer")
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", 400, f"Field {name} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise err("ERR_INVALID_REQUEST", 400, f"Field {name} must be <= {maximum}")
    return v


def optional_int(body, name, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        return None
    return require_int(body, name, minimum=minimum, maximum=maximum)


def require_enum(body, name, allowed):
    v = body.get(name)
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", 400, f"Field {name} must be one of {sorted(allowed)}")
    return v


def require_bool(body, name):
    v = body.get(name)
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", 400, f"Field {name} must be a boolean")
    return v


def optional_string(body, name):
    v = body.get(name)
    if v is None:
        return None
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", 400, f"Field {name} must be a string")
    return v


def require_iso_date(body, name):
    v = body.get(name)
    d = parse_iso_date(v)
    if d is None:
        raise err("ERR_INVALID_REQUEST", 400, f"Field {name} must be ISO date YYYY-MM-DD")
    return v


# ---------- entity helpers ----------

COMMON_FIELD_ENTITIES = {
    "programs", "budget_periods", "patients", "prescribers", "screenings",
    "documents", "applications", "enrollments", "circumstances", "appeals",
    "copay_cards", "inventory_lots", "shipments", "shipment_lines",
    "reconciliation_runs",
}


def touch(entity):
    """Bump updated_at and version on a mutable entity."""
    entity["updated_at"] = now_iso()
    if "version" in entity:
        entity["version"] += 1


def new_entity(extra=None, common=True):
    e = {
        "id": new_id(),
        "created_at": now_iso(),
    }
    if common:
        e["updated_at"] = e["created_at"]
        e["version"] = 1
    if extra:
        e.update(extra)
    e["_seq"] = db.next_seq()
    return e


def public(entity):
    """Strip internal keys for output."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def list_and_paginate(items):
    """Sort by _seq (creation order) ascending, then paginate and strip internals."""
    ordered = sorted(items, key=lambda e: e.get("_seq", 0))
    limit, offset = get_pagination()
    total = len(ordered)
    page = ordered[offset: offset + limit]
    return success_list([public(e) for e in page], total, limit, offset)
