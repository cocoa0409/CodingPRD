"""Core primitives: in-memory store, logical clock, envelope, auth, validation."""
import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

# ---------------------------------------------------------------- constants
ROLES = ("EventOrganizer", "AuctionManager", "FinanceOfficer", "Bidder", "Sponsor")
ALL_ROLES = list(ROLES)

DEFAULT_CLOCK_UTC = "2026-07-01T00:00:00.000Z"
TABLE_TURNOVER_BUFFER_MINUTES = 15
MAX_AD_REVISIONS = 2
PLEDGE_LAPSE_GRACE_DAYS = 30
EARLY_BIRD_DAYS_BEFORE_EVENT = 30
EARLY_BIRD_TABLE_DISCOUNT_RATE = Decimal("0.15")
EARLY_BIRD_SEAT_DISCOUNT_RATE = Decimal("0.10")
TICKET_BENEFIT_PER_SEAT_CENTS = 7500
MATCH_RATIO = Decimal("1.0")
FEE_TIER_1_CEILING_CENTS = 50000
FEE_TIER_2_CEILING_CENTS = 500000
FEE_RATE_TIER_1 = Decimal("0.029")
FEE_RATE_TIER_2 = Decimal("0.024")
FEE_RATE_TIER_3 = Decimal("0.019")
PROCESSING_FEE_FLAT_CENTS = 30
FMV_DE_MINIMIS_CENTS = 1500
MATERIAL_VARIANCE_THRESHOLD_CENTS = 5000

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_EVENT_NOT_FOUND": 404,
    "ERR_TABLE_NOT_FOUND": 404,
    "ERR_HOLD_NOT_FOUND": 404,
    "ERR_TICKET_ORDER_NOT_FOUND": 404,
    "ERR_BIDDER_NOT_FOUND": 404,
    "ERR_SPONSOR_NOT_FOUND": 404,
    "ERR_AD_NOT_FOUND": 404,
    "ERR_ITEM_NOT_FOUND": 404,
    "ERR_BID_NOT_FOUND": 404,
    "ERR_PADDLE_RAISE_NOT_FOUND": 404,
    "ERR_PLEDGE_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_PAYMENT_NOT_FOUND": 404,
    "ERR_RECEIPT_NOT_FOUND": 404,
    "ERR_RUN_NOT_FOUND": 404,
    "ERR_EVENT_FROZEN": 409,
    "ERR_EVENT_RESTRICTED": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_ITEM_NOT_OPEN": 409,
    "ERR_INVOICE_NOT_PAYABLE": 409,
    "ERR_RUN_ALREADY_FINALIZED": 409,
    "ERR_PLEDGE_TERMINAL": 409,
    "ERR_RECEIPT_ALREADY_ISSUED": 409,
    "ERR_STALE_EVENT_VERSION": 412,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_SPONSOR_NOT_CONFIRMED": 409,
    "ERR_OPEN_INVOICES_REMAIN": 409,
    "ERR_NO_FINALIZED_RUN": 409,
    "ERR_OPEN_LOTS_REMAIN": 409,
    "ERR_TICKET_ORDERS_EXIST": 409,
    "ERR_LOT_WINDOW_CLOSED": 409,
    "ERR_LOT_WINDOW_CONFLICT": 409,
    "ERR_TABLE_HOLD_CONFLICT": 409,
    "ERR_BID_TOO_LOW": 422,
    "ERR_AD_REVISION_LIMIT": 409,
    "ERR_SEAT_CAPACITY_EXCEEDED": 409,
    "ERR_DUPLICATE_PADDLE_NUMBER": 409,
    "ERR_NO_PAYMENT_METHOD": 402,
    "ERR_PAYMENT_EXCEEDS_BALANCE": 422,
    "ERR_MATERIAL_VARIANCE": 409,
    "ERR_SPONSOR_UNDERFUNDED": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or error_id.replace("ERR_", "").replace("_", " ").lower()


# ---------------------------------------------------------------- store
class Store:
    KINDS = (
        "events", "tables", "holds", "orders", "bidders", "sponsors", "ads",
        "items", "bids", "paddles", "pledges", "invoices", "payments",
        "receipts", "runs",
    )

    def __init__(self):
        self.reset()

    def reset(self):
        for k in self.KINDS:
            setattr(self, k, {})
        self.seq = 0
        self.clock = DEFAULT_CLOCK_UTC

    def next_seq(self):
        self.seq += 1
        return self.seq


db = Store()

