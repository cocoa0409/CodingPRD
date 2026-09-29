"""Core infrastructure: in-memory store, logical clock, errors, envelope, auth,
request-shape validators and rounding helpers.

Storage is process-memory only.  The store starts completely empty on every
boot: nothing is seeded, preloaded or hardcoded.
"""
import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from flask import g, jsonify, request

# --------------------------------------------------------------------------
# Constants (scaffold constants_global / PRD narrative)
# --------------------------------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"
OVERTIME_MULTIPLIER = Decimal("1.5")
MAX_REWORK = 2
RUSH_SLA_FACTOR = Decimal("0.5")
COLOR_CONSISTENCY_DRIFT_MAX = Decimal("0.75")
VENDOR_HOLD_STRIKES = 3
AT_RISK_SLA_FRACTION = Decimal("0.8")
SECONDS_PER_DAY = 86400

ROLES = [
    "StudioAdmin", "SampleCoordinator", "Producer", "Photographer",
    "Retoucher", "QCReviewer", "ContentOps",
]

CATEGORIES = ["APPAREL_TOP", "APPAREL_BOTTOM", "FOOTWEAR", "ACCESSORY", "HOME"]
ANGLE_CODES = ["FRONT", "BACK", "SIDE", "FLAT", "DETAIL", "VIDEO_360"]
ASSET_KINDS = ["STILL_ANGLE", "DETAIL", "ON_MODEL", "VIDEO"]
STATION_TYPES = ["MODEL", "MANNEQUIN", "STILL_LIFE"]
TALENT_TYPES = ["MODEL", "STYLIST", "PHOTOGRAPHER", "RETOUCHER"]
PROVIDER_KINDS = ["IN_HOUSE", "OUTSOURCED"]
USAGE_SCOPES = ["ECOM_ONLY", "ECOM_PLUS_SOCIAL", "FULL_BUYOUT"]
TERRITORIES = ["US", "GLOBAL"]
PRIORITY_TIERS = ["A", "B", "C"]
ROLE_ON_SET = ["MODEL", "STYLIST", "PHOTOGRAPHER"]

CUSTODY_STATES = ["EXPECTED", "RECEIVED", "IN_STUDIO", "ON_SET",
                  "RETURN_PENDING", "RETURNED", "LOST"]
MATCH_STATES = ["UNMATCHED", "MATCHED", "MISMATCH_HOLD"]
CONTENT_STATES = ["NOT_STARTED", "SAMPLE_READY", "SCHEDULED", "SHOT",
                  "IN_POST", "DELIVERED", "BLOCKED"]
DOC_STATES = ["PENDING", "SIGNED", "EXPIRED"]
SESSION_STATES = ["BOOKED", "LOCKED", "SHOOTING", "WRAPPED", "CANCELLED"]
BOOKING_STATES = ["HELD", "CONFIRMED", "RELEASED", "CANCELLED"]
ITEM_STATES = ["PLANNED", "ASSIGNED", "CAPTURED", "BLOCKED", "WAIVED"]
ASSET_STATES = ["INGESTED", "IN_RETOUCH", "QC_PENDING", "APPROVED",
                "REJECTED", "DELIVERED"]
TASK_STATES = ["QUEUED", "IN_PROGRESS", "SUBMITTED", "REWORK",
               "APPROVED", "ABANDONED"]
SLA_STATES = ["IN_SLA", "AT_RISK", "BREACHED"]

