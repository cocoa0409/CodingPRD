"""Foundation: logical clock, in-memory store, response envelope, error catalogue.

Storage is in-memory only.  The store starts completely empty on every boot --
nothing is seeded, preloaded or hardcoded.
"""
import json
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from flask import jsonify, request

UTC = timezone.utc

# PRD 2.6: "Before any client moves it, the logical clock reads exactly
# 2026-08-01T00:00:00Z, and it must never fall back to real time."
INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


class _Clock(object):
    def __init__(self):
        self.now = INITIAL_CLOCK


CLOCK = _Clock()


def now():
    return CLOCK.now


TABLES = (
    "growers",
    "blocks",
    "specs",
    "contracts",
    "allocations",
    "lanes",
    "crews",
    "visits",
    "pick_calls",
    "appointments",
    "weigh_tags",
    "grades",
    "lines",
    "installments",
)

DB = dict((t, {}) for t in TABLES)

_SEQ = {"n": 0}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def new_id():
    # PRD 2.4: "a UUID string with no type prefix of any kind"
    return str(uuid.uuid4())


# --------------------------------------------------------------------------
# timestamps
# --------------------------------------------------------------------------
def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def iso_clock(dt):
    """Clock endpoint shape: 2026-08-01T00:00:00Z when there is no fraction."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return iso_ms(dt)


def parse_dt(value):
    """Parse an ISO-8601 instant; returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text[-1] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def add_hours(dt, hours):
    return dt + timedelta(hours=int(hours))


def add_days(dt, days):
    return dt + timedelta(days=int(days))


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=int(minutes))


def utc_year(dt):
    return dt.astimezone(UTC).year


def utc_date(dt):
    return dt.astimezone(UTC).date()


# --------------------------------------------------------------------------
# numeric discipline
# --------------------------------------------------------------------------
def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def q(value, places):
    """round_half_up to `places` decimal places."""
    exp = Decimal(1).scaleb(-places)
    return D(value).quantize(exp, rounding=ROUND_HALF_UP)


def q1(value):
    return q(value, 1)


def q2(value):
    return q(value, 2)


def q3(value):
    return q(value, 3)


