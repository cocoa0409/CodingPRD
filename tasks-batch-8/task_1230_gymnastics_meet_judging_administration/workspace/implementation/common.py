"""Shared infrastructure: in-memory store, logical clock, envelope, auth, validation."""
import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import jsonify, request

# ----------------------------------------------------------------------------
# In-memory store (empty at every boot; no seeding)
# ----------------------------------------------------------------------------


class Store(object):
    def __init__(self):
        self.meets = {}
        self.sessions = {}
        self.squads = {}
        self.gymnasts = {}
        self.entries = {}        # AthleteEntry
        self.coaches = {}
        self.passes = {}         # CoachMeetPass
        self.judges = {}
        self.panels = {}         # JudgePanel
        self.assignments = {}    # PanelAssignment
        self.rotations = {}
        self.blocks = {}         # WarmupBlock
        self.scores = {}
        self.inquiries = {}
        self.awards = {}
        self.tickets = {}        # SpectatorTicket
        self.qual_records = {}   # QualificationRecord


DB = Store()

# ----------------------------------------------------------------------------
# Logical clock (startup default 2026-05-01T00:00:00Z; never wall-clock)
# ----------------------------------------------------------------------------

CLOCK = {"now": datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)}


def now():
    return CLOCK["now"]


def set_clock(dt):
    CLOCK["now"] = dt


def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value, field):
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "%s must be an ISO 8601 timestamp string" % field)
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "%s is not a valid ISO 8601 timestamp" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ----------------------------------------------------------------------------
# Errors and response envelope
# ----------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super(Exception, self).__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def ok_object(data, code=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": iso(now()),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), code


def ok_array(items, code=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": iso(now()),
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), code


