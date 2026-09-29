"""Foundation: errors, envelope, in-memory store, logical clock, auth, shape validation."""
import json
import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, getcontext

from flask import request, jsonify

getcontext().prec = 60

# --------------------------------------------------------------------------
# Error catalogue (PRD section 5)
# --------------------------------------------------------------------------
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 422,
    "ERR_COUNTERPARTY_NOT_FOUND": 404,
    "ERR_PORTFOLIO_NOT_FOUND": 404,
    "ERR_LOAN_NOT_FOUND": 404,
    "ERR_ASSUMPTION_SET_NOT_FOUND": 404,
    "ERR_RATE_CURVE_NOT_FOUND": 404,
    "ERR_VALUATION_RUN_NOT_FOUND": 404,
    "ERR_BID_PACKAGE_NOT_FOUND": 404,
    "ERR_TAPE_LINE_NOT_FOUND": 404,
    "ERR_BID_NOT_FOUND": 404,
    "ERR_PURCHASE_AGREEMENT_NOT_FOUND": 404,
    "ERR_APPROVAL_REQUEST_NOT_FOUND": 404,
    "ERR_SERVICING_TRANSFER_NOT_FOUND": 404,
    "ERR_ERROR_CASE_NOT_FOUND": 404,
    "ERR_HEDGE_POSITION_NOT_FOUND": 404,
    "ERR_STALE_PORTFOLIO_VERSION": 412,
    "ERR_STALE_BID_PACKAGE_VERSION": 412,
    "ERR_STALE_AGREEMENT_VERSION": 412,
    "ERR_TAPE_LOCKED": 409,
    "ERR_TAPE_NOT_LOCKED": 409,
    "ERR_TAPE_EMPTY": 422,
    "ERR_PACKAGE_INVALID_STATE": 409,
    "ERR_PACKAGE_NOT_ACCEPTING_BIDS": 409,
    "ERR_BID_INVALID_STATE": 409,
    "ERR_AGREEMENT_INVALID_STATE": 409,
    "ERR_TRANSFER_INVALID_STATE": 409,
    "ERR_CASE_INVALID_STATE": 409,
    "ERR_APPROVAL_ALREADY_DECIDED": 409,
    "ERR_HEDGE_ALREADY_CLOSED": 409,
    "ERR_COUNTERPARTY_ROLE_MISMATCH": 422,
    "ERR_VALUATION_STALE": 409,
    "ERR_NO_ACTIVE_RATE_CURVE": 409,
    "ERR_RATE_CURVE_DATE_NOT_ADVANCING": 422,
    "ERR_BIDDER_NOT_ELIGIBLE": 422,
    "ERR_BIDDER_RISK_TIER_TOO_HIGH": 422,
    "ERR_BID_DEADLINE_PASSED": 422,
    "ERR_BID_BELOW_RESERVE": 422,
    "ERR_MAX_NEGOTIATION_ROUNDS": 409,
    "ERR_AGENCY_APPROVAL_PENDING": 409,
    "ERR_CONDITION_WAIVER_REQUIRED": 422,
    "ERR_DUPLICATE_APPROVAL_REQUEST": 409,
    "ERR_TRANSFER_DATE_TOO_SOON": 422,
    "ERR_ONBOARDING_CAPACITY_EXCEEDED": 409,
    "ERR_MARKETING_WINDOW_OVERLAP": 409,
    "ERR_NOTICE_SENDER_ROLE_MISMATCH": 422,
    "ERR_NOTICE_EFFECTIVE_DATE_MISMATCH": 422,
    "ERR_NOTICE_LATE": 409,
    "ERR_NOTICE_COMPLIANCE_INCOMPLETE": 409,
    "ERR_LOAN_NOT_ON_TAPE": 422,
    "ERR_ESCROW_NOT_MAPPED": 409,
    "ERR_TRANSFER_NOT_READY": 409,
    "ERR_DUPLICATE_LOAN_NUMBER": 409,
    "ERR_REOPEN_WINDOW_EXPIRED": 422,
    "ERR_MAX_REOPENS_EXCEEDED": 409,
    "ERR_HOLDBACK_NOT_ELIGIBLE": 409,
    "ERR_HOLDBACK_EXHAUSTED": 409,
    "ERR_COMPLAINT_TIER_BLOCKS_RELEASE": 409,
    "ERR_CLAWBACK_EXCEEDS_RELEASED": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = ERROR_HTTP.get(error_id, 422)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# --------------------------------------------------------------------------
