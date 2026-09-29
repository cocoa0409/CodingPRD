"""Core infrastructure: error catalogue, response envelope, in-memory store, logical clock."""
import random
import string
import threading
import uuid
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING

from flask import g, jsonify

# --------------------------------------------------------------------------- #
# Error catalogue (PRD section 5)
# --------------------------------------------------------------------------- #
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_CASE_AUTHOR_REQUIRED": 403,
    "ERR_BRANCH_OWNERSHIP_REQUIRED": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_REFERENCED_RESOURCE_NOT_FOUND": 404,
    "ERR_STALE_BRANCH_VERSION": 412,
    "ERR_STALE_CASE_VERSION": 412,
    "ERR_CASE_STATE_INVALID": 409,
    "ERR_BRANCH_NOT_ACTIVE": 409,
    "ERR_NOTICE_NOT_OPEN": 409,
    "ERR_DISPOSITION_STATE_INVALID": 409,
    "ERR_PROPERTY_STATE_INVALID": 409,
    "ERR_ASSESSMENT_STATE_INVALID": 409,
    "ERR_CAMPAIGN_STATE_INVALID": 409,
    "ERR_PLAN_STATE_INVALID": 409,
    "ERR_RECEIVING_BRANCH_NOT_ACTIVE": 409,
    "ERR_IMPACT_ASSESSMENT_NOT_FINALIZED": 409,
    "ERR_NOTICE_PERIOD_INSUFFICIENT": 422,
    "ERR_NOTICE_PERIOD_NOT_ELAPSED": 409,
    "ERR_WARN_PERIOD_NOT_ELAPSED": 409,
    "ERR_TRANSITION_CAMPAIGN_NOT_LAUNCHED": 409,
    "ERR_NOTICE_WINDOW_CONFLICT": 409,
    "ERR_PLANNED_DATE_BEFORE_EFFECTIVE": 422,
    "ERR_CAMPAIGN_LEAD_TIME_INSUFFICIENT": 422,
    "ERR_UNWIND_WINDOW_CLOSED": 409,
    "ERR_OBSERVATION_OUT_OF_SEQUENCE": 409,
    "ERR_ABSORPTION_CAPACITY_EXCEEDED": 409,
    "ERR_BRANCH_HAS_OPEN_CASE": 409,
    "ERR_RECEIVING_BRANCH_INVALID": 422,
    "ERR_DUPLICATE_KEY": 409,
    "ERR_SEGMENT_MIX_INVALID": 422,
    "ERR_REVISION_LIMIT_EXCEEDED": 409,
    "ERR_OBSERVATION_SUBJECT_MISMATCH": 422,
    "ERR_SITE_SCORE_BELOW_MINIMUM": 422,
    "ERR_MARKET_OVER_BRANCHED": 409,
    "ERR_MARKET_DE_NOVO_HOLD": 409,
    "ERR_RETENTION_FORECAST_MISSING": 409,
    "ERR_PROPERTY_DISPOSITION_MISSING": 409,
    "ERR_STAFF_DISPOSITIONS_PENDING": 409,
    "ERR_NO_ELIGIBLE_RECEIVING_BRANCH": 422,
    "ERR_NO_PERFORMANCE_HISTORY": 409,
    "ERR_DISPOSITION_TARGET_INVALID": 422,
    "ERR_SAVINGS_BELOW_FLOOR": 422,
    "ERR_MONITORING_INCOMPLETE": 409,
    "ERR_PROPERTY_TERMS_INCOMPLETE": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = ERROR_STATUS.get(error_id, 400)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# --------------------------------------------------------------------------- #
# In-memory store.  Empty on every boot; nothing is ever seeded.
# --------------------------------------------------------------------------- #
COLLECTIONS = (
    "market_areas",
    "branches",
    "performance_snapshots",
    "consolidation_cases",
    "retention_forecasts",
    "impact_assessments",
    "closure_notices",
    "staff_dispositions",
    "property_dispositions",
    "transition_campaigns",
    "de_novo_plans",
    "deposit_observations",
)

DB = {name: {} for name in COLLECTIONS}

LOCK = threading.RLock()

_SEQ = [0]

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
CLOCK = {"current": DEFAULT_CLOCK}


def next_seq():
    _SEQ[0] += 1
    return _SEQ[0]


def new_id():
    return str(uuid.uuid4())


def utc_now_iso():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)


def format_instant(dt):
    """Render the logical clock instant the way the PRD shows it: 2026-08-01T00:00:00Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def clock_now():
    return CLOCK["current"]


def clock_today():
    return CLOCK["current"].astimezone(timezone.utc).date()


def clock_today_iso():
    return clock_today().isoformat()


# --------------------------------------------------------------------------- #
# Record helpers
# --------------------------------------------------------------------------- #
def new_record(collection, fields, versioned=True):
    created_at = utc_now_iso()
    rec = {"id": new_id(), "created_at": created_at}
    if versioned:
        rec["updated_at"] = created_at
        rec["version"] = 1
    rec.update(fields)
    rec["_seq"] = next_seq()
    DB[collection][rec["id"]] = rec
    return rec


def touch(rec):
    """Bump version + updated_at at most once per request for this record."""
    if rec is None or "version" not in rec:
        return rec
    seen = getattr(g, "_touched", None)
    if seen is None:
        seen = set()
        g._touched = seen
    if id(rec) in seen:
        return rec
    seen.add(id(rec))
    rec["version"] = rec["version"] + 1
    rec["updated_at"] = utc_now_iso()
    return rec


def public(rec):
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def sort_key_created(rec):
    return (rec["created_at"], rec["_seq"])


def all_of(collection):
    return list(DB[collection].values())


# --------------------------------------------------------------------------- #
# Response envelope (PRD section 2.2)
# --------------------------------------------------------------------------- #
_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    rid = getattr(g, "_api_request_id", None)
    if rid is None:
        rid = "req_" + "".join(random.choice(_ALNUM) for _ in range(20))
        g._api_request_id = rid
    return rid


def base_meta():
    return {"api_request_id": request_id(), "api_request_timestamp": utc_now_iso()}


def object_response(data, status=200):
    body = {"meta": base_meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def list_response(items, limit, offset, total_count):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# --------------------------------------------------------------------------- #
# Rounding discipline (PRD section 2.7)
# --------------------------------------------------------------------------- #
def rhu(numerator, denominator=1):
    """round_half_up of numerator/denominator; ties move away from zero."""
    q = Decimal(numerator) / Decimal(denominator)
    return int(q.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec(value):
    return Decimal(str(value))


def floor_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_FLOOR))


def ceil_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_CEILING))


def parse_date(value):
    return date.fromisoformat(value)


def day_diff(later, earlier):
    """Whole calendar days between two ISO date strings (later - earlier)."""
    return (parse_date(later) - parse_date(earlier)).days


def date_plus(value, days):
    return (parse_date(value) + timedelta(days=days)).isoformat()