def ok_list(items, code=200):
    """List endpoint response with pagination fields in meta."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": iso(now()),
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": has_more,
        },
        "response_type": "array",
        "data": page,
    }
    return jsonify(body), code


def error_body(error_id, message):
    return {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": iso(now()),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# ----------------------------------------------------------------------------
# Entity helpers
# ----------------------------------------------------------------------------

_SEQ = {"n": 0}


def new_entity():
    _SEQ["n"] += 1
    t = now()
    return {
        "id": str(uuid.uuid4()),
        "created_at": t,
        "updated_at": t,
        "version": 1,
        "_seq": _SEQ["n"],
    }


def touch(entity):
    entity["updated_at"] = now()
    entity["version"] += 1


def sort_items(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def get_or_404(table, entity_id, label="Resource"):
    ent = table.get(entity_id)
    if ent is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", 404,
                       "%s %s does not exist" % (label, entity_id))
    return ent


def fk_or_404(table, entity_id, field):
    ent = table.get(entity_id)
    if ent is None:
        raise ApiError("ERR_FK_NOT_FOUND", 404,
                       "Referenced %s %s does not exist" % (field, entity_id))
    return ent


# ----------------------------------------------------------------------------
# Auth (X-User-ID / X-User-Role)
# ----------------------------------------------------------------------------

ROLES = {
    "MeetDirector", "MeetReferee", "JudgePanelChief",
    "Coach", "GateAttendant", "Spectator",
}


def authorize(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "Missing or malformed X-User-ID / X-User-Role headers")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED_ROLE", 403,
                       "Role %s is not permitted to invoke this endpoint" % role)
    return uid, role


# ----------------------------------------------------------------------------
# Request body / field validation
# ----------------------------------------------------------------------------


def body():
    data = request.get_json(silent=True)
    if data is None:
        if request.data:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "Request body must be valid JSON")
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Request body must be a JSON object")
    return data


def required(data, field):
    if field not in data or data[field] is None:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Missing required field: %s" % field)
    return data[field]


def opt(data, field, default=None):
    v = data.get(field, default)
    return default if v is None else v


def req_str(data, field):
    v = required(data, field)
    if not isinstance(v, str) or not v:
        raise ApiError("ERR_INVALID_REQUEST", 400, "%s must be a non-empty string" % field)
    return v


def req_int(data, field):
    v = required(data, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, "%s must be an integer" % field)
    return v


def opt_int(data, field, default):
    v = data.get(field, default)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, "%s must be an integer" % field)
    return v


def enum_val(v, allowed, field):
    if not isinstance(v, str) or v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "%s must be one of %s" % (field, sorted(allowed)))
    return v


def req_enum(data, field, allowed):
    return enum_val(required(data, field), allowed, field)


def opt_enum(data, field, allowed, default):
    v = data.get(field, default)
    if v is None:
        return default
    return enum_val(v, allowed, field)


THREE_DP = Decimal("0.001")


def q3(d):
    return d.quantize(THREE_DP, rounding=ROUND_HALF_UP)


def score_field(v, lo, hi, field):
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise ApiError("ERR_INVALID_REQUEST", 400, "%s must be a number" % field)
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        raise ApiError("ERR_INVALID_REQUEST", 400, "%s must be a number" % field)
    if d.is_nan() or d.is_infinite():
        raise ApiError("ERR_INVALID_REQUEST", 400, "%s must be a finite number" % field)
    if -d.as_tuple().exponent > 3:
        raise ApiError("ERR_SCORE_FIELD_RANGE", 422,
                       "%s must have at most 3 decimal places" % field)
    if d < Decimal(str(lo)) or d > Decimal(str(hi)):
        raise ApiError("ERR_SCORE_FIELD_RANGE", 422,
                       "%s must be within [%s, %s]" % (field, lo, hi))
    return d


def delta_field(v, lo, hi, field):
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise ApiError("ERR_INVALID_REQUEST", 400, "%s must be a number" % field)
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        raise ApiError("ERR_INVALID_REQUEST", 400, "%s must be a number" % field)
    if d.is_nan() or d.is_infinite():
        raise ApiError("ERR_INVALID_REQUEST", 400, "%s must be a finite number" % field)
    if -d.as_tuple().exponent > 3 or d < Decimal(str(lo)) or d > Decimal(str(hi)):
        raise ApiError("ERR_INQUIRY_DELTA_RANGE", 422,
                       "%s must be within [%s, %s] with at most 3 decimal places"
                       % (field, lo, hi))
    return d


def dec_out(d):
    if d is None:
        return None
    return float(d)


# ----------------------------------------------------------------------------
# Filters
# ----------------------------------------------------------------------------


def apply_filters(items, mapping):
    """mapping: query param -> ('str'|'int', stored_field)."""
    out = list(items)
    for qp, (kind, field) in mapping.items():
        raw = request.args.get(qp)
        if raw is None:
            continue
        if kind == "int":
            try:
                val = int(raw)
            except (TypeError, ValueError):
                raise ApiError("ERR_INVALID_REQUEST", 400,
                               "%s filter must be an integer" % qp)
        else:
            val = raw
        out = [e for e in out if e.get(field) == val]
    return out


# ----------------------------------------------------------------------------
# Domain constants
# ----------------------------------------------------------------------------

APPARATUS = {"VAULT", "UNEVEN_BARS", "BALANCE_BEAM", "FLOOR_EXERCISE"}
LEVEL_BANDS = ["L2", "L3", "L4", "L5", "L6", "L7", "L8", "L9", "L10",
               "XCEL_BRONZE", "XCEL_SILVER", "XCEL_GOLD", "XCEL_PLATINUM",
               "XCEL_DIAMOND"]
LEVEL_BAND_SET = set(LEVEL_BANDS)
COMPULSORY_LEVELS = {"L2", "L3", "L4", "L5"}
RATINGS = {"BREVET", "NATIONAL", "USA", "LEVEL_10", "LEVEL_9", "LEVEL_8",
           "LEVEL_7", "LEVEL_4_5", "XCEL"}
RATING_TIERS = {"BREVET": 8, "NATIONAL": 7, "USA": 6, "LEVEL_10": 5,
                "LEVEL_9": 4, "LEVEL_8": 3, "LEVEL_7": 2, "LEVEL_4_5": 1,
                "XCEL": 0}
BAND_TIERS = {"L10": 5, "L9": 4, "L8": 3, "L7": 2, "L6": 2, "L5": 1, "L4": 1,
              "L3": 1, "L2": 1, "XCEL_BRONZE": 0, "XCEL_SILVER": 0,
              "XCEL_GOLD": 0, "XCEL_PLATINUM": 0, "XCEL_DIAMOND": 0}
PANEL_ROLES = {"PANEL_CHIEF", "D_JUDGE", "E_JUDGE", "LINE_JUDGE", "TIMER"}
SCRATCH_REASONS = {"INJURY", "COACH_DECISION", "NO_SHOW", "DISQUALIFICATION"}
SUSPENSION_REASONS = {"CREDENTIAL_LAPSE", "CONDUCT", "SAFE_SPORT_HOLD"}
RESOLUTIONS = {"D_RAISED", "D_UNCHANGED", "E_ADJUSTED", "DEDUCTION_REMOVED",
               "NO_CHANGE"}
TICKET_CLASSES = {"GENERAL_ADMISSION", "RESERVED", "VIP", "COMP"}
AWARD_CATEGORIES = ["VAULT", "UNEVEN_BARS", "BALANCE_BEAM", "FLOOR_EXERCISE",
                    "ALL_AROUND"]
CATEGORY_INDEX = {"VAULT": 0, "UNEVEN_BARS": 1, "BALANCE_BEAM": 2,
                  "FLOOR_EXERCISE": 3, "ALL_AROUND": 4}
TARGET_MEET_LEVELS = {"STATE", "REGIONAL", "NATIONAL"}
PER_ATHLETE_SECONDS = {"VAULT": 30, "UNEVEN_BARS": 90, "BALANCE_BEAM": 120,
                       "FLOOR_EXERCISE": 90}

RE_SANCTION = re.compile(r"^USAG-[0-9]{4}-[0-9]{4}$")
RE_GYMNAST = re.compile(r"^A[0-9]{7}$")
RE_COACH = re.compile(r"^C[0-9]{7}$")
RE_JUDGE = re.compile(r"^J[0-9]{7}$")


def level_compatible(gymnast_level, band):
    if gymnast_level in COMPULSORY_LEVELS:
        return gymnast_level == band
    return abs(LEVEL_BANDS.index(gymnast_level) - LEVEL_BANDS.index(band)) <= 1


# ----------------------------------------------------------------------------
# Graph traversal helpers
# ----------------------------------------------------------------------------


def meet_of_session(session):
    return DB.meets.get(session["meet_id"])


def meet_of_entry(entry):
    session = DB.sessions.get(entry["session_id"])
    return DB.meets.get(session["meet_id"]) if session else None


def session_of_entry(entry):
    return DB.sessions.get(entry["session_id"])


def meet_of_score(score):
    entry = DB.entries.get(score["athlete_entry_id"])
    return meet_of_entry(entry) if entry else None


def session_gyms(session_id):
    gyms = set()
    for e in DB.entries.values():
        if e["session_id"] == session_id and e["entry_status"] != "SCRATCHED":
            g = DB.gymnasts.get(e["gymnast_id"])
            if g is not None:
                gyms.add(g["home_gym"])
    return gyms


def athlete_count(squad_id):
    n = 0
    for e in DB.entries.values():
        if e.get("squad_id") == squad_id and e["entry_status"] in (
                "REGISTERED", "CHECKED_IN"):
            n += 1
    return n
