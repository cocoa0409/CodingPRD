"""Core primitives: in-memory store, logical clock, response envelope, errors,
auth, pagination, serialization, and the domain calculations.

All state lives in module-level dicts and is wiped on every process start
(the harness restarts the server before each test). Nothing is seeded here.
"""
import math
import random
import string
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from flask import request, jsonify

# =====================================================================
# Constants
# =====================================================================
VALID_ROLES = {"Anonymous", "Member", "Attorney", "Notary", "PlatformAdmin"}
PLAN_TIERS = {"BASIC", "PLUS", "PREMIER"}
DOC_TYPES = {"WILL", "TRUST", "POA", "HEALTHCARE_DIRECTIVE"}
BUNDLE_TYPES = {"INDIVIDUAL", "COUPLE"}
RELATIONSHIPS = {"SPOUSE", "CHILD", "RELATIVE", "CHARITY", "OTHER"}
ASSET_TYPES = {"REAL_ESTATE", "BANK", "INVESTMENT", "VEHICLE", "PERSONAL", "BUSINESS"}
FUNDING_STATUSES = {"UNFUNDED", "PENDING", "FUNDED"}
SCOPES = {"VIEW", "FULL", "EXECUTOR_ACCESS"}
PAYMENT_OUTCOMES = {"SUCCEEDED", "FAILED"}
REVIEW_ACTIONS = {"START_REVIEW", "REQUEST_CHANGES", "APPROVE"}
EXECUTOR_DECISIONS = {"ACCEPT", "DECLINE"}

ATTORNEY_ADDON_CENTS = 15000
TERM_DAYS = 365
RENEWAL_WINDOW_DAYS = 30
GRACE_DAYS = 30
BUNDLE_MULTIPLIER = {"INDIVIDUAL": Decimal("1.0"), "COUPLE": Decimal("1.6")}

WITNESS_BASE = {"WILL": 2, "TRUST": 0, "POA": 1, "HEALTHCARE_DIRECTIVE": 1}
WITNESS_SURCHARGE_STATES = {"LA", "VT"}
REQUIRED_FIELDS = {"WILL": 5, "TRUST": 7, "POA": 4, "HEALTHCARE_DIRECTIVE": 4}

DEFAULT_CLOCK = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)

# Error catalog: error_id -> http status
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_VALIDATION": 400,
    "ERR_MEMBER_NOT_FOUND": 404,
    "ERR_SUBSCRIPTION_NOT_FOUND": 404,
    "ERR_QUESTIONNAIRE_NOT_FOUND": 404,
    "ERR_DOCUMENT_NOT_FOUND": 404,
    "ERR_BENEFICIARY_NOT_FOUND": 404,
    "ERR_ASSET_NOT_FOUND": 404,
    "ERR_EXECUTOR_NOT_FOUND": 404,
    "ERR_REVIEW_NOT_FOUND": 404,
    "ERR_SHARE_GRANT_NOT_FOUND": 404,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_SUBSCRIPTION_NOT_ACTIVE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_SUBSCRIPTION_PERIOD_OVERLAP": 409,
    "ERR_SHARE_WINDOW_OVERLAP": 409,
    "ERR_DOCUMENT_NOT_EXECUTED": 409,
    "ERR_RENEWAL_WINDOW_NOT_OPEN": 422,
    "ERR_RENEWAL_TOO_LATE": 422,
    "ERR_QUESTIONNAIRE_INCOMPLETE": 422,
    "ERR_DOCUMENT_TYPE_NOT_IN_PLAN": 422,
    "ERR_DOCUMENT_QUOTA_EXCEEDED": 422,
    "ERR_ALLOCATION_EXCEEDED": 422,
    "ERR_NO_BENEFICIARIES": 422,
    "ERR_WITNESS_REQUIREMENT_NOT_MET": 422,
    "ERR_ATTORNEY_SUPPORT_NOT_ENABLED": 422,
    "ERR_ASSET_ALREADY_FUNDED": 422,
    "ERR_PAYMENT_ALREADY_SETTLED": 409,
}

