"""Core infrastructure: in-memory store, logical clock, response envelope,
error catalogue, auth / validation guards.

All state is held in module-level Python dicts.  Nothing is persisted to disk,
so every fresh process starts completely empty (PRD 2.4 / 2.5).
"""
import math
import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from flask import g, request

# ---------------------------------------------------------------------------
# Error catalogue (PRD 5)
# ---------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNKNOWN_ROLE": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_VALIDATION": 422,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_ADVERTISER_NOT_FOUND": 404,
    "ERR_BUDGET_PLAN_NOT_FOUND": 404,
    "ERR_TRADE_FUND_ACCOUNT_NOT_FOUND": 404,
    "ERR_CAMPAIGN_NOT_FOUND": 404,
    "ERR_PLACEMENT_SLOT_NOT_FOUND": 404,
    "ERR_LINE_ITEM_NOT_FOUND": 404,
    "ERR_CATALOG_PRODUCT_NOT_FOUND": 404,
    "ERR_PRODUCT_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_AUCTION_EVENT_NOT_FOUND": 404,
    "ERR_ENGAGEMENT_EVENT_NOT_FOUND": 404,
    "ERR_STUDY_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_DISPUTE_NOT_FOUND": 404,
    "ERR_STALE_ADVERTISER_VERSION": 412,
    "ERR_STALE_CAMPAIGN_VERSION": 412,
    "ERR_STALE_LINE_ITEM_VERSION": 412,
    "ERR_STALE_TRADE_FUND_VERSION": 412,
    "ERR_STALE_INVOICE_VERSION": 412,
    "ERR_ADVERTISER_TERMINATED": 409,
    "ERR_INVALID_ONBOARDING_TRANSITION": 409,
    "ERR_ADVERTISER_NOT_ACTIVE": 409,
    "ERR_PLAN_INVALID_STATE": 409,
    "ERR_PLAN_NOT_FUNDABLE": 409,
    "ERR_INVALID_CAMPAIGN_TRANSITION": 409,
    "ERR_CAMPAIGN_NOT_DELIVERING": 409,
    "ERR_LINE_ITEM_INVALID_STATE": 409,
    "ERR_SLOT_NOT_OPEN": 409,
    "ERR_PRODUCT_DELISTED": 409,
    "ERR_AUCTION_INVALID_STATE": 409,
    "ERR_STUDY_INVALID_STATE": 409,
    "ERR_INVOICE_INVALID_STATE": 409,
    "ERR_DISPUTE_INVALID_STATE": 409,
    "ERR_TRADE_FUND_FROZEN": 409,
    "ERR_PRODUCT_RESTRICTED": 422,
    "ERR_KYC_DOCUMENTS_INSUFFICIENT": 422,
    "ERR_SLA_BREACH_REJECTION_FORBIDDEN": 409,
    "ERR_STUDY_NOT_SIGNIFICANT": 422,
    "ERR_SERVICE_MODEL_CONFLICT": 422,
    "ERR_FLIGHT_WINDOW_OUTSIDE_CAMPAIGN": 422,
    "ERR_FLIGHT_WINDOW_OUTSIDE_PLAN": 422,
    "ERR_PLAN_WINDOW_OVERLAP": 409,
    "ERR_ENGAGEMENT_OUTSIDE_FLIGHT": 422,
    "ERR_STUDY_WASHOUT_VIOLATION": 409,
    "ERR_DISPUTE_WINDOW_CLOSED": 409,
    "ERR_STUDY_WINDOW_NOT_ELAPSED": 409,
    "ERR_SLOT_CAPACITY_EXCEEDED": 409,
    "ERR_SLOT_CATEGORY_EXCLUSIVE": 409,
    "ERR_SLOT_BUFFER_CONFLICT": 409,
    "ERR_DUPLICATE_BRAND_CODE": 409,
    "ERR_DUPLICATE_RESOURCE_CODE": 409,
    "ERR_DUPLICATE_TRADE_FUND_PERIOD": 409,
    "ERR_DUPLICATE_ATTRIBUTED_SALE": 409,
    "ERR_DUPLICATE_INVOICE_PERIOD": 409,
    "ERR_HERO_ASSIGNMENT_REQUIRED": 422,
    "ERR_NO_ELIGIBLE_PRODUCTS": 422,
    "ERR_PARENT_ADVERTISER_INVALID": 422,
    "ERR_OFFSITE_CHANNEL_MISMATCH": 422,
    "ERR_MAX_INFO_REQUESTS_EXCEEDED": 409,
    "ERR_MAX_ROUNDS_EXCEEDED": 409,
    "ERR_CROSS_ADVERTISER_REFERENCE": 422,
    "ERR_FISCAL_PERIOD_MISMATCH": 422,
    "ERR_ENGAGEMENT_AUCTION_MISMATCH": 422,
    "ERR_SUPERSEDED_STUDY_INVALID": 422,
    "ERR_CAP_EXCEEDS_PARENT_LIMIT": 422,
    "ERR_PLAN_BUDGET_INSUFFICIENT": 402,
    "ERR_CREDIT_LIMIT_EXCEEDED": 402,
    "ERR_TRADE_FUND_INSUFFICIENT": 402,
    "ERR_AMOUNT_BELOW_MINIMUM": 422,
    "ERR_CLAIM_EXCEEDS_INVOICE": 422,
    "ERR_CREDIT_EXCEEDS_CLAIM": 422,
    "ERR_SETTLEMENT_AMOUNT_MISMATCH": 422,
    "ERR_NOTHING_TO_INVOICE": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    words = error_id[4:].replace("_", " ").lower() if error_id.startswith("ERR_") else error_id
    return "Request rejected: " + words + "."


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------
ROLES = (
    "NetworkAdmin",
    "AccountManager",
    "AdvertiserUser",
    "CreditAnalyst",
    "MeasurementAnalyst",
    "BillingOps",
    "CatalogOps",
    "AuctionService",
)

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5) -- defaults to 2026-08-01T00:00:00Z on every boot.
# ---------------------------------------------------------------------------
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    """The complete world state.  Wiped on every process start."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = CLOCK_DEFAULT
        self.advertisers = {}
        self.budget_plans = {}
        self.trade_fund_accounts = {}
        self.campaigns = {}
        self.placement_slots = {}
        self.line_items = {}
        self.catalog_products = {}
        self.product_assignments = {}
        self.auction_events = {}
        self.auction_bids = {}
        self.engagement_events = {}
        self.attributed_sales = {}
        self.incrementality_studies = {}
        self.invoices = {}
        self.measurement_disputes = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def now():
    """Current logical time."""
    return db.clock


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_dt(value):
    """Parse an ISO-8601 instant.  Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    m = _TS_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hh, mm = (int(m.group(i)) for i in range(1, 6))
    ss = int(m.group(6) or 0)
    frac = m.group(7)
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    tzs = m.group(8)
    try:
        base = datetime(year, month, day, hh, mm, ss, micro, tzinfo=timezone.utc)
    except ValueError:
        return None
    if tzs and tzs not in ("Z", "z"):
        sign = 1 if tzs[0] == "+" else -1
        tzs = tzs[1:].replace(":", "")
        offset = timedelta(hours=int(tzs[:2]), minutes=int(tzs[2:4]))
        base = base - sign * offset
    # Millisecond resolution comparison (PRD 2.8)
    return base.replace(microsecond=(base.microsecond // 1000) * 1000)


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def whole_days(start, end):
    """Number of whole 24h periods in [start, end)."""
    if start is None or end is None:
        return 0
    delta = end - start
    if delta.total_seconds() <= 0:
        return 0
    return int(delta.total_seconds() // 86400)


def floor_utc_day(dt):
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def overlaps(a_start, a_end, b_start, b_end):
    """Half-open overlap test (PRD 2.8)."""
    return a_start < b_end and b_start < a_end


# ---------------------------------------------------------------------------
# Numeric helpers (PRD 2.6)
# ---------------------------------------------------------------------------
def rhu(value, places=0):
    """round-half-up to `places` decimals.  Returns int when places == 0."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    q = Decimal(1).scaleb(-places)
    out = d.quantize(q, rounding=ROUND_HALF_UP)
    if places == 0:
        return int(out)
    return float(out)


def rhu_dec(value, places=0):
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    q = Decimal(1).scaleb(-places)
    return d.quantize(q, rounding=ROUND_HALF_UP)


def ceil_int(value):
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(d.to_integral_value(rounding=ROUND_CEILING))


def trunc_int(value):
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(d)


def dec(value):
    return value if isinstance(value, Decimal) else Decimal(str(value))


# ---------------------------------------------------------------------------
# Common row fields (PRD 2.4)
# ---------------------------------------------------------------------------
def new_row(versioned=True):
    ts = now()
    row = {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "_seq": db.next_seq(),
    }
    if versioned:
        row["updated_at"] = ts
        row["version"] = 1
    return row


def touch(row):
    """Mutation bookkeeping: bump version, refresh updated_at."""
    if row is None:
        return row
    if "version" in row:
        row["version"] = row["version"] + 1
        row["updated_at"] = now()
    return row


def sort_rows(rows):
    """Collections are always sorted by created_at ascending (PRD 2.3)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# ---------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _wall_ts():
    dt = datetime.now(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": _wall_ts()}


def ok(data, status=200):
    return {"meta": _meta(), "response_type": "object", "data": data}, status


def ok_list(rows, total, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(rows)) < total
    return {"meta": meta, "response_type": "array", "data": rows}, 200


def err_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# ---------------------------------------------------------------------------
# Field specifications / body validation (rejection precedence #5)
# ---------------------------------------------------------------------------
class F(object):
    def __init__(self, name, ftype, required=False, enum=None, minimum=None,
                 maximum=None, nullable=False, default=None, has_default=False):
        self.name = name
        self.ftype = ftype
        self.required = required
        self.enum = enum
        self.minimum = minimum
        self.maximum = maximum
        self.nullable = nullable
        self.default = default
        self.has_default = has_default


def _type_ok(value, ftype):
    if ftype == "string":
        return isinstance(value, str)
    if ftype == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if ftype == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if ftype == "boolean":
        return isinstance(value, bool)
    if ftype == "array":
        return isinstance(value, list)
    if ftype == "datetime":
        return isinstance(value, str) and parse_dt(value) is not None
    if ftype == "enum":
        return isinstance(value, str)
    return True


def validate_body(body, specs):
    """Returns a dict of coerced values.  Raises ERR_VALIDATION on any defect."""
    out = {}
    for spec in specs:
        present = spec.name in body
        value = body.get(spec.name)
        if not present or value is None:
            if present and value is None and spec.nullable:
                out[spec.name] = None
                continue
            if spec.required:
                fail("ERR_VALIDATION", "Field '%s' is required." % spec.name)
            if spec.has_default:
                out[spec.name] = spec.default
            continue
        if not _type_ok(value, spec.ftype):
            fail("ERR_VALIDATION", "Field '%s' has the wrong type." % spec.name)
        if spec.enum is not None and value not in spec.enum:
            fail("ERR_VALIDATION", "Field '%s' is not a permitted value." % spec.name)
        if spec.minimum is not None and value < spec.minimum:
            fail("ERR_VALIDATION",
                 "Field '%s' is below its minimum of %s." % (spec.name, spec.minimum))
        if spec.maximum is not None and value > spec.maximum:
            fail("ERR_VALIDATION",
                 "Field '%s' is above its maximum of %s." % (spec.name, spec.maximum))
        if spec.ftype == "datetime":
            out[spec.name] = parse_dt(value)
        else:
            out[spec.name] = value
    return out


def get_body():
    if request.method in ("GET", "DELETE") and not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        body = {}
    if not isinstance(body, dict):
        fail("ERR_VALIDATION", "Request body must be a JSON object.")
    return body


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3, rejection precedence #6)
# ---------------------------------------------------------------------------
def read_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        if raw is None or not re.match(r"^-?\d+$", raw.strip() or ""):
            fail("ERR_INVALID_PAGINATION", "limit must be an integer 1..100.")
        limit = int(raw)
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_PAGINATION", "limit must be an integer 1..100.")
    if "offset" in args:
        raw = args.get("offset")
        if raw is None or not re.match(r"^-?\d+$", raw.strip() or ""):
            fail("ERR_INVALID_PAGINATION", "offset must be an integer >= 0.")
        offset = int(raw)
        if offset < 0:
            fail("ERR_INVALID_PAGINATION", "offset must be an integer >= 0.")
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


# ---------------------------------------------------------------------------
# Auth (rejection precedence #1-#3)
# ---------------------------------------------------------------------------
def read_identity():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or not str(user_id).strip() or not str(role).strip():
        fail("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required.")
    role = role.strip()
    user_id = user_id.strip()
    if role not in ROLES:
        fail("ERR_UNKNOWN_ROLE", "Unknown role '%s'." % role)
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        fail("ERR_ROLE_NOT_PERMITTED", "Role '%s' may not call this endpoint." % role)


# ---------------------------------------------------------------------------
# Entity existence order (rejection precedence #7-#19)
# ---------------------------------------------------------------------------
EXISTENCE_ORDER = [
    ("advertiser", "advertisers", "ERR_ADVERTISER_NOT_FOUND"),
    ("budget_plan", "budget_plans", "ERR_BUDGET_PLAN_NOT_FOUND"),
    ("trade_fund_account", "trade_fund_accounts", "ERR_TRADE_FUND_ACCOUNT_NOT_FOUND"),
    ("campaign", "campaigns", "ERR_CAMPAIGN_NOT_FOUND"),
    ("placement_slot", "placement_slots", "ERR_PLACEMENT_SLOT_NOT_FOUND"),
    ("line_item", "line_items", "ERR_LINE_ITEM_NOT_FOUND"),
    ("catalog_product", "catalog_products", "ERR_CATALOG_PRODUCT_NOT_FOUND"),
    ("product_assignment", "product_assignments", "ERR_PRODUCT_ASSIGNMENT_NOT_FOUND"),
    ("auction_event", "auction_events", "ERR_AUCTION_EVENT_NOT_FOUND"),
    ("engagement_event", "engagement_events", "ERR_ENGAGEMENT_EVENT_NOT_FOUND"),
    ("study", "incrementality_studies", "ERR_STUDY_NOT_FOUND"),
    ("invoice", "invoices", "ERR_INVOICE_NOT_FOUND"),
    ("dispute", "measurement_disputes", "ERR_DISPUTE_NOT_FOUND"),
]

_COLLECTION_BY_KIND = {k: c for k, c, _ in EXISTENCE_ORDER}
# two ledger collections that carry no existence check of their own
_COLLECTION_BY_KIND["auction_bid"] = "auction_bids"
_COLLECTION_BY_KIND["attributed_sale"] = "attributed_sales"


def lookup(kind, row_id):
    if row_id is None:
        return None
    return getattr(db, _COLLECTION_BY_KIND[kind]).get(row_id)


def rows(kind):
    return list(getattr(db, _COLLECTION_BY_KIND[kind]).values())


def insert(kind, row):
    getattr(db, _COLLECTION_BY_KIND[kind])[row["id"]] = row
    return row


# extra collections that are not part of the existence order
def bid_rows():
    return list(db.auction_bids.values())
