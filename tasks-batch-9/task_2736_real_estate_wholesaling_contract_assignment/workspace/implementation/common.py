"""Foundation: response envelope, error catalog, logical clock, in-memory store,
request validation helpers and RBAC header handling.

Structural names (headers, envelope fields, pagination fields, error ids) are all
taken from PRD.md §2 and SCAFFOLD.yaml §1.0/§1.4/§1.6.
"""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from flask import jsonify, request

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Error catalog (PRD §5 / SCAFFOLD §1.6)
# ---------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_PAGINATION_OUT_OF_RANGE": 400,
    "ERR_WHOLESALER_NOT_FOUND": 404,
    "ERR_MARKETING_CAMPAIGN_NOT_FOUND": 404,
    "ERR_SELLER_LEAD_NOT_FOUND": 404,
    "ERR_DEAL_ANALYSIS_NOT_FOUND": 404,
    "ERR_PURCHASE_CONTRACT_NOT_FOUND": 404,
    "ERR_DISCLOSURE_ACKNOWLEDGEMENT_NOT_FOUND": 404,
    "ERR_EARNEST_MONEY_DEPOSIT_NOT_FOUND": 404,
    "ERR_CASH_BUYER_NOT_FOUND": 404,
    "ERR_PROOF_OF_FUNDS_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_OFFER_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_AGREEMENT_NOT_FOUND": 404,
    "ERR_TITLE_ORDER_NOT_FOUND": 404,
    "ERR_COMPLIANCE_REVIEW_NOT_FOUND": 404,
    "ERR_DISPUTE_CASE_NOT_FOUND": 404,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_DUAL_CONTROL_REQUIRED": 403,
    "ERR_STALE_CONTRACT_VERSION": 412,
    "ERR_STALE_LEAD_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_CONTRACT_TERMINAL": 409,
    "ERR_CAMPAIGN_NOT_PUBLISHED": 409,
    "ERR_LEAD_NOT_SCREENED": 409,
    "ERR_DEAL_ANALYSIS_NOT_FINALIZED": 409,
    "ERR_CONTRACT_NOT_SIGNED": 409,
    "ERR_POF_NOT_VERIFIED": 409,
    "ERR_OFFER_NOT_ACCEPTED": 409,
    "ERR_CONTRACT_NOT_ASSIGNED": 409,
    "ERR_DEPOSIT_NOT_HELD": 409,
    "ERR_EVIDENCE_INCOMPLETE": 409,
    "ERR_WHOLESALER_COMPLIANCE_HOLD": 403,
    "ERR_INTENT_TO_ASSIGN_NOT_DISCLOSED": 422,
    "ERR_LICENSURE_DISCLOSURE_MISSING": 422,
    "ERR_DNC_SCRUB_REQUIRED": 422,
    "ERR_DISCLOSURE_ACKNOWLEDGEMENT_MISSING": 422,
    "ERR_EQUITY_SKIMMING_PROHIBITED": 422,
    "ERR_COOLING_OFF_NOT_ELAPSED": 422,
    "ERR_UNLICENSED_BROKERAGE_ACTIVITY": 422,
    "ERR_INSPECTION_PERIOD_EXPIRED": 409,
    "ERR_ASSIGNMENT_DEADLINE_PASSED": 409,
    "ERR_PROOF_OF_FUNDS_EXPIRED": 422,
    "ERR_PROPERTY_OCCUPANCY_CONFLICT": 409,
    "ERR_FUNDING_WINDOW_CONFLICT": 409,
    "ERR_STRUCTURE_MISMATCH": 409,
    "ERR_NEGOTIATION_ROUND_LIMIT": 409,
    "ERR_INSUFFICIENT_QUALIFYING_COMPS": 422,
    "ERR_DUPLICATE_ACTIVE_OFFER": 409,
    "ERR_MAO_EXCEEDED": 422,
    "ERR_OFFER_BELOW_CONTRACT_PRICE": 422,
    "ERR_INSUFFICIENT_VERIFIED_FUNDS": 422,
    "ERR_ASSIGNMENT_FEE_CAP_EXCEEDED": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or "Request rejected: %s" % error_id


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Timestamps / logical clock
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.4)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_iso(value):
    """Parse an ISO 8601 UTC instant. Returns None when unparseable/not UTC."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("z") or text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    if dt.utcoffset() != timedelta(0):
        return None
    return dt.astimezone(UTC)


# ---------------------------------------------------------------------------
# In-memory store — empty on every boot, nothing is ever seeded.
# ---------------------------------------------------------------------------
class Store(object):
    COLLECTIONS = (
        "wholesalers",
        "marketing_campaigns",
        "seller_leads",
        "deal_analyses",
        "purchase_contracts",
        "disclosure_acknowledgements",
        "earnest_money_deposits",
        "cash_buyers",
        "proof_of_funds",
        "assignment_offers",
        "assignment_agreements",
        "title_orders",
        "compliance_reviews",
        "dispute_cases",
    )

    def __init__(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self.current_utc = DEFAULT_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def now():
    return db.current_utc


def new_id():
    return str(uuid.uuid4())


def base_record(versioned=True):
    rec = {"id": new_id(), "created_at": now()}
    if versioned:
        rec["updated_at"] = now()
        rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


def touch(rec):
    """Mutation bookkeeping: refresh updated_at and increment version (PRD §2.4)."""
    if "version" in rec:
        rec["updated_at"] = now()
        rec["version"] = rec["version"] + 1
    return rec


# ---------------------------------------------------------------------------
# Response envelope (PRD §2.2)
# ---------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso_ms(datetime.now(UTC)),
    }


def serialize(rec):
    if rec is None:
        return None
    out = {}
    for key, value in rec.items():
        if key.startswith("_"):
            continue
        if isinstance(value, datetime):
            out[key] = iso_ms(value)
        elif isinstance(value, Decimal):
            out[key] = float(value)
        elif isinstance(value, list):
            out[key] = list(value)
        else:
            out[key] = value
    return out


def respond_object(rec, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": serialize(rec)}
    return jsonify(body), status


def respond_raw(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def respond_list(records, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(records)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serialize(r) for r in records],
    }
    return jsonify(body), 200


# ---------------------------------------------------------------------------
# Auth (PRD §2.1)
# ---------------------------------------------------------------------------
ROLES = (
    "Wholesaler",
    "Seller",
    "CashBuyer",
    "TitleAgent",
    "ComplianceOfficer",
    "PlatformAdmin",
)
ALL_ROLES = list(ROLES)
READ_ALL = list(ROLES)


def authenticate(allowed_roles, require_user_id=True):
    role = request.headers.get("X-User-Role")
    if role is None or role.strip() == "" or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role is missing or not a declared role.")
    user_id = request.headers.get("X-User-ID")
    if require_user_id and (user_id is None or user_id.strip() == ""):
        fail("ERR_UNAUTHENTICATED", "X-User-ID is required for this operation.")
    if role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE", "Role %s may not invoke this endpoint." % role)
    return role, (user_id.strip() if isinstance(user_id, str) else user_id)


# ---------------------------------------------------------------------------
# Body validation helpers — every failure is ERR_INVALID_REQUEST (rank 3)
# ---------------------------------------------------------------------------
def get_body():
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def _present(body, name):
    return name in body and body[name] is not None


def req_str(body, name, max_len=None, min_len=1):
    if not _present(body, name):
        fail("ERR_INVALID_REQUEST", "%s is required." % name)
    value = body[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string." % name)
    if min_len is not None and len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "%s must be non-empty." % name)
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "%s exceeds %d characters." % (name, max_len))
    return value


def opt_str(body, name, max_len=None, min_len=1, default=None):
    if not _present(body, name):
        return default
    return req_str(body, name, max_len=max_len, min_len=min_len)


def req_state_code(body, name):
    value = req_str(body, name, max_len=2, min_len=2)
    if len(value) != 2 or not value.isalpha() or value != value.upper():
        fail("ERR_INVALID_REQUEST", "%s must be exactly two uppercase letters." % name)
    return value


def req_int(body, name, minimum=None, maximum=None):
    if not _present(body, name):
        fail("ERR_INVALID_REQUEST", "%s is required." % name)
    return _as_int(body[name], name, minimum, maximum)


def opt_int(body, name, minimum=None, maximum=None, default=None):
    if not _present(body, name):
        return default
    return _as_int(body[name], name, minimum, maximum)


def _as_int(value, name, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be <= %d." % (name, maximum))
    return value


def req_bool(body, name):
    if not _present(body, name):
        fail("ERR_INVALID_REQUEST", "%s is required." % name)
    value = body[name]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean." % name)
    return value


def opt_bool(body, name, default=False):
    if not _present(body, name):
        return default
    return req_bool(body, name)


def req_enum(body, name, allowed):
    value = req_str(body, name, max_len=None, min_len=1)
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s." % (name, ", ".join(allowed)))
    return value


def opt_enum(body, name, allowed, default=None):
    if not _present(body, name):
        return default
    return req_enum(body, name, allowed)


def req_dt(body, name):
    if not _present(body, name):
        fail("ERR_INVALID_REQUEST", "%s is required." % name)
    value = body[name]
    parsed = parse_iso(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 UTC instant." % name)
    return parsed


def req_number(value, name, minimum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "%s must be a number." % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be >= %s." % (name, minimum))
    return value


def opt_id(body, name):
    if not _present(body, name):
        return None
    value = body[name]
    if not isinstance(value, str) or value.strip() == "":
        fail("ERR_INVALID_REQUEST", "%s must be a non-empty string." % name)
    return value


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3) and deterministic list ordering
# ---------------------------------------------------------------------------
def read_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None and limit_raw != "":
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
    if offset_raw is not None and offset_raw != "":
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
    if limit < 1 or limit > 100 or offset < 0:
        fail("ERR_PAGINATION_OUT_OF_RANGE", "limit must be 1..100 and offset >= 0.")
    return limit, offset


def sort_records(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def apply_filters(records, filters):
    """filters: list of (query_param_name, record_field_name)."""
    out = list(records)
    for param, field in filters:
        wanted = request.args.get(param)
        if wanted is None or wanted == "":
            continue
        out = [r for r in out if r.get(field) == wanted]
    return out


def list_response(records, filters):
    limit, offset = read_pagination()
    filtered = apply_filters(records, filters)
    ordered = sort_records(filtered)
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return respond_list(window, limit, offset, total)
