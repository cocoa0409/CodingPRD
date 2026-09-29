"""Foundation layer: in-memory store, logical clock, response envelope, errors,
auth/RBAC middleware and shared request-shape validators.

Storage is process-local and purely in memory. Nothing is seeded at import time.
"""
import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, InvalidOperation

from flask import request, jsonify

# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #

ERROR_STATUS = {
    "ERR_MISSING_USER_CONTEXT": 400,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_ACTOR_NOT_COMMITTEE_MEMBER": 403,
    "ERR_ACTOR_NOT_SELF": 403,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_CROSS_PLAN_REFERENCE": 422,
    "ERR_MOTION_SUBJECT_MISMATCH": 422,
    "ERR_OUTGOING_FUND_MISMATCH": 422,
    "ERR_ASSET_CLASS_MISMATCH": 422,
    "ERR_QDIA_REQUIRES_TARGET_DATE_SUITE": 422,
    "ERR_POOL_FUND_INELIGIBLE": 422,
    "ERR_INVALID_REQUEST": 400,
    "ERR_IPS_WEIGHTS_INVALID": 400,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_CHARTER_NOT_ADOPTED": 409,
    "ERR_CHARTER_SEATS_INSUFFICIENT": 409,
    "ERR_VOTING_SEATS_EXCEEDED": 409,
    "ERR_SEAT_NOT_VACANT": 409,
    "ERR_SEAT_NOT_ACTIVE": 409,
    "ERR_TERM_NOT_IN_EFFECT": 409,
    "ERR_ACCEPTANCE_ALREADY_SIGNED": 409,
    "ERR_FIDUCIARY_ACCEPTANCE_MISSING": 409,
    "ERR_TRAINING_NOT_CURRENT": 409,
    "ERR_MEETING_NOT_IN_SESSION": 409,
    "ERR_MEETING_IN_SESSION": 409,
    "ERR_CHAIR_NOT_PRESENT": 409,
    "ERR_OPEN_MOTION_VOTE_LOCK": 409,
    "ERR_REVIEW_NOT_SCORING": 409,
    "ERR_REVIEW_MEETING_MISSING": 409,
    "ERR_REVIEW_DECISIONS_EXECUTED": 409,
    "ERR_FUND_NOT_CANDIDATE": 409,
    "ERR_SLOT_NOT_REPLACEABLE": 409,
    "ERR_SLOT_HAS_OPEN_PROPOSAL": 409,
    "ERR_NOTICE_ALREADY_ISSUED": 409,
    "ERR_BENCHMARK_ALREADY_CURRENT": 409,
    "ERR_RECORDKEEPER_REQUIRED": 409,
    "ERR_ENGAGEMENT_HAS_PENDING_MAPPING": 409,
    "ERR_QDIA_SLOT_REQUIRED": 409,
    "ERR_STALE_PLAN_VERSION": 412,
    "ERR_STALE_REVIEW_VERSION": 412,
    "ERR_MENU_FROZEN": 409,
    "ERR_QUORUM_NOT_MET": 409,
    "ERR_NO_ELIGIBLE_VOTERS": 422,
    "ERR_RECUSAL_REQUIRED": 409,
    "ERR_MOTION_NOT_CARRIED": 409,
    "ERR_MINUTES_NOT_APPROVED": 409,
    "ERR_NO_ADOPTED_IPS": 409,
    "ERR_IPS_VERSION_STALE": 409,
    "ERR_FUND_FAILS_IPS_CRITERIA": 422,
    "ERR_ROLLING_WINDOW_UNAVAILABLE": 422,
    "ERR_SCORECARD_COVERAGE_INCOMPLETE": 422,
    "ERR_NO_SCORECARDS": 422,
    "ERR_MODULE_NOT_WAIVABLE": 422,
    "ERR_TRAINING_SCORE_INSUFFICIENT": 422,
    "ERR_SHARE_CLASS_INELIGIBLE": 422,
    "ERR_NO_ELIGIBLE_TARGET_DATE_SUITE": 422,
    "ERR_DUPLICATE_RESOURCE": 409,
    "ERR_SEAT_TERM_OVERLAP": 409,
    "ERR_ENGAGEMENT_TERM_OVERLAP": 409,
    "ERR_NOTICE_PERIOD_NOT_ELAPSED": 409,
    "ERR_BLACKOUT_WINDOW_CONFLICT": 409,
    "ERR_UNWIND_WINDOW_CLOSED": 409,
    "ERR_QUARTER_CLOSED": 409,
    "ERR_REOPEN_LIMIT_REACHED": 409,
    "ERR_REVISION_LIMIT_REACHED": 409,
    "ERR_MENU_CAPACITY_EXHAUSTED": 409,
    "ERR_CREDIT_POOL_INSUFFICIENT": 409,
    "ERR_ALLOCATION_NOT_BALANCED": 422,
    "ERR_FEE_DISCLOSURE_RESTATEMENT_REQUIRED": 409,
    "ERR_NO_PARTICIPANT_ACCOUNTS": 422,
    "ERR_NO_PLAN_ASSETS": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# --------------------------------------------------------------------------- #
# In-memory store
# --------------------------------------------------------------------------- #

COLLECTIONS = (
    "plans", "seats", "members", "training", "ips", "slots", "funds",
    "reviews", "scorecards", "meetings", "motions", "proposals", "runs",
    "engagements",
)


class Store(object):
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


# --------------------------------------------------------------------------- #
# Logical clock
# --------------------------------------------------------------------------- #

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock(object):
    def __init__(self):
        self.now = DEFAULT_CLOCK

    def set(self, dt):
        self.now = dt

    def iso(self):
        return fmt_dt(self.now)

    def date(self):
        return self.now.date()


clock = Clock()


def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000)


