"""Core infrastructure: logical clock, in-memory store, envelope, errors, auth."""
import random
import re
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
_CLOCK = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}


def now():
    return _CLOCK["now"]


def set_now(dt):
    _CLOCK["now"] = dt.astimezone(timezone.utc)


def today():
    return _CLOCK["now"].date()


# ---------------------------------------------------------------------------
# In-memory store (empty at boot; never seeded)
# ---------------------------------------------------------------------------
db = {
    "applications": {},
    "volunteers": {},
    "clearances": {},
    "departments": {},
    "roles": {},
    "requests": {},
    "placements": {},
    "training": {},
    "shifts": {},
    "assignments": {},
    "hours": {},
    "badges": {},
    "campaigns": {},
    "items": {},
    "sales": {},
    "events": {},
}

_SEQ = {"n": 0}
_BADGE_SEQ = {"n": 0}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def mint_badge_number():
    _BADGE_SEQ["n"] += 1
    return "BDG-" + str(_BADGE_SEQ["n"]).zfill(6)


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def iso_z(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_datetime(s):
    """Parse an ISO 8601 datetime into an aware UTC datetime, or None."""
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if txt.endswith(("Z", "z")):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(s):
    if not isinstance(s, str) or not _DATE_RE.match(s.strip()):
        return None
    try:
        return date.fromisoformat(s.strip())
    except ValueError:
        return None


def add_months(dt, months):
    """Calendar-month arithmetic on UTC datetimes, clamping the day."""
    y = dt.year + (dt.month - 1 + months) // 12
    m = (dt.month - 1 + months) % 12 + 1
    # clamp day to end of month
    if m == 12:
        first_next = datetime(y + 1, 1, 1, tzinfo=timezone.utc)
    else:
        first_next = datetime(y, m + 1, 1, tzinfo=timezone.utc)
    last_day = (first_next - timedelta(days=1)).day
    d = min(dt.day, last_day)
    return dt.replace(year=y, month=m, day=d)


def add_years_dt(dt, years):
    return add_months(dt, 12 * years)


def add_years_date(d, years):
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        # Feb 29 -> Feb 28
        return d.replace(year=d.year + years, day=28)


def age_on(dob, d):
    """Whole years between dob and d; birthday on d counts as reached."""
    return d.year - dob.year - ((d.month, d.day) < (dob.month, dob.day))


# ---------------------------------------------------------------------------
# Errors and envelope
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta():
    return {
        "api_request_id": _req_id(),
        "api_request_timestamp": iso_z(datetime.now(timezone.utc)),
    }


def ok_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_list(items, total_count, limit, offset, code=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), code


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def fail(error_id, http_status, message):
    raise ApiError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# Error ids (from scaffold §1.6)
# ---------------------------------------------------------------------------
ERR_MISSING_HEADERS = ("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_UNAUTHORIZED_ROLE = ("ERR_UNAUTHORIZED_ROLE", 403)
ERR_NOT_RESOURCE_OWNER = ("ERR_NOT_RESOURCE_OWNER", 403)
ERR_SOD_CLEARANCE = ("ERR_SOD_CLEARANCE_ADJUDICATION", 403)
ERR_SOD_DISBURSEMENT = ("ERR_SOD_CAMPAIGN_DISBURSEMENT", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_APPLICATION_NOT_ACTIONABLE = ("ERR_APPLICATION_NOT_ACTIONABLE", 409)
ERR_VOLUNTEER_INVALID_STATE = ("ERR_VOLUNTEER_INVALID_STATE", 409)
ERR_POSTURE_FROZEN = ("ERR_POSTURE_FROZEN", 409)
ERR_POSTURE_NOT_CLEAR = ("ERR_POSTURE_NOT_CLEAR", 409)
ERR_CLEARANCE_INVALID_STATE = ("ERR_CLEARANCE_INVALID_STATE", 409)
ERR_REQUEST_INVALID_STATE = ("ERR_REQUEST_INVALID_STATE", 409)
ERR_REQUEST_NOT_OPEN = ("ERR_REQUEST_NOT_OPEN", 409)
ERR_PLACEMENT_INVALID_STATE = ("ERR_PLACEMENT_INVALID_STATE", 409)
ERR_SHIFT_INVALID_STATE = ("ERR_SHIFT_INVALID_STATE", 409)
ERR_ASSIGNMENT_INVALID_STATE = ("ERR_ASSIGNMENT_INVALID_STATE", 409)
ERR_HOUR_ENTRY_INVALID_STATE = ("ERR_HOUR_ENTRY_INVALID_STATE", 409)
ERR_TRAINING_RECORD_INVALID_STATE = ("ERR_TRAINING_RECORD_INVALID_STATE", 409)
ERR_BADGE_INVALID_STATE = ("ERR_BADGE_INVALID_STATE", 409)
ERR_CAMPAIGN_INVALID_STATE = ("ERR_CAMPAIGN_INVALID_STATE", 409)
ERR_SALE_ALREADY_VOIDED = ("ERR_SALE_ALREADY_VOIDED", 409)
ERR_ROLE_MIN_AGE_NOT_MET = ("ERR_ROLE_MIN_AGE_NOT_MET", 422)
ERR_DEPARTMENT_JUNIOR_RESTRICTED = ("ERR_DEPARTMENT_JUNIOR_RESTRICTED", 422)
ERR_JUNIOR_WEEKLY_CAP = ("ERR_JUNIOR_WEEKLY_HOUR_CAP_EXCEEDED", 422)
ERR_SUPERVISION_REQUIRED = ("ERR_SUPERVISION_REQUIRED", 422)
ERR_SUPERVISOR_INELIGIBLE = ("ERR_SUPERVISOR_INELIGIBLE", 422)
ERR_SUPERVISOR_RATIO_EXCEEDED = ("ERR_SUPERVISOR_RATIO_EXCEEDED", 422)
ERR_TRAINING_REQUIREMENT_UNMET = ("ERR_TRAINING_REQUIREMENT_UNMET", 422)
ERR_ORIENTATION_INCOMPLETE = ("ERR_ORIENTATION_INCOMPLETE", 422)
ERR_CLEARANCE_REQUIREMENTS_UNMET = ("ERR_CLEARANCE_REQUIREMENTS_UNMET", 422)
ERR_NO_ACCEPTED_PLACEMENT = ("ERR_NO_ACCEPTED_PLACEMENT", 409)
ERR_DUPLICATE_ACTIVE_CLEARANCE = ("ERR_DUPLICATE_ACTIVE_CLEARANCE", 409)
ERR_DUPLICATE_PLACEMENT = ("ERR_DUPLICATE_PLACEMENT", 409)
ERR_PLACEMENT_LIMIT_EXCEEDED = ("ERR_PLACEMENT_LIMIT_EXCEEDED", 409)
ERR_DUPLICATE_SHIFT_ASSIGNMENT = ("ERR_DUPLICATE_SHIFT_ASSIGNMENT", 409)
ERR_SHIFT_TIME_OVERLAP = ("ERR_SHIFT_TIME_OVERLAP", 409)
ERR_SHIFT_AT_CAPACITY = ("ERR_SHIFT_AT_CAPACITY", 409)
ERR_COUNTER_ROUND_EXHAUSTED = ("ERR_COUNTER_ROUND_EXHAUSTED", 409)
ERR_SHIFT_HAS_ASSIGNMENTS = ("ERR_SHIFT_HAS_ASSIGNMENTS", 409)
ERR_ITEM_INACTIVE = ("ERR_ITEM_INACTIVE", 409)
ERR_HOURS_EXCEED_SHIFT = ("ERR_HOURS_EXCEED_SHIFT", 422)
ERR_SIGNUP_WINDOW_CLOSED = ("ERR_SIGNUP_WINDOW_CLOSED", 409)
ERR_CANCEL_WINDOW_CLOSED = ("ERR_CANCEL_WINDOW_CLOSED", 409)
ERR_SHIFT_NOT_ENDED = ("ERR_SHIFT_NOT_ENDED", 409)
ERR_VOID_WINDOW_ELAPSED = ("ERR_VOID_WINDOW_ELAPSED", 409)
ERR_CAMPAIGN_WINDOW_MISMATCH = ("ERR_CAMPAIGN_WINDOW_MISMATCH", 422)
ERR_DISBURSEMENT_COOLING_OFF = ("ERR_DISBURSEMENT_COOLING_OFF", 409)
ERR_SERVICE_DATE_OUT_OF_RANGE = ("ERR_SERVICE_DATE_OUT_OF_RANGE", 422)
ERR_ASSIGNMENT_OWNERSHIP_MISMATCH = ("ERR_ASSIGNMENT_OWNERSHIP_MISMATCH", 422)
ERR_CASHIER_NOT_GIFT_SHOP_PLACED = ("ERR_CASHIER_NOT_GIFT_SHOP_PLACED", 422)
ERR_INSUFFICIENT_STOCK = ("ERR_INSUFFICIENT_STOCK", 409)
ERR_INSUFFICIENT_TENDER = ("ERR_INSUFFICIENT_TENDER", 402)
ERR_DISBURSEMENT_EXCEEDS_BALANCE = ("ERR_DISBURSEMENT_EXCEEDS_BALANCE", 402)


def raise_err(t, message):
    raise ApiError(t[0], t[1], message)


# ---------------------------------------------------------------------------
# Auth (tier 1) and role (tier 3)
# ---------------------------------------------------------------------------
def auth():
    uid = request.headers.get("X-User-ID", "")
    role = request.headers.get("X-User-Role", "")
    uid = uid.strip() if isinstance(uid, str) else ""
    role = role.strip() if isinstance(role, str) else ""
    if not uid or not role:
        raise_err(ERR_MISSING_HEADERS, "X-User-ID and X-User-Role headers are required")
    return uid, role


def require_role(role, roles):
    if role not in roles:
        raise_err(ERR_UNAUTHORIZED_ROLE, "Role %s is not authorized for this endpoint" % role)


# ---------------------------------------------------------------------------
# Body parsing and field validation (tier 2)
# ---------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True, force=False)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def _present(data, field):
    return field in data and data[field] is not None


def req_str(data, field, nonempty=False):
    if not _present(data, field) or not isinstance(data[field], str):
        raise_err(ERR_INVALID_REQUEST, "Field '%s' is required and must be a string" % field)
    if nonempty and data[field].strip() == "":
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be non-empty" % field)
    return data[field]


def opt_str(data, field, default=None):
    if not _present(data, field):
        return default
    if not isinstance(data[field], str):
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be a string" % field)
    return data[field]


def req_int(data, field, minimum=None, maximum=None):
    if not _present(data, field) or not isinstance(data[field], int) or isinstance(data[field], bool):
        raise_err(ERR_INVALID_REQUEST, "Field '%s' is required and must be an integer" % field)
    v = data[field]
    if minimum is not None and v < minimum:
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be >= %s" % (field, minimum))
    if maximum is not None and v > maximum:
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be <= %s" % (field, maximum))
    return v


def opt_int(data, field, default=None, minimum=None, maximum=None):
    if not _present(data, field):
        return default
    return req_int(data, field, minimum=minimum, maximum=maximum)


def opt_bool(data, field, default=None):
    if not _present(data, field):
        return default
    if not isinstance(data[field], bool):
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be a boolean" % field)
    return data[field]


def req_enum(data, field, allowed):
    v = req_str(data, field)
    if v not in allowed:
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be one of %s" % (field, sorted(allowed)))
    return v


def req_datetime(data, field):
    raw = req_str(data, field)
    dt = parse_datetime(raw)
    if dt is None:
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be an ISO 8601 datetime" % field)
    return dt


def opt_datetime(data, field, default=None):
    if not _present(data, field):
        return default
    return req_datetime(data, field)


def req_date(data, field):
    raw = req_str(data, field)
    d = parse_date(raw)
    if d is None:
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be an ISO 8601 date (YYYY-MM-DD)" % field)
    return d


def req_version(data, field):
    return req_int(data, field)


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def pagination_params():
    raw_limit = request.args.get("limit", None)
    raw_offset = request.args.get("offset", None)
    limit, offset = 10, 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_err(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def page_list(records, serializer, filters=None):
    """records: iterable of dicts. Sorts by created_at asc (seq tiebreak),
    applies equality filters, paginates, and returns the list response."""
    limit, offset = pagination_params()
    rows = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    if filters:
        for key, val in filters.items():
            if val is None:
                continue
            rows = [r for r in rows if r.get(key) == val]
    total = len(rows)
    page = rows[offset:offset + limit]
    return ok_list([serializer(r) for r in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Existence helper (tier 4)
# ---------------------------------------------------------------------------
def get_or_404(collection, rid, label="Resource"):
    rec = db[collection].get(rid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "%s %s not found" % (label, rid))
    return rec


def touch(rec):
    rec["updated_at"] = now()
    rec["version"] += 1


def new_rec():
    ts = now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
