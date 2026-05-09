"""Core: in-memory db, response envelope, errors, auth, helpers."""
import os
import re
import secrets
import string
import threading
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import g, request, jsonify


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
AUTO_APPROVAL_THRESHOLD_CENTS = 200000
AUTO_FRAUD_GATE = Decimal("0.30")
FRAUD_HOLD_GATE = Decimal("0.80")
DECAY_PER_FLAG = Decimal("0.20")
BLACKLIST_THRESHOLD = Decimal("0.40")
COLLUSION_PATTERN_THRESHOLD = 3
LOOKBACK_DAYS = 90
PATTERN_THRESHOLD_CAP = Decimal("0.20")

W_PATTERN = Decimal("0.30")
W_COLLUSION = Decimal("0.30")
W_FORGERY = Decimal("0.30")
W_RAPID = Decimal("0.10")

ROLE_CUSTOMER = "Customer"
ROLE_ADJUSTER = "Adjuster"
ROLE_REVIEWER = "Reviewer"
ROLE_PAYOUT_OFFICER = "PayoutOfficer"
ROLE_PLATFORM_ADMIN = "PlatformAdmin"
VALID_ROLES = {
    ROLE_CUSTOMER,
    ROLE_ADJUSTER,
    ROLE_REVIEWER,
    ROLE_PAYOUT_OFFICER,
    ROLE_PLATFORM_ADMIN,
}

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "test-admin-token")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
ERROR_CATALOG = {
    "ERR_AUTH_REQUIRED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_VALIDATION_FAILED": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_DUPLICATE_CLAIM_INTAKE": 409,
    "ERR_POLICY_INACTIVE": 422,
    "ERR_LOSS_OUTSIDE_POLICY_PERIOD": 422,
    "ERR_REPORTING_WINDOW_EXCEEDED": 422,
    "ERR_ADJUSTER_SPECIALTY_MISMATCH": 422,
    "ERR_REPAIR_SHOP_BLACKLISTED": 422,
    "ERR_PHOTOS_REQUIRED": 422,
    "ERR_ESTIMATE_REQUIRED": 422,
    "ERR_DOCUMENT_AUTHENTICITY_FAILED": 422,
    "ERR_FRAUD_HOLD": 422,
    "ERR_SEGREGATION_OF_DUTIES": 422,
    "ERR_COVERAGE_LIMIT_EXCEEDED": 422,
    "ERR_NEGATIVE_NET_PAYOUT": 422,
    "ERR_APPEAL_ALREADY_EXISTS": 409,
    "ERR_PAYOUT_ALREADY_EXISTS": 409,
    "ERR_INVESTIGATION_ALREADY_OPEN": 409,
}


class ApiError(Exception):
    def __init__(self, error_id: str, message: str = "", http_status: int = None):
        self.error_id = error_id
        self.http_status = http_status if http_status is not None else ERROR_CATALOG.get(error_id, 400)
        self.message = message or error_id


def err(error_id: str, message: str = "") -> ApiError:
    return ApiError(error_id, message)


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------
class DB:
    def __init__(self):
        self.reset()

    def reset(self):
        self.policies = {}
        self.adjusters = {}
        self.repair_shops = {}
        self.claims = {}
        self.investigations = {}
        self.estimate_line_items = {}
        self.review_decisions = {}
        self.appeals = {}
        self.payouts = {}
        self.fraud_flags = {}
        self.audit_log = {}
        # daily counter for claim_number minting; key: YYYYMMDD -> seq used
        self.claim_daily_seq = {}
        # simulated clock; if None, fall back to wall clock
        self.simulated_clock = None
        # event log (e.g., POLICY_CLAIM_CLOSED)
        self.event_log = []


db = DB()
LOCK = threading.RLock()


# ---------------------------------------------------------------------------
# IDs / time / money helpers
# ---------------------------------------------------------------------------
def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def server_now() -> datetime:
    """Either the simulated clock or the real wall clock (UTC)."""
    if db.simulated_clock is not None:
        return db.simulated_clock
    return datetime.now(timezone.utc)


def iso_z(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with 3 fractional digits, Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso() -> str:
    return iso_z(server_now())


_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:?\d{2})$"
)


def parse_iso(s) -> datetime:
    """Parse an ISO 8601 datetime string, return tz-aware UTC datetime. Raises ApiError(ERR_VALIDATION_FAILED) on bad input."""
    if not isinstance(s, str):
        raise err("ERR_VALIDATION_FAILED", "expected ISO 8601 string")
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        raise err("ERR_VALIDATION_FAILED", f"bad ISO 8601: {s}")


def round_half_up(value, places: int = 0) -> Decimal:
    """Round-half-up to the given decimal places, return Decimal."""
    q = Decimal(10) ** -places
    return Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Common-fields stamping