_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$")
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_dt(value, field="value"):
    """Parse an ISO 8601 instant. Returns a timezone-aware UTC datetime."""
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 instant" % field)
    text = value.strip()
    m = _DT_RE.match(text)
    if not m:
        if _DATE_RE.match(text):
            try:
                d = datetime(int(text[0:4]), int(text[5:7]), int(text[8:10]),
                             tzinfo=timezone.utc)
            except ValueError:
                fail("ERR_INVALID_REQUEST", "%s is not a valid date" % field)
            return d
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 instant" % field)
    frac = m.group(7) or ".0"
    micro = int(round(float(frac) * 1000000))
    tz = m.group(8)
    try:
        base = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                        int(m.group(4)), int(m.group(5)), int(m.group(6)),
                        min(micro, 999999), tzinfo=timezone.utc)
    except ValueError:
        fail("ERR_INVALID_REQUEST", "%s is not a valid instant" % field)
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        tz = tz[1:].replace(":", "")
        offset = timedelta(hours=int(tz[0:2]), minutes=int(tz[2:4]))
        base = base - sign * offset
    return base


def parse_date(value, field="value"):
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 date" % field)
    text = value.strip()
    try:
        return datetime(int(text[0:4]), int(text[5:7]), int(text[8:10]),
                        tzinfo=timezone.utc).date()
    except ValueError:
        fail("ERR_INVALID_REQUEST", "%s is not a valid date" % field)


# --------------------------------------------------------------------------- #
# Decimal helpers
# --------------------------------------------------------------------------- #

Q2 = Decimal("0.01")
Q4 = Decimal("0.0001")
Q0 = Decimal("1")


def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def r2(value):
    return D(value).quantize(Q2, rounding=ROUND_HALF_UP)


def r4(value):
    return D(value).quantize(Q4, rounding=ROUND_HALF_UP)


def r0(value):
    return int(D(value).quantize(Q0, rounding=ROUND_HALF_UP))


def dfloor(value):
    return int(D(value).to_integral_value(rounding=ROUND_FLOOR))


# --------------------------------------------------------------------------- #
# Response envelope
# --------------------------------------------------------------------------- #

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def meta_base():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_dt(datetime.now(timezone.utc)),
    }


def jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return dict((k, jsonable(v)) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, datetime):
        return fmt_dt(value)
    return value


def ok(data, status=200):
    body = {
        "meta": meta_base(),
        "response_type": "object",
        "data": jsonable(data) if data is not None else {},
    }
    return jsonify(body), status


def ok_list(rows, limit, offset, total):
    meta = meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(rows)) < total
    body = {"meta": meta, "response_type": "array", "data": jsonable(rows)}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# --------------------------------------------------------------------------- #
# Row lifecycle
# --------------------------------------------------------------------------- #