# Logical clock (PRD section 2.3) -- never the host wall clock.
# --------------------------------------------------------------------------
CLOCK = {"now": datetime(2026, 8, 1, 0, 0, 0)}


def now_dt():
    return CLOCK["now"]


def now_date():
    return CLOCK["now"].date()


def fmt_dt(dt):
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return fmt_dt(CLOCK["now"])


def fmt_date(d):
    if d is None:
        return None
    return d.strftime("%Y-%m-%d")


_DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?([Zz]|[+-]\d{2}:?\d{2})?$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_dt(value):
    """Parse an ISO-8601 datetime into a naive UTC datetime. None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not _DT_RE.match(text):
        return None
    text = text.replace(" ", "T").replace("t", "T")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def parse_date(value):
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


# --------------------------------------------------------------------------
# In-memory store -- starts empty on every boot, nothing is ever seeded.
# --------------------------------------------------------------------------
DB = {
    "counterparties": {},
    "portfolios": {},
    "loans": {},
    "assumption_sets": {},
    "rate_curves": {},
    "valuation_runs": {},
    "bid_packages": {},
    "tape_lines": {},
    "bids": {},
    "agreements": {},
    "approval_requests": {},
    "transfers": {},
    "notices": {},
    "error_cases": {},
    "hedge_positions": {},
}

_SEQ = {"n": 0}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def new_row(collection, versioned=True):
    row = {
        "id": str(uuid.uuid4()),
        "created_at": now_iso(),
        "_created": now_dt(),
        "_seq": next_seq(),
    }
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    DB[collection][row["id"]] = row
    return row


def touch(row):
    """Accepted mutation of a row: refresh updated_at and bump version by exactly 1."""
    row["updated_at"] = now_iso()
    row["version"] = row.get("version", 0) + 1


def rows(collection):
    return list(DB[collection].values())


def sort_created(items):
    return sorted(items, key=lambda r: (r["_created"], r["_seq"]))


# --------------------------------------------------------------------------
# Response envelope (PRD section 2.2)
# --------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def base_meta():
    return {"api_request_id": request_id(), "api_request_timestamp": now_iso()}


def ok(data, status=200):
    return jsonify({"meta": base_meta(), "response_type": "object", "data": data}), status


def ok_list(items, limit, offset, total_count):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_response(err):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# --------------------------------------------------------------------------
# Pagination (PRD section 2.2)
# --------------------------------------------------------------------------
def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except ValueError:
            fail("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit out of bounds")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except ValueError:
            fail("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset out of bounds")
    return limit, offset


def paginate(items, serializer):
    limit, offset = pagination()
    total = len(items)
    window = items[offset:offset + limit]
    return ok_list([serializer(r) for r in window], limit, offset, total)


def filter_eq(items, field, arg_name=None, allowed=None):
    name = arg_name or field
    raw = request.args.get(name)
    if raw is None:
        return items
    if allowed is not None and raw not in allowed:
        fail("ERR_INVALID_REQUEST", "invalid %s filter" % name)
    return [r for r in items if r.get(field) == raw]


# --------------------------------------------------------------------------
# Auth / RBAC (PRD section 2.1)
# --------------------------------------------------------------------------
ROLES = (
    "ValuationAnalyst",
    "TransactionManager",
    "SellerServicer",
    "BuyerServicer",
    "AgencyApprover",
    "ComplianceOfficer",
    "HedgeDesk",
    "PlatformAdmin",
)
ALL_ROLES = ROLES


def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    if user_id is None or user_id.strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required")
    role = request.headers.get("X-User-Role")
    if role is None or role.strip() == "" or role not in ROLES or role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "role is not authorized for this operation")
    return user_id, role


def require_owner(user_id, expected_id):
    if expected_id is None or user_id != expected_id:
        fail("ERR_NOT_RESOURCE_OWNER", "acting identity does not own this resource")


# --------------------------------------------------------------------------
# Decimal helpers (PRD section 2.5) -- half-up away from zero, never float math
# --------------------------------------------------------------------------
def D(value):
    return Decimal(str(value))


def rhu(value, places=0):
    """Round half up away from zero to `places` decimals."""
    quant = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def floor_int(value):
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_FLOOR))


def num(value, places):
    """Emit a decimal quantity as a JSON number with the mandated precision."""
    if value is None:
        return None
    return float(rhu(Decimal(value), places))


# --------------------------------------------------------------------------
# Request-shape validation (PRD section 2.12 step 3)
# --------------------------------------------------------------------------
def json_body():
    raw = request.get_data(cache=True)
    if raw is None or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        fail("ERR_INVALID_REQUEST", "request body is not valid JSON")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return parsed


def body_of(*allowed):
    """Parse the body and reject unknown / system-maintained / computed field writes."""
    body = json_body()
    for key in body.keys():
        if key not in allowed:
            fail("ERR_INVALID_REQUEST", "unexpected field '%s'" % key)
    return body


def no_body():
    body = json_body()
    if body:
        fail("ERR_INVALID_REQUEST", "this operation accepts no request body")
    return body


_MISSING = object()


def _present(body, key, required):
    if key not in body or body[key] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "field '%s' is required" % key)
        return False
    return True


def f_str(body, key, required=True, min_len=1, max_len=None, non_blank=True):
    if not _present(body, key, required):
        return None
    value = body[key]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "field '%s' must be a string" % key)
    if non_blank and value.strip() == "":
        fail("ERR_INVALID_REQUEST", "field '%s' must not be blank" % key)
    if min_len is not None and len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "field '%s' is too short" % key)
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "field '%s' is too long" % key)
    return value


def f_int(body, key, required=True, minimum=None, maximum=None, default=_MISSING):
    if not _present(body, key, required):
        return None if default is _MISSING else default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "field '%s' must be an integer" % key)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "field '%s' is below the permitted minimum" % key)
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "field '%s' is above the permitted maximum" % key)
    return value


def f_dec(body, key, required=True, minimum=None, maximum=None, places=None,
          exclusive_min=False, exclusive_max=False, default=_MISSING):
    if not _present(body, key, required):
        return None if default is _MISSING else default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "field '%s' must be a number" % key)
    dec = D(value)
    if places is not None:
        exp = dec.as_tuple().exponent
        if isinstance(exp, int) and -exp > places:
            fail("ERR_INVALID_REQUEST",
                 "field '%s' carries more than %d decimal places" % (key, places))
    if minimum is not None:
        if exclusive_min and dec <= D(minimum):
            fail("ERR_INVALID_REQUEST", "field '%s' must be greater than %s" % (key, minimum))
        if not exclusive_min and dec < D(minimum):
            fail("ERR_INVALID_REQUEST", "field '%s' is below the permitted minimum" % key)
    if maximum is not None:
        if exclusive_max and dec >= D(maximum):
            fail("ERR_INVALID_REQUEST", "field '%s' must be less than %s" % (key, maximum))
        if not exclusive_max and dec > D(maximum):
            fail("ERR_INVALID_REQUEST", "field '%s' is above the permitted maximum" % key)
    return dec


def f_bool(body, key, required=True, default=_MISSING):
    if not _present(body, key, required):
        return None if default is _MISSING else default
    value = body[key]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "field '%s' must be a boolean" % key)
    return value


def f_enum(body, key, choices, required=True, default=_MISSING):
    if not _present(body, key, required):
        return None if default is _MISSING else default
    value = body[key]
    if not isinstance(value, str) or value not in choices:
        fail("ERR_INVALID_REQUEST", "field '%s' must be one of %s" % (key, ", ".join(choices)))
    return value


def f_date(body, key, required=True):
    if not _present(body, key, required):
        return None
    value = body[key]
    parsed = parse_date(value) if isinstance(value, str) else None
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "field '%s' must be a YYYY-MM-DD date" % key)
    return parsed


def f_dt(body, key, required=True):
    """Returns (datetime, verbatim string) so client-supplied instants echo unchanged."""
    if not _present(body, key, required):
        return None, None
    value = body[key]
    parsed = parse_dt(value) if isinstance(value, str) else None
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "field '%s' must be an ISO-8601 UTC timestamp" % key)
    return parsed, value


def f_id(body, key, required=True):
    if not _present(body, key, required):
        return None
    value = body[key]
    if not isinstance(value, str) or value.strip() == "":
        fail("ERR_INVALID_REQUEST", "field '%s' must be an id string" % key)
    return value


def f_str_list(body, key, choices, required=False, default=None):
    if not _present(body, key, required):
        return list(default) if default is not None else None
    value = body[key]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "field '%s' must be an array" % key)
    seen = []
    for item in value:
        if not isinstance(item, str) or item not in choices:
            fail("ERR_INVALID_REQUEST", "field '%s' contains an unknown value" % key)
        if item in seen:
            fail("ERR_INVALID_REQUEST", "field '%s' contains duplicates" % key)
        seen.append(item)
    return seen


def lookup(collection, row_id, not_found):
    row = DB[collection].get(row_id)
    if row is None:
        fail(not_found)
    return row


# --------------------------------------------------------------------------
# Endpoint role sets (PRD section 4 endpoint table)
# --------------------------------------------------------------------------
R_ADMIN = ("PlatformAdmin",)
R_VALUATION = ("ValuationAnalyst",)
R_TXN = ("TransactionManager",)
R_SELLER = ("SellerServicer",)
R_BUYER = ("BuyerServicer",)
R_APPROVER = ("AgencyApprover",)
R_COMPLIANCE = ("ComplianceOfficer",)
R_HEDGE = ("HedgeDesk",)
READ_CP = ("PlatformAdmin", "TransactionManager", "ValuationAnalyst", "ComplianceOfficer")
READ_PF = ("PlatformAdmin", "TransactionManager", "ValuationAnalyst", "ComplianceOfficer",
           "HedgeDesk", "SellerServicer", "BuyerServicer")
READ_LOAN = ("PlatformAdmin", "TransactionManager", "ValuationAnalyst", "ComplianceOfficer",
             "SellerServicer", "BuyerServicer")
READ_NOTICE = ("PlatformAdmin", "TransactionManager", "ComplianceOfficer",
               "SellerServicer", "BuyerServicer")
READ_REF = ("PlatformAdmin", "TransactionManager", "ValuationAnalyst", "ComplianceOfficer",
            "HedgeDesk")
READ_PKG = READ_LOAN
READ_AGR = ("PlatformAdmin", "TransactionManager", "ComplianceOfficer", "AgencyApprover",
            "SellerServicer", "BuyerServicer")
READ_APR = ("PlatformAdmin", "TransactionManager", "ComplianceOfficer", "AgencyApprover")
READ_XFER = ("PlatformAdmin", "TransactionManager", "ComplianceOfficer",
             "SellerServicer", "BuyerServicer")
READ_HEDGE = ("PlatformAdmin", "TransactionManager", "ValuationAnalyst", "ComplianceOfficer",
              "HedgeDesk", "SellerServicer")