# ---------------------------------------------------------------------------
def stamp_create() -> dict:
    iso = now_iso()
    return {"id": new_id(), "created_at": iso, "updated_at": iso, "version": 1}


def stamp_create_immutable() -> dict:
    return {"id": new_id(), "created_at": now_iso()}


def bump(entity: dict):
    entity["updated_at"] = now_iso()
    entity["version"] = int(entity.get("version", 1)) + 1


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _meta(pagination=None):
    m = {
        "api_request_id": getattr(g, "api_request_id", None) or new_request_id(),
        "api_request_timestamp": now_iso(),
    }
    if pagination:
        m.update(pagination)
    return m


def ok(data, http: int = 200, pagination=None):
    rt = "array" if isinstance(data, list) else "object"
    body = {
        "meta": _meta(pagination),
        "response_type": rt,
        "data": data if data is not None else {},
    }
    resp = jsonify(body)
    resp.status_code = http
    return resp


def error_response(api_err: ApiError):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": api_err.error_id, "message": api_err.message},
    }
    resp = jsonify(body)
    resp.status_code = api_err.http_status
    return resp


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def parse_auth():
    """Validate X-User-ID and X-User-Role; raise ERR_AUTH_REQUIRED / ERR_FORBIDDEN."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err("ERR_AUTH_REQUIRED", "missing X-User-ID/X-User-Role")
    if not isinstance(user_id, str) or not isinstance(role, str):
        raise err("ERR_AUTH_REQUIRED", "malformed auth headers")
    if not user_id.strip() or not role.strip():
        raise err("ERR_AUTH_REQUIRED", "blank auth headers")
    if role not in VALID_ROLES:
        raise err("ERR_FORBIDDEN", f"unknown role: {role}")
    return user_id, role


def require_roles(*allowed):
    user_id, role = parse_auth()
    if role not in allowed:
        raise err("ERR_FORBIDDEN", f"role {role} not permitted")
    return user_id, role


def require_admin_token():
    """For /_events/* and /_clock/advance: still require X-User-ID & X-User-Role=PlatformAdmin AND X-Admin-Token."""
    user_id, role = parse_auth()
    if role != ROLE_PLATFORM_ADMIN:
        raise err("ERR_FORBIDDEN", "admin role required")
    token = request.headers.get("X-Admin-Token")
    if not token or token != ADMIN_TOKEN:
        raise err("ERR_FORBIDDEN", "invalid admin token")
    return user_id, role


# ---------------------------------------------------------------------------
# Body helpers / validation
# ---------------------------------------------------------------------------
def get_json_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise err("ERR_VALIDATION_FAILED", "request body must be a JSON object")
    return body


def require_field(body: dict, name: str):
    if name not in body or body[name] is None:
        raise err("ERR_VALIDATION_FAILED", f"missing field: {name}")
    return body[name]


def require_int(body: dict, name: str, *, ge=None, gt=None, le=None) -> int:
    v = require_field(body, name)
    try:
        if isinstance(v, bool):
            raise ValueError()
        i = int(v)
        # Refuse implicit floats with fractional component to keep cents integral.
        if isinstance(v, float) and not float(v).is_integer():
            raise ValueError()
    except (TypeError, ValueError):
        raise err("ERR_VALIDATION_FAILED", f"field {name} must be integer")
    if ge is not None and i < ge:
        raise err("ERR_VALIDATION_FAILED", f"field {name} must be >= {ge}")
    if gt is not None and i <= gt:
        raise err("ERR_VALIDATION_FAILED", f"field {name} must be > {gt}")
    if le is not None and i > le:
        raise err("ERR_VALIDATION_FAILED", f"field {name} must be <= {le}")
    return i


def require_str(body: dict, name: str, *, allow_empty=False) -> str:
    v = require_field(body, name)
    if not isinstance(v, str):
        raise err("ERR_VALIDATION_FAILED", f"field {name} must be string")
    if not allow_empty and not v.strip():
        raise err("ERR_VALIDATION_FAILED", f"field {name} is empty")
    return v


def require_enum(body: dict, name: str, choices) -> str:
    v = require_str(body, name)
    if v not in choices:
        raise err("ERR_VALIDATION_FAILED", f"field {name} must be one of {sorted(choices)}")
    return v


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise err("ERR_INVALID_PAGINATION", "limit/offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        raise err("ERR_INVALID_PAGINATION", "limit out of [1,100] or negative offset")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    sliced = items[offset : offset + limit]
    return sliced, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }


# ---------------------------------------------------------------------------
# Common existence resolver
# ---------------------------------------------------------------------------
def get_or_404(d: dict, key, label: str = ""):
    if key is None or key not in d:
        raise err("ERR_NOT_FOUND", f"{label} not found" if label else "resource not found")
    return d[key]