def new_row(extra=None):
    now = clock.iso()
    row = {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    if extra:
        row.update(extra)
    return row


def touch(row):
    row["updated_at"] = clock.iso()
    row["version"] = row.get("version", 1) + 1
    return row


def public(row):
    return dict((k, v) for k, v in row.items() if not k.startswith("_"))


def sort_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# --------------------------------------------------------------------------- #
# Auth / RBAC
# --------------------------------------------------------------------------- #

ROLES = ("PlanSponsorAdmin", "CommitteeChair", "CommitteeMember",
         "InvestmentConsultant", "Recordkeeper", "PlanAuditor")

ALL_ROLES = ROLES
READ_ALL = ROLES


class Actor(object):
    __slots__ = ("user_id", "role", "member", "seat")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role
        self.member = None
        self.seat = None

    @property
    def entity_backed(self):
        return self.role in ("CommitteeChair", "CommitteeMember")


def authenticate(allowed_roles):
    """Priority 10 then priority 20."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or role is None or str(uid).strip() == "" \
            or str(role).strip() == "" or role not in ROLES:
        fail("ERR_MISSING_USER_CONTEXT", "valid user context headers required")
    if allowed_roles is not None and role not in allowed_roles:
        fail("ERR_ROLE_NOT_PERMITTED", "role %s may not call this endpoint" % role)
    return Actor(uid, role)


def resolve_committee_identity(actor):
    """Priority 25, first half: X-User-ID must be a committee member row and a
    chair caller's seat must be a CHAIR seat. Plan scoping is checked later,
    once the request's plan has been resolved."""
    if not actor.entity_backed:
        return
    member = store.members.get(actor.user_id)
    if member is None:
        fail("ERR_ACTOR_NOT_COMMITTEE_MEMBER",
             "X-User-ID does not resolve to a committee member")
    seat = store.seats.get(member.get("seat_id"))
    if seat is None:
        fail("ERR_ACTOR_NOT_COMMITTEE_MEMBER", "member seat is unknown")
    if actor.role == "CommitteeChair" and seat.get("seat_class") != "CHAIR":
        fail("ERR_ACTOR_NOT_COMMITTEE_MEMBER", "acting member does not hold a CHAIR seat")
    actor.member = member
    actor.seat = seat


def require_actor_plan(actor, plan_id):
    """Priority 25, second half."""
    if not actor.entity_backed:
        return
    if actor.seat is None or actor.seat.get("plan_id") != plan_id:
        fail("ERR_ACTOR_NOT_COMMITTEE_MEMBER",
             "acting member's seat does not belong to this plan")


# --------------------------------------------------------------------------- #
# Request body / query helpers
# --------------------------------------------------------------------------- #

def body():
    data = request.get_json(silent=True)
    if data is None:
        if request.data and request.data.strip():
            fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return data


MISSING = object()


def req_field(payload, name):
    if name not in payload or payload[name] is None:
        fail("ERR_INVALID_REQUEST", "%s is required" % name)
    return payload[name]


def opt_field(payload, name, default=None):
    if name not in payload or payload[name] is None:
        return default
    return payload[name]


def as_str(value, name, min_len=None, max_len=None):
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string" % name)
    if min_len is not None and len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "%s must be at least %d characters" % (name, min_len))
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "%s must be at most %d characters" % (name, max_len))
    return value


def as_int(value, name, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and float(value).is_integer():
            value = int(value)
        else:
            fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be <= %s" % (name, maximum))
    return value


def as_bool(value, name):
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean" % name)
    return value


def as_enum(value, name, allowed):
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s" % (name, ", ".join(allowed)))
    return value


def as_dec(value, name, scale, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        fail("ERR_INVALID_REQUEST", "%s must be a number" % name)
    try:
        dec = D(value)
    except (InvalidOperation, ValueError):
        fail("ERR_INVALID_REQUEST", "%s must be a number" % name)
    if dec != dec or dec.is_infinite():
        fail("ERR_INVALID_REQUEST", "%s must be a finite number" % name)
    exp = dec.as_tuple().exponent
    if isinstance(exp, int) and exp < -scale:
        fail("ERR_INVALID_REQUEST",
             "%s must carry at most %d decimal places" % (name, scale))
    if minimum is not None and dec < D(minimum):
        fail("ERR_INVALID_REQUEST", "%s must be >= %s" % (name, minimum))
    if maximum is not None and dec > D(maximum):
        fail("ERR_INVALID_REQUEST", "%s must be <= %s" % (name, maximum))
    return dec.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP)


def as_id(value, name):
    if not isinstance(value, str) or value.strip() == "":
        fail("ERR_RESOURCE_NOT_FOUND", "%s does not resolve" % name)
    return value


# --------------------------------------------------------------------------- #
# Pagination and listing
# --------------------------------------------------------------------------- #

def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def q_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def q_int(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)


def q_bool(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    fail("ERR_INVALID_REQUEST", "%s must be a boolean" % name)


def paginate(rows, secondary=None):
    limit, offset = pagination()
    if secondary is None:
        ordered = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    else:
        ordered = sorted(rows, key=lambda r: (r["created_at"], secondary(r), r["_seq"]))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return [public(r) for r in window], limit, offset, total
