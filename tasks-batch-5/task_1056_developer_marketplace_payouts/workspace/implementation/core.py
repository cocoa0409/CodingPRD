"""Core infrastructure: store, logical clock, envelope, errors, auth, pagination."""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import g, jsonify, request

# --------------------------------------------------------------------------
# Constants (SCAFFOLD §constants / PRD §3)
# --------------------------------------------------------------------------
PRICING_COOLDOWN_HOURS = 24
REFUND_WINDOW_DAYS = 30
CHARGEBACK_REPRESENT_WINDOW_DAYS = 7
POLICY_STRIKE_SUSPEND_THRESHOLD = 3
DEFAULT_SHARE_BPS = 7000
CHARGEBACK_RESERVE_BPS = 500
BACKUP_WITHHOLDING_BPS = 2400
MIN_PAYOUT_CENTS = 5000
FORM_1099_THRESHOLD_CENTS = 60000
RISK_WINDOW_DAYS = 30
REFUND_WEIGHT = 40
CHARGEBACK_WEIGHT = 40
STRIKE_WEIGHT = 20
DEFAULT_CLOCK_UTC = "2026-07-01T00:00:00Z"

ROLES = {
    "Developer",
    "ReviewAgent",
    "PolicyOfficer",
    "FinanceOps",
    "PlatformAdmin",
    "StorefrontService",
}


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_DEVELOPER_NOT_FOUND": 404,
    "ERR_APP_NOT_FOUND": 404,
    "ERR_REVIEW_SUBMISSION_NOT_FOUND": 404,
    "ERR_PRICING_PLAN_NOT_FOUND": 404,
    "ERR_TAX_JURISDICTION_NOT_FOUND": 404,
    "ERR_REVENUE_SHARE_TIER_NOT_FOUND": 404,
    "ERR_PURCHASE_NOT_FOUND": 404,
    "ERR_REFUND_NOT_FOUND": 404,
    "ERR_CHARGEBACK_NOT_FOUND": 404,
    "ERR_POLICY_CASE_NOT_FOUND": 404,
    "ERR_PAYOUT_BATCH_NOT_FOUND": 404,
    "ERR_PAYOUT_LINE_NOT_FOUND": 404,
    "ERR_LEDGER_ENTRY_NOT_FOUND": 404,
    "ERR_TAX_FORM_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_STALE_APP_VERSION": 412,
    "ERR_STALE_DEVELOPER_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_DEVELOPER_NOT_ACTIVE": 409,
    "ERR_PURCHASE_NOT_REFUNDABLE": 409,
    "ERR_APP_NOT_PURCHASABLE": 409,
    "ERR_DEVELOPER_PAYOUT_HELD": 409,
    "ERR_PRICING_WINDOW_CONFLICT": 409,
    "ERR_BATCH_PERIOD_OVERLAP": 409,
    "ERR_TAX_FORM_EXISTS": 409,
    "ERR_JURISDICTION_EXISTS": 409,
    "ERR_JURISDICTION_NOT_CONFIGURED": 422,
    "ERR_PLAN_APP_MISMATCH": 422,
    "ERR_REFUND_WINDOW_EXPIRED": 422,
    "ERR_REPRESENTMENT_WINDOW_EXPIRED": 422,
    "ERR_REFUND_EXCEEDS_REMAINING": 422,
    "ERR_INVALID_PRICING": 422,
    "ERR_TAX_ID_REQUIRED": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# --------------------------------------------------------------------------