def cents(value):
    """round_half_up to a whole number of cents."""
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def tenths(value):
    """Integer tenths (PRD 2.7): x * 10 rounded half up to a whole number."""
    return int((D(value) * 10).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_div(a, b):
    """Floor of a / b for integers."""
    if b == 0:
        return 0
    return int(Decimal(a) / Decimal(b) // 1) if False else a // b


def dmax(a, b):
    return a if a >= b else b


def dmin(a, b):
    return a if a <= b else b


ZERO3 = Decimal("0.000")


# --------------------------------------------------------------------------
# error catalogue (PRD section 5)
# --------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_MISSING_AUTH_HEADER": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_CONTRACT_GROWER": 403,
    "ERR_SOD_SAME_USER_GRADING": 403,
    "ERR_GROWER_NOT_FOUND": 404,
    "ERR_BLOCK_NOT_FOUND": 404,
    "ERR_QUALITY_SPEC_NOT_FOUND": 404,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_ALLOCATION_NOT_FOUND": 404,
    "ERR_LANE_NOT_FOUND": 404,
    "ERR_CREW_NOT_FOUND": 404,
    "ERR_SAMPLING_VISIT_NOT_FOUND": 404,
    "ERR_PICK_CALL_NOT_FOUND": 404,
    "ERR_APPOINTMENT_NOT_FOUND": 404,
    "ERR_WEIGH_TAG_NOT_FOUND": 404,
    "ERR_SETTLEMENT_LINE_NOT_FOUND": 404,
    "ERR_INSTALLMENT_NOT_FOUND": 404,
    "ERR_GRADE_NOT_FOUND": 404,
    "ERR_VALIDATION": 422,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_BASIS_FIELD_MISMATCH": 422,
    "ERR_INVALID_INSTALLMENT_PLAN": 422,
    "ERR_DUPLICATE_CODE": 409,
    "ERR_STALE_APPOINTMENT_VERSION": 412,
    "ERR_STALE_WEIGH_TAG_VERSION": 412,
    "ERR_CONTRACT_STATE_INVALID": 409,
    "ERR_PICK_CALL_STATE_INVALID": 409,
    "ERR_APPOINTMENT_NOT_OPEN": 409,
    "ERR_LANE_CLOSED": 409,
    "ERR_TAG_WEIGH_STATE_INVALID": 409,
    "ERR_TAG_NOT_DISPUTABLE": 409,
    "ERR_INSTALLMENT_NOT_PAYABLE": 409,
    "ERR_MAX_OFFER_ROUNDS_EXCEEDED": 409,
    "ERR_MAX_PICK_CALL_REVISIONS_EXCEEDED": 409,
    "ERR_RENEWAL_WINDOW_NOT_OPEN": 409,
    "ERR_RELIABILITY_BELOW_RENEWAL_THRESHOLD": 409,
    "ERR_NO_ALLOCATIONS": 409,
    "ERR_NO_PROVISIONAL_LINES": 409,
    "ERR_GROWER_SUSPENDED": 403,
    "ERR_BLOCK_NOT_PICK_READY": 422,
    "ERR_LANE_WINDOW_CONFLICT": 409,
    "ERR_CREW_WINDOW_OVERLAP_LIMIT": 409,
    "ERR_APPOINTMENT_OUTSIDE_PICK_WINDOW": 422,
    "ERR_OUTSIDE_APPOINTMENT_WINDOW": 409,
    "ERR_INSUFFICIENT_PICK_NOTICE": 422,
    "ERR_ACK_WINDOW_CLOSED": 409,
    "ERR_DISPUTE_WINDOW_CLOSED": 409,
    "ERR_TERMINATION_NOTICE_TOO_SHORT": 422,
    "ERR_BLOCK_NOT_ALLOCATED": 409,
    "ERR_CREW_REGION_MISMATCH": 422,
    "ERR_BLOCK_GROWER_MISMATCH": 409,
    "ERR_LANE_DAILY_CAPACITY_EXCEEDED": 409,
    "ERR_LOAD_EXCEEDS_LANE_MAX": 409,
    "ERR_TARE_EXCEEDS_GROSS": 422,
    "ERR_PAYMENT_EXCEEDS_BALANCE": 409,
    "ERR_LIEN_OUTSTANDING": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, status=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        self.status = status or ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    words = error_id.replace("ERR_", "").replace("_", " ").lower()
    return "Request refused: " + words + "."


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# --------------------------------------------------------------------------
# response envelope (PRD 2.2)
# --------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def meta_base():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": iso_ms(CLOCK.now),
    }


def jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return iso_ms(value)
    if isinstance(value, dict):
        return dict((k, jsonable(v)) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def respond(data, status=200):
    body = {
        "meta": meta_base(),
        "response_type": "object",
        "data": jsonable(data if data is not None else {}),
    }
    return jsonify(body), status


def respond_list(rows, total, limit, offset):
    meta = meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(rows)) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": jsonable(rows),
    }
    return jsonify(body), 200


def respond_error(error_id, message, status):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# --------------------------------------------------------------------------
# request body
# --------------------------------------------------------------------------
def read_body():
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw, parse_float=Decimal)
    except Exception:
        fail("ERR_VALIDATION", "Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail("ERR_VALIDATION", "Request body must be a JSON object.")
    return parsed


# --------------------------------------------------------------------------
# record helpers
# --------------------------------------------------------------------------
def new_record(table, fields):
    row = dict(fields)
    row["id"] = new_id()
    row["_seq"] = next_seq()
    row["created_at"] = CLOCK.now
    if table != "grades":
        row["updated_at"] = CLOCK.now
        row["version"] = 1
    DB[table][row["id"]] = row
    return row


def touch(row):
    """A mutation in the sense of PRD 2.4: updated_at refreshed, version + 1."""
    if "version" in row:
        row["updated_at"] = CLOCK.now
        row["version"] = row["version"] + 1
    return row


def rows(table):
    return list(DB[table].values())


def by_created_asc(items):
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))


def by_created_desc(items):
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]), reverse=True)