SCOPE_RANK = {"ECOM_ONLY": 1, "ECOM_PLUS_SOCIAL": 2, "FULL_BUYOUT": 3}
TIER_WEIGHT = {"A": Decimal(100), "B": Decimal(60), "C": Decimal(30)}


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_STYLE_NOT_FOUND": 404,
    "ERR_SAMPLE_NOT_FOUND": 404,
    "ERR_SESSION_NOT_FOUND": 404,
    "ERR_BOOKING_NOT_FOUND": 404,
    "ERR_SHOT_ITEM_NOT_FOUND": 404,
    "ERR_ASSET_NOT_FOUND": 404,
    "ERR_RETOUCH_TASK_NOT_FOUND": 404,
    "ERR_NOT_BOOKED_ON_SESSION": 403,
    "ERR_TASK_NOT_ASSIGNED_TO_ACTOR": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_TALENT_TYPE_MISMATCH": 422,
    "ERR_SAMPLE_INVALID_CUSTODY": 409,
    "ERR_SESSION_NOT_BOOKED": 409,
    "ERR_SESSION_NOT_LOCKED": 409,
    "ERR_SESSION_NOT_SHOOTING": 409,
    "ERR_SESSION_TERMINAL": 409,
    "ERR_BOOKING_INVALID_STATE": 409,
    "ERR_SHOT_ITEM_NOT_ASSIGNABLE": 409,
    "ERR_RETOUCH_TASK_INVALID_STATE": 409,
    "ERR_ASSET_NOT_APPROVED": 409,
    "ERR_RELEASE_INVALID_STATE": 409,
    "ERR_COLOR_ALREADY_MEASURED": 409,
    "ERR_STALE_SESSION_VERSION": 412,
    "ERR_STALE_STYLE_VERSION": 412,
    "ERR_STATION_CALIBRATION_EXPIRED": 409,
    "ERR_COLOR_CHECK_FAILED": 409,
    "ERR_COLOR_CONSISTENCY_DRIFT": 422,
    "ERR_VENDOR_COORDINATION_HOLD": 409,
    "ERR_DUPLICATE_STYLE_NUMBER": 409,
    "ERR_DUPLICATE_CODE": 409,
    "ERR_DUPLICATE_SHOT_ITEM": 409,
    "ERR_CATEGORY_PROFILE_MISMATCH": 422,
    "ERR_INVALID_BASE_STYLE": 422,
    "ERR_INVALID_TIME_WINDOW": 422,
    "ERR_STATION_OVERLAP": 409,
    "ERR_TALENT_OVERLAP": 409,
    "ERR_STATION_TYPE_MISMATCH": 422,
    "ERR_STYLE_NUMBER_MISMATCH": 409,
    "ERR_SAMPLE_NOT_MATCHED": 409,
    "ERR_SAMPLE_NOT_IN_STUDIO": 409,
    "ERR_RELEASE_NOT_ON_FILE": 422,
    "ERR_RELEASE_SCOPE_INSUFFICIENT": 422,
    "ERR_ASSET_NAMING_VIOLATION": 422,
    "ERR_ASSET_METADATA_INCOMPLETE": 422,
    "ERR_RETOUCH_TASK_EXISTS": 409,
    "ERR_SHOT_LIST_EMPTY": 409,
    "ERR_STATION_CAPACITY_EXCEEDED": 409,
    "ERR_SESSION_BUDGET_EXCEEDED": 409,
    "ERR_NO_CLAIMABLE_TASK": 409,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers missing or role unrecognised.",
    "ERR_FORBIDDEN_ROLE": "This role may not call this endpoint.",
    "ERR_INVALID_REQUEST": "Request body or query parameters are malformed.",
    "ERR_REFERENCE_NOT_FOUND": "A referenced configuration record does not exist.",
    "ERR_STYLE_NOT_FOUND": "Style not found.",
    "ERR_SAMPLE_NOT_FOUND": "Sample not found.",
    "ERR_SESSION_NOT_FOUND": "Shoot session not found.",
    "ERR_BOOKING_NOT_FOUND": "Talent booking not found.",
    "ERR_SHOT_ITEM_NOT_FOUND": "Shot list item not found.",
    "ERR_ASSET_NOT_FOUND": "Asset not found.",
    "ERR_RETOUCH_TASK_NOT_FOUND": "Retouch task not found.",
    "ERR_NOT_BOOKED_ON_SESSION": "The acting photographer holds no confirmed photographer booking on this session.",
    "ERR_TASK_NOT_ASSIGNED_TO_ACTOR": "Only the assigned retoucher may submit this task.",
    "ERR_SEGREGATION_OF_DUTIES": "The QC reviewer may not review their own retouch work.",
    "ERR_TALENT_TYPE_MISMATCH": "Talent type does not admit this role.",
    "ERR_SAMPLE_INVALID_CUSTODY": "The sample's custody state does not allow this action.",
    "ERR_SESSION_NOT_BOOKED": "The session must be in BOOKED state.",
    "ERR_SESSION_NOT_LOCKED": "The session must be in LOCKED state.",
    "ERR_SESSION_NOT_SHOOTING": "The session must be in SHOOTING state.",
    "ERR_SESSION_TERMINAL": "The session has already reached a terminal state.",
    "ERR_BOOKING_INVALID_STATE": "The booking's state does not allow this action.",
    "ERR_SHOT_ITEM_NOT_ASSIGNABLE": "The shot list item's state does not allow this action.",
    "ERR_RETOUCH_TASK_INVALID_STATE": "The retouch task's state does not allow this action.",
    "ERR_ASSET_NOT_APPROVED": "The asset's state does not allow this action.",
    "ERR_RELEASE_INVALID_STATE": "The release cannot be signed in its current state.",
    "ERR_COLOR_ALREADY_MEASURED": "A colour reading has already been recorded for this session.",
    "ERR_STALE_SESSION_VERSION": "expected_session_version does not match the session's current version.",
    "ERR_STALE_STYLE_VERSION": "expected_style_version does not match the style's current version.",
    "ERR_STATION_CALIBRATION_EXPIRED": "The station's colour calibration has lapsed.",
    "ERR_COLOR_CHECK_FAILED": "The session's on-set colour check failed; capture may not be ingested.",
    "ERR_COLOR_CONSISTENCY_DRIFT": "Colour reading drifts too far from this station's previous passing session.",
    "ERR_VENDOR_COORDINATION_HOLD": "The vendor is on coordination hold; no further sample receipts are accepted.",
    "ERR_DUPLICATE_STYLE_NUMBER": "style_number already exists.",
    "ERR_DUPLICATE_CODE": "A uniquely-constrained code already exists.",
    "ERR_DUPLICATE_SHOT_ITEM": "This style already owes that asset kind at that angle.",
    "ERR_CATEGORY_PROFILE_MISMATCH": "The asset profile governs a different category.",
    "ERR_INVALID_BASE_STYLE": "Colorway parentage is invalid.",
    "ERR_INVALID_TIME_WINDOW": "The supplied interval is not a valid window.",
    "ERR_STATION_OVERLAP": "The station is already occupied for that interval.",
    "ERR_TALENT_OVERLAP": "The talent is already booked for an overlapping interval.",
    "ERR_STATION_TYPE_MISMATCH": "The session's station cannot shoot that asset kind.",
    "ERR_STYLE_NUMBER_MISMATCH": "The sample's declared style number does not match the style.",
    "ERR_SAMPLE_NOT_MATCHED": "The sample must be matched to a style before it can move onto the rack or onto set.",
    "ERR_SAMPLE_NOT_IN_STUDIO": "A matched sample for every scheduled style must be physically in the studio.",
    "ERR_RELEASE_NOT_ON_FILE": "No signed release covers this model's booked window.",
    "ERR_RELEASE_SCOPE_INSUFFICIENT": "The release's usage scope is narrower than the session requires.",
    "ERR_ASSET_NAMING_VIOLATION": "file_name does not match the category's naming pattern.",
    "ERR_ASSET_METADATA_INCOMPLETE": "Required metadata keys are missing or empty.",
    "ERR_RETOUCH_TASK_EXISTS": "This asset already has a live retouch task.",
    "ERR_SHOT_LIST_EMPTY": "The session has no required shot assigned.",
    "ERR_STATION_CAPACITY_EXCEEDED": "The station's daily minute capacity would be exceeded.",
    "ERR_SESSION_BUDGET_EXCEEDED": "Confirming this booking would exceed the session's talent budget.",
    "ERR_NO_CLAIMABLE_TASK": "No queued retouch task is currently claimable.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# --------------------------------------------------------------------------