# Store
# --------------------------------------------------------------------------
class Store:
    COLLECTIONS = (
        "developers",
        "apps",
        "review_submissions",
        "pricing_plans",
        "tax_jurisdictions",
        "revenue_share_tiers",
        "purchases",
        "refunds",
        "chargebacks",
        "policy_cases",
        "payout_batches",
        "payout_lines",
        "ledger_entries",
        "tax_forms",
    )

    def __init__(self):
        self.reset()

    def reset(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0
        self.clock = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# --------------------------------------------------------------------------
# Time helpers
# --------------------------------------------------------------------------
def parse_iso(value):
    if not isinstance(value, str) or not value.strip():
        return None
    txt = value.strip()
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_wall():
    return datetime.now(timezone.utc)


def clock_now():
    return db.clock


# --------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------
def new_record(versioned=True, **fields):
    ts = iso(now_wall())
    rec = {"id": str(uuid.uuid4()), "created_at": ts}
    if versioned:
        rec["updated_at"] = ts
        rec["version"] = 1
    rec.update(fields)
    rec["_seq"] = db.next_seq()
    return rec


def touch(rec):
    if "version" in rec:
        rec["version"] = rec["version"] + 1
        rec["updated_at"] = iso(now_wall())
    return rec


def public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def ordered(collection):
    return sorted(collection.values(), key=lambda r: r["_seq"])


# --------------------------------------------------------------------------
# Response envelope
# --------------------------------------------------------------------------
def _request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(now_wall()),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def ok_list(items, limit, offset, total):
    meta = _meta(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": offset + len(items) < total,
        }
    )
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------
def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers.")
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "Role %s may not call this endpoint." % role)
    g.user_id = user_id
    g.role = role
    return user_id, role


def is_developer():
    return getattr(g, "role", None) == "Developer"


def require_owner(developer_id):
    if is_developer() and g.user_id != developer_id:
        fail("ERR_NOT_RESOURCE_OWNER", "Caller does not own this resource.")


# --------------------------------------------------------------------------
# Body / field validation
# --------------------------------------------------------------------------
def get_body():
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Body must be valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "Body must be a JSON object.")
    return payload


def req_str(body, field):
    value = body.get(field)
    if not isinstance(value, str) or not value.strip():
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty string." % field)
    return value


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    value = body[field]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % field)
    return value


def req_enum(body, field, members):
    value = req_str(body, field)
    if value not in members:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (field, sorted(members)))
    return value


def req_int(body, field, minimum=None):
    value = body.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (field, minimum))
    return value


def opt_int(body, field, default=None, minimum=None):
    if field not in body or body[field] is None:
        return default
    return req_int(body, field, minimum)


def req_bool(body, field):
    value = body.get(field)
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % field)
    return value


def opt_bool(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return req_bool(body, field)


def req_dt(body, field):
    raw = body.get(field)
    if not isinstance(raw, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 string." % field)
    parsed = parse_iso(raw)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a valid ISO 8601 instant." % field)
    return parsed


def req_str_array(body, field):
    value = body.get(field)
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an array." % field)
    for item in value:
        if not isinstance(item, str):
            fail("ERR_INVALID_REQUEST", "Field '%s' must contain strings." % field)
    return list(value)


# --------------------------------------------------------------------------
# Pagination + filters
# --------------------------------------------------------------------------
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_PAGINATION", "limit must be an integer.")
        if str(raw).strip() != str(limit):
            fail("ERR_INVALID_PAGINATION", "limit must be an integer.")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_PAGINATION", "limit must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_PAGINATION", "offset must be an integer.")
        if str(raw).strip() != str(offset):
            fail("ERR_INVALID_PAGINATION", "offset must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_PAGINATION", "offset must be >= 0.")
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    page = rows[offset: offset + limit]
    return [public(r) for r in page], total


def filter_eq(rows, field, param=None):
    param = param or field
    value = request.args.get(param)
    if value is None:
        return rows
    if value in ("true", "false") and rows and isinstance(rows[0].get(field), bool):
        want = value == "true"
        return [r for r in rows if r.get(field) is want]
    out = []
    for r in rows:
        current = r.get(field)
        if current is None:
            continue
        if isinstance(current, bool):
            if str(current).lower() == value.lower():
                out.append(r)
        elif isinstance(current, int):
            try:
                if current == int(value):
                    out.append(r)
            except ValueError:
                continue
        elif str(current) == value:
            out.append(r)
    return out


# --------------------------------------------------------------------------
# Math
# --------------------------------------------------------------------------
def rhu(value):
    """Round half-up (away from zero) to a whole unit; returns int."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def tax_from_inclusive(amount_cents, rate_bps):
    if rate_bps == 0:
        return 0
    return rhu(Decimal(amount_cents) * Decimal(rate_bps) / Decimal(10000 + rate_bps))


def bps_of(amount_cents, bps):
    return rhu(Decimal(amount_cents) * Decimal(bps) / Decimal(10000))


def days(n):
    return timedelta(days=n)
