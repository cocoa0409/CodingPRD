"""Request pipeline helpers: auth, RBAC, idempotency, body/shape, pagination.

Implements the fixed precedence ladder of PRD §2.10 / SCAFFOLD §1.4:
  1. ERR_UNAUTHENTICATED (401)  — X-User-Role missing or not a declared role
  2. ERR_FORBIDDEN (403)        — role not allowed; entity-backed identity
                                  mismatch; payload-scoped role rules
  3. ERR_MISSING_IDEMPOTENCY_KEY (400) — every POST needs Idempotency-Key
  4. ERR_IDEMPOTENCY_CONFLICT (409)    — key replay with different request
  ...then existence / shape / state / business checks in the routes.
"""

import json

from flask import request

from db import IDEMPOTENCY, STORE
from errors import (
    ApiError,
    ERR_UNAUTHENTICATED,
    ERR_FORBIDDEN,
    ERR_MISSING_IDEMPOTENCY_KEY,
    ERR_IDEMPOTENCY_CONFLICT,
    ERR_INVALID_REQUEST,
)
from logical_clock import _parse_iso
from response import PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MIN, PAGE_LIMIT_MAX, PAGE_OFFSET_DEFAULT

ROLES = {"ProgramAdmin", "MarketManager", "BoothOperator", "Vendor", "Auditor", "Shopper"}
ENTITY_BACKED = {"Vendor": "vendors", "Shopper": "shoppers"}


# ---------------------------------------------------------------------------
# Auth (priorities 1-2)
# ---------------------------------------------------------------------------

def authenticate(allowed_roles):
    """Run auth + role RBAC. Returns (role, user_id).

    allowed_roles: iterable of role names from the endpoint table.
    """
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401,
                       "X-User-Role header missing or not a declared role")
    user_id = request.headers.get("X-User-ID")
    if role not in allowed_roles:
        raise ApiError(ERR_FORBIDDEN, 403,
                       f"Role {role} is not permitted on this endpoint")
    table = ENTITY_BACKED.get(role)
    if table is not None:
        if user_id is None or user_id not in STORE[table]:
            raise ApiError(ERR_FORBIDDEN, 403,
                           f"X-User-ID does not identify an existing {role} row")
    return role, user_id


# ---------------------------------------------------------------------------
# Body handling
# ---------------------------------------------------------------------------

class Body:
    def __init__(self):
        self.raw = request.get_data(cache=True) or b""
        self.parsed = None
        self.valid_json = False
        text = self.raw.decode("utf-8", errors="replace").strip()
        if text:
            try:
                val = json.loads(text)
                if isinstance(val, dict):
                    self.parsed = val
                    self.valid_json = True
            except (ValueError, TypeError):
                self.parsed = None
                self.valid_json = False
        else:
            self.parsed = {}
            self.valid_json = True

    def get(self, key, default=None):
        if not self.valid_json:
            return default
        return self.parsed.get(key, default)

    def has(self, key):
        return self.valid_json and key in self.parsed


def get_body():
    return Body()


def fingerprint(method, path, raw_body):
    text = raw_body.decode("utf-8", errors="replace") if isinstance(raw_body, (bytes, bytearray)) else str(raw_body)
    try:
        canon = json.dumps(json.loads(text), sort_keys=True, separators=(",", ":")) if text.strip() else ""
    except (ValueError, TypeError):
        canon = "RAW:" + text
    return f"{method} {path}\n{canon}"


# ---------------------------------------------------------------------------
# Idempotency (priorities 3-4, POST only) — PRD §2.7
# ---------------------------------------------------------------------------

class IdempotencyReplay(Exception):
    def __init__(self, status, body):
        self.status = status
        self.body = body


def idempotency_guard(body):
    """Raise on missing key / conflicting replay; raise IdempotencyReplay on
    an exact replay of a previously successful request."""
    key = request.headers.get("Idempotency-Key")
    if not key:
        raise ApiError(ERR_MISSING_IDEMPOTENCY_KEY, 400,
                       "POST requests require an Idempotency-Key header")
    fp = fingerprint(request.method, request.path, body.raw)
    rec = IDEMPOTENCY.get(key)
    if rec is not None:
        if rec["fingerprint"] != fp:
            raise ApiError(ERR_IDEMPOTENCY_CONFLICT, 409,
                           "Idempotency-Key was reused with a different request")
        raise IdempotencyReplay(rec["status"], rec["body"])
    return key, fp


def idempotency_commit(key, fp, status, body_json):
    """Store only successful (2xx) responses for replay."""
    if key is None:
        return
    if 200 <= int(status) < 300:
        IDEMPOTENCY[key] = {"fingerprint": fp, "status": int(status), "body": body_json}


# ---------------------------------------------------------------------------
# Shape validation helpers (priority 8 -> ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------

def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def fail_shape(msg):
    raise ApiError(ERR_INVALID_REQUEST, 400, msg)


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str):
        fail_shape(f"Field '{field}' is required and must be a string")
    return v


def opt_str(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        fail_shape(f"Field '{field}' must be a string")
    return v


def req_int(body, field):
    v = body.get(field)
    if not _is_int(v):
        fail_shape(f"Field '{field}' is required and must be an integer")
    return v


def opt_bool(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, bool):
        fail_shape(f"Field '{field}' must be a boolean")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        fail_shape(f"Field '{field}' must be one of {sorted(allowed)}")
    return v


def req_datetime(body, field):
    v = body.get(field)
    if not isinstance(v, str):
        fail_shape(f"Field '{field}' is required and must be an ISO 8601 timestamp")
    try:
        return _parse_iso(v)
    except ValueError:
        fail_shape(f"Field '{field}' must be a valid ISO 8601 timestamp")


def req_date(body, field):
    from datetime import datetime as _dt
    v = body.get(field)
    if not isinstance(v, str):
        fail_shape(f"Field '{field}' is required and must be an ISO date (YYYY-MM-DD)")
    try:
        _dt.strptime(v, "%Y-%m-%d")
    except ValueError:
        fail_shape(f"Field '{field}' must be a valid ISO date (YYYY-MM-DD)")
    return v


def req_str_list(body, field):
    v = body.get(field)
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        fail_shape(f"Field '{field}' is required and must be an array of strings")
    return v


def ensure_valid_json(body):
    if not body.valid_json:
        fail_shape("Request body must be a JSON object")


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3) — GET list endpoints; lenient (clamped) parsing
# ---------------------------------------------------------------------------

def parse_pagination():
    def _int_arg(name, default):
        raw = request.args.get(name)
        if raw is None:
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    limit = _int_arg("limit", PAGE_LIMIT_DEFAULT)
    offset = _int_arg("offset", PAGE_OFFSET_DEFAULT)
    limit = max(PAGE_LIMIT_MIN, min(PAGE_LIMIT_MAX, limit))
    offset = max(0, offset)
    return limit, offset


def paginate(items, sort_key=None):
    """Sort (created_at ASC, insertion seq tie-break by default), then slice."""
    if sort_key is None:
        sort_key = lambda e: (e.get("created_at", ""), e.get("_seq", 0))
    ordered = sorted(items, key=sort_key)
    limit, offset = parse_pagination()
    total = len(ordered)
    return ordered[offset:offset + limit], limit, offset, total