NON_TERMINAL_SUB = {"PENDING_PAYMENT", "ACTIVE", "SUSPENDED"}
TERMINAL_SUB = {"CANCELLED", "EXPIRED"}
NON_TERMINAL_DOC = {"GENERATED", "IN_REVIEW", "PENDING_EXECUTION", "EXECUTED"}
TERMINAL_DOC = {"SUPERSEDED", "REVOKED"}
NON_TERMINAL_REVIEW = {"REQUESTED", "IN_REVIEW", "CHANGES_REQUESTED"}


# =====================================================================
# Errors
# =====================================================================
class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP[error_id]
        self.message = message or error_id


# =====================================================================
# Logical clock
# =====================================================================
class Clock:
    def __init__(self):
        self.current = DEFAULT_CLOCK

    def now(self):
        return self.current

    def set(self, dt):
        self.current = dt


clock = Clock()


# =====================================================================
# In-memory store
# =====================================================================
class DB:
    def __init__(self):
        self.plan_catalog = {}
        self.members = {}
        self.subscriptions = {}
        self.questionnaires = {}
        self.documents = {}
        self.beneficiaries = {}
        self.assets = {}
        self.executors = {}
        self.share_grants = {}
        self.attorney_reviews = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()


# =====================================================================
# Time helpers
# =====================================================================
def fmt_ts(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", "expected an ISO-8601 timestamp string")
    t = s.strip()
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise ApiError("ERR_VALIDATION", "malformed ISO-8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# =====================================================================
# Identity / common fields
# =====================================================================
def new_id():
    return str(uuid.uuid4())


def req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def add_common(entity, versioned=True):
    now = clock.now()
    entity["id"] = new_id()
    entity["created_at"] = now
    entity["_seq"] = db.next_seq()
    if versioned:
        entity["updated_at"] = now
        entity["version"] = 1
    return entity


def touch(entity):
    entity["updated_at"] = clock.now()
    entity["version"] = entity.get("version", 1) + 1


# =====================================================================
# Serialization + response envelope
# =====================================================================
def serialize(entity):
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = fmt_ts(v)
        elif isinstance(v, Decimal):
            out[k] = float(v)
        else:
            out[k] = v
    return out


def _base_meta():
    return {"api_request_id": req_id(), "api_request_timestamp": fmt_ts(clock.now())}


def respond(data, status=200, response_type="object"):
    body = {"meta": _base_meta(), "response_type": response_type, "data": data}
    return jsonify(body), status


def respond_entity(entity, status=200):
    return respond(serialize(entity), status=status, response_type="object")


def respond_list(items, meta_extra):
    meta = _base_meta()
    meta.update(meta_extra)
    body = {"meta": meta, "response_type": "array", "data": [serialize(e) for e in items]}
    return jsonify(body), 200


def error_response(err: ApiError):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# =====================================================================
# Auth
# =====================================================================
def authenticate(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in VALID_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "missing or unknown authentication headers")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "role not permitted for this operation")
    return uid, role


def require_ownership(role, uid, owner_member_id):
    """Member-role callers may only act on resources they own."""
    if role == "Member" and owner_member_id != uid:
        raise ApiError("ERR_UNAUTHORIZED", "member does not own this resource")


# =====================================================================
# Body field helpers
# =====================================================================
def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", "request body must be a JSON object")
    return body


def require(body, name):
    if name not in body or body[name] is None:
        raise ApiError("ERR_VALIDATION", f"missing required field: {name}")
    return body[name]


def as_str(v, name):
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", f"{name} must be a non-empty string")
    return v


def as_enum(v, name, allowed):
    if not isinstance(v, str) or v not in allowed:
        raise ApiError("ERR_VALIDATION", f"{name} must be one of {sorted(allowed)}")
    return v


def as_int(v, name, minimum=None):
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", f"{name} must be an integer")
    if minimum is not None and v < minimum:
        raise ApiError("ERR_VALIDATION", f"{name} must be >= {minimum}")
    return v


def as_bool(v, name):
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", f"{name} must be a boolean")
    return v


def as_state_code(v, name):
    if not isinstance(v, str) or len(v) != 2 or not v.isalpha() or not v.isupper():
        raise ApiError("ERR_VALIDATION", f"{name} must be two uppercase letters")
    return v


def as_pct(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", f"{name} must be a number")
    d = Decimal(str(v))
    if d < 0 or d > 100:
        raise ApiError("ERR_VALIDATION", f"{name} must be between 0 and 100")
    if -d.as_tuple().exponent > 2:
        raise ApiError("ERR_VALIDATION", f"{name} may have at most two decimals")
    return d


# =====================================================================
# Pagination
# =====================================================================
def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "limit must be an integer")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100
    if "offset" in args and args.get("offset") != "":
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items):
    """items: iterable of entities. Sorts by created_at asc (stable by seq)."""
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    limit, offset = parse_pagination()
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta


# =====================================================================
# Money / rounding
# =====================================================================
def round_half_up_cents(dec_value):
    return int(Decimal(dec_value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# =====================================================================
# Calculations
# =====================================================================
def signup_price(plan, attorney_support, bundle_type):
    base = plan["base_price_cents"]
    addon = ATTORNEY_ADDON_CENTS if attorney_support else 0
    mult = BUNDLE_MULTIPLIER[bundle_type]
    return round_half_up_cents(Decimal(base + addon) * mult)


def loyalty_pct(new_renewal_count):
    if new_renewal_count in (1, 2):
        return Decimal("0.10")
    if new_renewal_count >= 3:
        return Decimal("0.20")
    return Decimal("0")


def renewal_final_charge(pending_cents, new_renewal_count):
    pct = loyalty_pct(new_renewal_count)
    return round_half_up_cents(Decimal(pending_cents) * (Decimal(1) - pct))


def witness_requirement(document_type, state_code):
    base = WITNESS_BASE[document_type]
    surcharge = 1 if state_code in WITNESS_SURCHARGE_STATES else 0
    witness_count_required = base + surcharge
    requires_notary = (document_type in {"TRUST", "POA"}) or (state_code == "LA")
    return witness_count_required, requires_notary


def cancel_refund(sub):
    if sub["current_period_end"] is None:
        return 0
    now = clock.now()
    delta = sub["current_period_end"] - now
    remaining_days = max(0, math.ceil(delta.total_seconds() / 86400.0))
    refund = round_half_up_cents(
        Decimal(sub["price_cents"]) * Decimal(remaining_days) / Decimal(TERM_DAYS)
    )
    refund = min(refund, sub["paid_to_date_cents"])
    return refund


def gross_estate_value(subscription_id):
    return sum(
        a["estimated_value_cents"]
        for a in db.assets.values()
        if a["subscription_id"] == subscription_id
    )


def recompute_estate_distribution(subscription_id):
    pool = gross_estate_value(subscription_id)
    primaries = [
        b
        for b in db.beneficiaries.values()
        if b["subscription_id"] == subscription_id and not b["is_contingent"]
    ]
    primaries.sort(key=lambda b: (b["created_at"], b["_seq"]))
    # contingent -> 0
    for b in db.beneficiaries.values():
        if b["subscription_id"] == subscription_id and b["is_contingent"]:
            b["allocated_cents"] = 0
    if not primaries:
        return
    floor_shares = []
    for b in primaries:
        share = (Decimal(pool) * b["allocation_pct"] / Decimal(100)).quantize(
            Decimal("1"), rounding=ROUND_FLOOR
        )
        floor_shares.append(int(share))
    residual = pool - sum(floor_shares)
    n = len(primaries)
    for i in range(residual):
        floor_shares[i % n] += 1
    for b, share in zip(primaries, floor_shares):
        b["allocated_cents"] = share


def period_overlap(member_id, exclude_id, start, end):
    """Half-open [start, end) overlap against member's other non-terminal subs."""
    for s in db.subscriptions.values():
        if s["id"] == exclude_id:
            continue
        if s["member_id"] != member_id:
            continue
        if s["status"] in TERMINAL_SUB:
            continue
        os, oe = s["current_period_start"], s["current_period_end"]
        if os is None or oe is None:
            continue
        if start < oe and os < end:
            return True
    return False