# Rounding / numeric helpers
# --------------------------------------------------------------------------
def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    return Decimal(str(value))


def round_half_up(value, places=0):
    q = Decimal(1).scaleb(-places)
    return dec(value).quantize(q, rounding=ROUND_HALF_UP)


def cents_half_up(value):
    return int(round_half_up(value, 0))


def floor_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_FLOOR))


def ceil_int(value):
    d = dec(value)
    i = d.to_integral_value(rounding=ROUND_FLOOR)
    return int(i) if d == i else int(i) + 1


def hours_between(start, end):
    """Elapsed hours as an exact Decimal."""
    return dec((end - start).total_seconds()) / Decimal(3600)


def whole_minutes(start, end):
    return int((end - start).total_seconds() // 60)


def num_out(value, places=2):
    """Serialise a Decimal/number to a JSON number with `places` decimals."""
    if value is None:
        return None
    return float(round_half_up(value, places))


# --------------------------------------------------------------------------
# Datetime helpers
# --------------------------------------------------------------------------
_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_dt(value):
    """Parse an ISO-8601 instant.  Returns a timezone-aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    m = _DT_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hh, mm = (int(m.group(i)) for i in range(1, 6))
    ss = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
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
    return base


def parse_date_only(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def iso3(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


# --------------------------------------------------------------------------
# In-memory store + logical clock
# --------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.vendors = {}
        self.asset_profiles = {}
        self.stations = {}
        self.talents = {}
        self.providers = {}
        self.styles = {}
        self.samples = {}
        self.releases = {}
        self.sessions = {}
        self.bookings = {}
        self.items = {}
        self.assets = {}
        self.tasks = {}
        self.seq = 0
        self.clock = parse_dt(DEFAULT_CLOCK_UTC)

    def next_seq(self):
        self.seq += 1
        return self.seq


db = Store()


def now():
    """The current logical clock instant."""
    return db.clock


def new_id():
    return str(uuid.uuid4())


def touch(row):
    """Record a mutation: bump version and refresh updated_at."""
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = now()
    return row


def new_row(extra=None):
    ts = now()
    row = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    if extra:
        row.update(extra)
    return row


def by_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# --------------------------------------------------------------------------
# Response envelope
# --------------------------------------------------------------------------
def _request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _wall_iso3():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def base_meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": _wall_iso3()}


def ok(data, status=200):
    body = {"meta": base_meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(rows, limit, offset, total):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(rows)) < total
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# --------------------------------------------------------------------------
# Auth / RBAC  (PRD 2.1 + 2.7 step 1)
# --------------------------------------------------------------------------
def authorize(*allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not str(uid).strip():
        fail("ERR_UNAUTHENTICATED")
    if role is None or not str(role).strip():
        fail("ERR_UNAUTHENTICATED")
    uid = str(uid).strip()
    role = str(role).strip()
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE")
    g.user_id = uid
    g.role = role
    return uid, role


def actor_id():
    return g.get("user_id")


# --------------------------------------------------------------------------
# Request-shape validators  (PRD 2.7 step 2 -> ERR_INVALID_REQUEST)
# --------------------------------------------------------------------------
_MISSING = object()


def get_body():
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return body


def _present(body, key, required, default):
    if key not in body or body[key] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return False, default
    return True, None


def vstr(body, key, required=True, default=None, minlen=None, maxlen=None,
         pattern=None, strip=False):
    ok_, dflt = _present(body, key, required, default)
    if not ok_:
        return dflt
    value = body[key]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % key)
    if strip:
        value = value.strip()
    if minlen is not None and len(value) < minlen:
        fail("ERR_INVALID_REQUEST", "Field '%s' is too short." % key)
    if maxlen is not None and len(value) > maxlen:
        fail("ERR_INVALID_REQUEST", "Field '%s' is too long." % key)
    if pattern is not None and not re.match(pattern, value):
        fail("ERR_INVALID_REQUEST", "Field '%s' has an invalid format." % key)
    return value


def vint(body, key, required=True, default=None, minimum=None, maximum=None):
    ok_, dflt = _present(body, key, required, default)
    if not ok_:
        return dflt
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' is below its minimum." % key)
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' is above its maximum." % key)
    return value


def vnum(body, key, required=True, default=None, minimum=None, maximum=None):
    ok_, dflt = _present(body, key, required, default)
    if not ok_:
        return dec(dflt) if dflt is not None else None
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % key)
    d = dec(value)
    if minimum is not None and d < dec(minimum):
        fail("ERR_INVALID_REQUEST", "Field '%s' is below its minimum." % key)
    if maximum is not None and d > dec(maximum):
        fail("ERR_INVALID_REQUEST", "Field '%s' is above its maximum." % key)
    return d


def vbool(body, key, required=True, default=None):
    ok_, dflt = _present(body, key, required, default)
    if not ok_:
        return dflt
    value = body[key]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % key)
    return value


def venum(body, key, allowed, required=True, default=None):
    ok_, dflt = _present(body, key, required, default)
    if not ok_:
        return dflt
    value = body[key]
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def vdt(body, key, required=True, default=None):
    ok_, dflt = _present(body, key, required, default)
    if not ok_:
        return dflt
    parsed = parse_dt(body[key])
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO-8601 instant." % key)
    return parsed


def varray(body, key, required=True, default=None, non_empty=True,
           member_enum=None, numeric=False, strings=False):
    ok_, dflt = _present(body, key, required, default)
    if not ok_:
        return dflt
    value = body[key]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an array." % key)
    if non_empty and len(value) == 0:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty array." % key)
    for member in value:
        if member_enum is not None and (not isinstance(member, str) or member not in member_enum):
            fail("ERR_INVALID_REQUEST", "Field '%s' holds an undeclared member." % key)
        if numeric and (isinstance(member, bool) or not isinstance(member, (int, float))):
            fail("ERR_INVALID_REQUEST", "Field '%s' must contain only numbers." % key)
        if strings and not isinstance(member, str):
            fail("ERR_INVALID_REQUEST", "Field '%s' must contain only strings." % key)
    return value


def vobject(body, key, required=True, default=None):
    ok_, dflt = _present(body, key, required, default)
    if not ok_:
        return dflt
    value = body[key]
    if not isinstance(value, dict):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an object." % key)
    return value


# --------------------------------------------------------------------------
# Query-parameter validators (list endpoints, PRD 2.3)
# --------------------------------------------------------------------------
def page_params():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        if raw is None or not re.match(r"^-?\d+$", raw.strip()):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        limit = int(raw.strip())
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        if raw is None or not re.match(r"^-?\d+$", raw.strip()):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        offset = int(raw.strip())
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must be at least 0.")
    return limit, offset


def qstr(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def qenum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s." % (name, ", ".join(allowed)))
    return value


def qbool(name):
    value = request.args.get(name)
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    fail("ERR_INVALID_REQUEST", "%s must be a boolean." % name)


def qdate(name):
    value = request.args.get(name)
    if value is None:
        return None
    parsed = parse_date_only(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be a YYYY-MM-DD date." % name)
    return parsed


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