NOT_FOUND = {
    "events": "ERR_EVENT_NOT_FOUND",
    "tables": "ERR_TABLE_NOT_FOUND",
    "holds": "ERR_HOLD_NOT_FOUND",
    "orders": "ERR_TICKET_ORDER_NOT_FOUND",
    "bidders": "ERR_BIDDER_NOT_FOUND",
    "sponsors": "ERR_SPONSOR_NOT_FOUND",
    "ads": "ERR_AD_NOT_FOUND",
    "items": "ERR_ITEM_NOT_FOUND",
    "bids": "ERR_BID_NOT_FOUND",
    "paddles": "ERR_PADDLE_RAISE_NOT_FOUND",
    "pledges": "ERR_PLEDGE_NOT_FOUND",
    "invoices": "ERR_INVOICE_NOT_FOUND",
    "payments": "ERR_PAYMENT_NOT_FOUND",
    "receipts": "ERR_RECEIPT_NOT_FOUND",
    "runs": "ERR_RUN_NOT_FOUND",
}


def fetch(kind, rid):
    """Resolve an entity id or raise the matching not-found error."""
    coll = getattr(db, kind)
    row = coll.get(rid) if isinstance(rid, str) else None
    if row is None:
        raise ApiError(NOT_FOUND[kind])
    return row


def rows(kind):
    return sorted(getattr(db, kind).values(), key=lambda r: r["_seq"])


# ---------------------------------------------------------------- time
def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        "%03dZ" % (datetime.now(timezone.utc).microsecond // 1000)


def _now_iso():
    d = datetime.now(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (d.microsecond // 1000)


def fmt_dt(d):
    d = d.astimezone(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (d.microsecond // 1000)


_DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}(:\d{2})?(\.\d+)?"
                    r"(([Zz])|([+-]\d{2}:?\d{2}))?$")


def parse_dt(value):
    """Parse an ISO-8601 instant; returns an aware UTC datetime or None."""
    if not isinstance(value, str) or not _DT_RE.match(value.strip()):
        return None
    s = value.strip().replace(" ", "T").replace("t", "T")
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def clock_dt():
    return parse_dt(db.clock)


# ---------------------------------------------------------------- money
def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------- entities
def new_row(**fields):
    ts = _now_iso()
    row = {"id": str(uuid.uuid4()), "created_at": ts, "updated_at": ts, "version": 1}
    row.update(fields)
    row["_seq"] = db.next_seq()
    return row


def touch(row):
    row["updated_at"] = _now_iso()
    row["version"] = int(row.get("version", 1)) + 1
    return row


def public(row):
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


# ---------------------------------------------------------------- envelope
def _request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": _now_iso()}


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), status


def ok_list(items, limit, offset, total):
    meta = _meta()
    meta.update({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(items) < total,
    })
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------- auth
def authenticate(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "missing or invalid authentication headers")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE", "role %s may not call this endpoint" % role)
    return uid, role


def own_check(condition):
    if not condition:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "caller does not own this resource")


# ---------------------------------------------------------------- input
def body():
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "request body is not valid JSON")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ApiError("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return parsed


_MISSING = object()


def _bad(name, why):
    raise ApiError("ERR_INVALID_REQUEST", "field '%s' %s" % (name, why))


def get_str(src, name, required=True, default=None, allow_empty=False):
    if name not in src or src[name] is None:
        if required:
            _bad(name, "is required")
        return default
    value = src[name]
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if not allow_empty and value.strip() == "":
        _bad(name, "must be non-empty")
    return value


def get_int(src, name, required=True, default=None, minimum=None):
    if name not in src or src[name] is None:
        if required:
            _bad(name, "is required")
        return default
    value = src[name]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(name, "must be >= %s" % minimum)
    return value


def get_bool(src, name, required=True, default=None):
    if name not in src or src[name] is None:
        if required:
            _bad(name, "is required")
        return default
    value = src[name]
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def get_enum(src, name, choices, required=True, default=None):
    value = get_str(src, name, required=required, default=default)
    if value is None:
        return None
    if value not in choices:
        _bad(name, "must be one of %s" % ", ".join(choices))
    return value


def get_dt(src, name, required=True, default=None):
    value = get_str(src, name, required=required, default=default)
    if value is None:
        return None, None
    parsed = parse_dt(value)
    if parsed is None:
        _bad(name, "must be an ISO 8601 instant")
    return value, parsed


def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            _bad("limit", "must be an integer")
        if limit < 1 or limit > 100:
            _bad("limit", "must be between 1 and 100")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            _bad("offset", "must be an integer")
        if offset < 0:
            _bad("offset", "must be >= 0")
    return limit, offset


def q_enum(name, choices):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in choices:
        _bad(name, "must be one of %s" % ", ".join(choices))
    return value


def q(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def paged(items, limit, offset):
    total = len(items)
    window = items[offset:offset + limit]
    return [public(r) for r in window], total
