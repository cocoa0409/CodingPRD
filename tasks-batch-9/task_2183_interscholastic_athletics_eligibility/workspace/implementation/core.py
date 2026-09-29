"""Core infrastructure: logical clock, in-memory store, envelope, auth, validation."""
import os
import re
import uuid
import random
import string
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, ROUND_HALF_UP

from flask import request, jsonify

UTC = timezone.utc
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

ROLES = [
    "AssociationAdmin",
    "SchoolAthleticDirector",
    "Registrar",
    "EligibilityReviewer",
    "MedicalOfficer",
    "OfficialsCoordinator",
    "Official",
]
ALL_ROLES = list(ROLES)

SPORTS = ["FOOTBALL", "BASKETBALL", "TRACK", "SOCCER"]
CLASSIFICATIONS = ["C1A", "C2A", "C3A", "C4A", "C5A"]
SPORT_TIERS = ["TIER_A", "TIER_B", "TIER_C"]
ROLE_TITLES = ["HEAD_COACH", "ASSISTANT_COACH"]
CERT_LEVELS = ["LEVEL_1", "LEVEL_2", "LEVEL_3"]
DOC_TYPES = ["PHYSICAL", "PARENT_CONSENT", "CONCUSSION_ACK"]
INJURY_TYPES = ["CONCUSSION", "FRACTURE", "SPRAIN", "OTHER"]

SEASON_STATUSES = ["PLANNED", "PRACTICE_OPEN", "REGULAR_SEASON", "SEEDING_LOCKED",
                   "PLAYOFFS", "COMPLETED", "ABANDONED"]

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_SCHOOL_NOT_FOUND": 404,
    "ERR_STUDENT_NOT_FOUND": 404,
    "ERR_SEASON_NOT_FOUND": 404,
    "ERR_CASE_NOT_FOUND": 404,
    "ERR_CONTEST_NOT_FOUND": 404,
    "ERR_OFFICIAL_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_TRANSPORT_REQUEST_NOT_FOUND": 404,
    "ERR_INJURY_REPORT_NOT_FOUND": 404,
    "ERR_CREDENTIAL_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_STALE_SEASON_VERSION": 412,
    "ERR_STALE_CONTEST_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_CASE_NOT_ACTIVATABLE": 409,
    "ERR_APPEAL_LIMIT_REACHED": 409,
    "ERR_ALREADY_RESPONDED": 409,
    "ERR_RTP_STAGE_CEILING": 409,
    "ERR_RTP_STAGE_INCOMPLETE": 409,
    "ERR_CREDENTIAL_ALREADY_LAPSED": 409,
    "ERR_SEASON_HAS_OPEN_CONTESTS": 409,
    "ERR_SEASON_NOT_OPEN": 409,
    "ERR_CONTEST_NOT_STAFFABLE": 409,
    "ERR_CONTEST_NOT_SCHEDULED_FOR_TRANSPORT": 409,
    "ERR_SCHOOL_SANCTIONED": 409,
    "ERR_COACH_NOT_CREDENTIALED": 409,
    "ERR_ACADEMIC_RECORD_MISSING": 409,
    "ERR_ATHLETE_MEDICALLY_SUSPENDED": 409,
    "ERR_CONTEST_OUTSIDE_SEASON_WINDOW": 409,
    "ERR_VENUE_TURNOVER_CONFLICT": 409,
    "ERR_OFFICIAL_DOUBLE_BOOKED": 409,
    "ERR_RTP_INTERVAL_NOT_ELAPSED": 409,
    "ERR_TRANSPORT_DEPARTURE_IN_PAST": 409,
    "ERR_RESULT_BEFORE_TIPOFF": 409,
    "ERR_CONTEST_TIME_IN_PAST": 409,
    "ERR_SAME_SCHOOL_CONTEST": 409,
    "ERR_CLASSIFICATION_MISMATCH": 409,
    "ERR_SEASON_CONTEST_LIMIT": 409,
    "ERR_CONTEST_WINDOW_DENSITY": 409,
    "ERR_BRACKET_TOO_SMALL": 409,
    "ERR_RELEASE_TIME_EXCEEDED": 409,
    "ERR_FLEET_CAPACITY_EXCEEDED": 409,
    "ERR_OFFICIALS_INCOMPLETE": 409,
    "ERR_SEEDING_EMPTY_SNAPSHOT": 409,
    "ERR_SCHOOL_NOT_IN_CONTEST": 409,
    "ERR_DUPLICATE_ELIGIBILITY_CASE": 409,
    "ERR_FEE_OUTSTANDING": 409,
    "ERR_FEE_OVERPAYMENT": 422,
    "ERR_NOTHING_TO_REFUND": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# In-memory store + logical clock
# ---------------------------------------------------------------------------
class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = CLOCK_DEFAULT
        self.seq = 0
        self.schools = {}
        self.students = {}
        self.credentials = {}
        self.seasons = {}
        self.cases = {}
        self.documents = {}
        self.contests = {}
        self.officials = {}
        self.assignments = {}
        self.transports = {}
        self.injuries = {}
        self.seeds = {}


DB = Store()


def now():
    return DB.clock


def now_date():
    return DB.clock.date()


def next_seq():
    DB.seq += 1
    return DB.seq


# ---------------------------------------------------------------------------
# Time / number formatting
# ---------------------------------------------------------------------------
def iso_dt(dt):
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def iso_date(d):
    if d is None:
        return None
    if isinstance(d, str):
        return d
    return d.strftime("%Y-%m-%d")


_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,6}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_dt(value):
    """Parse an ISO 8601 instant. Returns tz-aware UTC datetime or None on failure."""
    if not isinstance(value, str):
        return None
    m = _DT_RE.match(value.strip())
    if not m:
        return None
    y, mo, d, hh, mm, ss, frac, tz = m.groups()
    try:
        micro = 0
        if frac:
            micro = int((frac + "000000")[:6])
        dt = datetime(int(y), int(mo), int(d), int(hh), int(mm),
                      int(ss or 0), micro, tzinfo=UTC)
    except ValueError:
        return None
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        tzs = tz[1:].replace(":", "")
        offset = timedelta(hours=int(tzs[:2]), minutes=int(tzs[2:4]))
        dt = dt - sign * offset
    return dt


def parse_date(value):
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def rhu(value, places=0):
    """Round half up to `places` decimals, returns Decimal."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    q = Decimal(1).scaleb(-places)
    return value.quantize(q, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def to_num(d, places):
    """Render a Decimal as a JSON number carrying `places` decimals."""
    if d is None:
        return None
    return float(rhu(d, places))


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    wall = datetime.now(UTC)
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": wall.strftime("%Y-%m-%dT%H:%M:%S.")
        + "%03dZ" % (wall.microsecond // 1000),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    })
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Auth (validation tiers 1-3)
# ---------------------------------------------------------------------------
class Principal(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-ID and a valid X-User-Role are required")
    return Principal(uid, role)


def auth(allowed_roles):
    """Tier 1 (authentication) then tier 2 (endpoint role list)."""
    p = authenticate()
    if p.role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE", "role %s may not call this endpoint" % p.role)
    return p


def own(principal, expected_id, roles=("SchoolAthleticDirector", "Registrar", "Official")):
    """Tier 3: ownership check for entity-backed roles."""
    if principal.role in roles and expected_id is not None:
        if principal.user_id != expected_id:
            fail("ERR_NOT_RESOURCE_OWNER",
                 "acting principal does not own this resource")


# ---------------------------------------------------------------------------
# Body / query validation helpers
# ---------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return data


def _bad(field, why):
    fail("ERR_INVALID_REQUEST", "%s %s" % (field, why))


def req_str(b, key):
    v = b.get(key)
    if not isinstance(v, str) or v == "":
        _bad(key, "is required and must be a non-empty string")
    return v


def opt_str(b, key, default=None):
    if key not in b or b[key] is None:
        return default
    v = b[key]
    if not isinstance(v, str):
        _bad(key, "must be a string")
    return v


def req_enum(b, key, allowed):
    v = b.get(key)
    if not isinstance(v, str) or v not in allowed:
        _bad(key, "must be one of %s" % ", ".join(allowed))
    return v


def opt_enum(b, key, allowed, default=None):
    if key not in b or b[key] is None:
        return default
    return req_enum(b, key, allowed)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(b, key, minimum=None, maximum=None):
    v = b.get(key)
    if not _is_int(v):
        _bad(key, "is required and must be an integer")
    if minimum is not None and v < minimum:
        _bad(key, "must be >= %s" % minimum)
    if maximum is not None and v > maximum:
        _bad(key, "must be <= %s" % maximum)
    return v


def opt_int(b, key, default=None, minimum=None, maximum=None):
    if key not in b or b[key] is None:
        return default
    return req_int(b, key, minimum, maximum)


def req_num(b, key, minimum=None, maximum=None):
    v = b.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad(key, "is required and must be a number")
    d = dec(v)
    if minimum is not None and d < dec(minimum):
        _bad(key, "must be >= %s" % minimum)
    if maximum is not None and d > dec(maximum):
        _bad(key, "must be <= %s" % maximum)
    return d


def req_bool(b, key):
    v = b.get(key)
    if not isinstance(v, bool):
        _bad(key, "is required and must be a boolean")
    return v


def opt_bool(b, key, default=False):
    if key not in b or b[key] is None:
        return default
    return req_bool(b, key)


def req_date(b, key):
    v = b.get(key)
    d = parse_date(v)
    if d is None:
        _bad(key, "is required and must be an ISO 8601 date (YYYY-MM-DD)")
    return d


def opt_date(b, key, default=None):
    if key not in b or b[key] is None:
        return default
    return req_date(b, key)


def req_instant(b, key):
    v = b.get(key)
    d = parse_dt(v)
    if d is None:
        _bad(key, "is required and must be an ISO 8601 UTC instant")
    return d


def pagination():
    """Tier 7: pagination shape."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_PAGINATION", "limit must be an integer in [1, 100]")
        if str(raw).strip() != str(limit):
            fail("ERR_INVALID_PAGINATION", "limit must be an integer in [1, 100]")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_PAGINATION", "limit must be an integer in [1, 100]")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_PAGINATION", "offset must be an integer >= 0")
        if str(raw).strip() != str(offset):
            fail("ERR_INVALID_PAGINATION", "offset must be an integer >= 0")
        if offset < 0:
            fail("ERR_INVALID_PAGINATION", "offset must be an integer >= 0")
    return limit, offset


def paginate(rows, limit, offset):
    return rows[offset:offset + limit], len(rows)


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------
def new_record(fields, versioned=True):
    rec = dict(fields)
    rec["id"] = str(uuid.uuid4())
    rec["_seq"] = next_seq()
    rec["created_at"] = now()
    if versioned:
        rec["updated_at"] = now()
        rec["version"] = 1
    return rec


def touch(rec):
    rec["updated_at"] = now()
    rec["version"] = rec.get("version", 0) + 1
    return rec


def by_created(rows, reverse=False):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]), reverse=reverse)


def _common(rec, out, versioned=True):
    out["id"] = rec["id"]
    out["created_at"] = iso_dt(rec["created_at"])
    if versioned:
        out["updated_at"] = iso_dt(rec["updated_at"])
        out["version"] = rec["version"]
    return out


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def ser_school(s):
    out = {
        "name": s["name"],
        "classification": s["classification"],
        "region_code": s["region_code"],
        "school_day_end_utc_hhmm": s["school_day_end_utc_hhmm"],
        "bus_fleet_size": s["bus_fleet_size"],
        "max_release_minutes_per_request": s["max_release_minutes_per_request"],
        "fee_cap_cents": s["fee_cap_cents"],
        "venue_concurrent_capacity": s["venue_concurrent_capacity"],
        "sanction_status": s["sanction_status"],
        "forfeit_count": s["forfeit_count"],
        "release_minutes_used": s["release_minutes_used"],
        "fee_collected_cents": s["fee_collected_cents"],
        "credential_gap_sports": list(s["credential_gap_sports"]),
    }
    return _common(s, out)


def ser_student(s):
    out = {
        "school_id": s["school_id"],
        "previous_school_id": s["previous_school_id"],
        "full_name": s["full_name"],
        "birth_date": iso_date(s["birth_date"]),
        "grade_level": s["grade_level"],
        "residency_verified": s["residency_verified"],
        "residency_verified_on": iso_date(s["residency_verified_on"]),
        "transfer_date": iso_date(s["transfer_date"]),
        "hardship_waiver_granted": s["hardship_waiver_granted"],
        "free_reduced_lunch": s["free_reduced_lunch"],
        "gpa_prior_period": to_num(s["gpa_prior_period"], 3) if s["gpa_prior_period"] is not None else None,
        "gpa_current_period": to_num(s["gpa_current_period"], 3) if s["gpa_current_period"] is not None else None,
        "credits_prior_period": s["credits_prior_period"],
        "credits_current_period": s["credits_current_period"],
        "academic_record_submitted_by": s["academic_record_submitted_by"],
        "academic_record_submitted_at": iso_dt(s["academic_record_submitted_at"]),
    }
    return _common(s, out)


def ser_credential(c):
    out = {
        "school_id": c["school_id"],
        "coach_name": c["coach_name"],
        "sport": c["sport"],
        "role_title": c["role_title"],
        "certification_expires_on": iso_date(c["certification_expires_on"]),
        "status": c["status"],
        "background_check_completed_on": iso_date(c["background_check_completed_on"]),
        "background_check_reference": c["background_check_reference"],
    }
    return _common(c, out)


def ser_season(s):
    out = {
        "sport": s["sport"],
        "classification": s["classification"],
        "school_year": s["school_year"],
        "sport_tier": s["sport_tier"],
        "practice_start_date": iso_date(s["practice_start_date"]),
        "first_contest_date": iso_date(s["first_contest_date"]),
        "season_end_date": iso_date(s["season_end_date"]),
        "age_cutoff_date": iso_date(s["age_cutoff_date"]),
        "residency_deadline": iso_date(s["residency_deadline"]),
        "grading_lock_date": iso_date(s["grading_lock_date"]),
        "contest_limit": s["contest_limit"],
        "required_officials": s["required_officials"],
        "status": s["status"],
        "scheduled_contest_count": s["scheduled_contest_count"],
        "seeded_school_count": s["seeded_school_count"],
        "unseeded_school_count": s["unseeded_school_count"],
    }
    return _common(s, out)


def ser_case(c):
    out = {
        "student_id": c["student_id"],
        "sport_season_id": c["sport_season_id"],
        "status": c["status"],
        "fee_status": c["fee_status"],
        "ineligibility_reason": c["ineligibility_reason"],
        "gpa_variant_applied": c["gpa_variant_applied"],
        "effective_gpa": to_num(c["effective_gpa"], 3) if c["effective_gpa"] is not None else None,
        "fee_amount_cents": c["fee_amount_cents"],
        "fee_paid_cents": c["fee_paid_cents"],
        "fee_waived_cents": c["fee_waived_cents"],
        "fee_refunded_cents": c["fee_refunded_cents"],
        "fee_outstanding_cents": c["fee_outstanding_cents"],
        "appeal_count": c["appeal_count"],
        "evaluation_count": c["evaluation_count"],
        "provisional_revoked_at": iso_dt(c["provisional_revoked_at"]),
        "activated_at": iso_dt(c["activated_at"]),
    }
    return _common(c, out)


def ser_document(d):
    out = {
        "eligibility_case_id": d["eligibility_case_id"],
        "doc_type": d["doc_type"],
        "issued_on": iso_date(d["issued_on"]),
        "expires_on": iso_date(d["expires_on"]),
        "signer_name": d["signer_name"],
        "status": "VALID" if d["expires_on"] >= now_date() else "EXPIRED",
    }
    return _common(d, out, versioned=False)


def ser_contest(c):
    out = {
        "sport_season_id": c["sport_season_id"],
        "home_school_id": c["home_school_id"],
        "away_school_id": c["away_school_id"],
        "starts_at": iso_dt(c["starts_at"]),
        "ends_at": iso_dt(c["ends_at"]),
        "travel_miles": float(c["travel_miles"]),
        "is_playoff": c["is_playoff"],
        "status": c["status"],
        "accepted_official_count": c["accepted_official_count"],
        "home_score": c["home_score"],
        "away_score": c["away_score"],
        "forfeiting_school_id": c["forfeiting_school_id"],
        "hold_reason": c["hold_reason"],
        "result_recorded_at": iso_dt(c["result_recorded_at"]),
    }
    return _common(c, out)


def ser_official(o):
    out = {
        "full_name": o["full_name"],
        "certification_level": o["certification_level"],
        "home_region_code": o["home_region_code"],
        "accepted_assignment_count": o["accepted_assignment_count"],
    }
    return _common(o, out)


def ser_assignment(a):
    out = {
        "contest_id": a["contest_id"],
        "official_id": a["official_id"],
        "status": a["status"],
        "stipend_cents": a["stipend_cents"],
        "responded_at": iso_dt(a["responded_at"]),
    }
    return _common(a, out)


def ser_transport(t):
    out = {
        "contest_id": t["contest_id"],
        "requesting_school_id": t["requesting_school_id"],
        "bus_count": t["bus_count"],
        "travel_minutes": t["travel_minutes"],
        "depart_at": iso_dt(t["depart_at"]),
        "return_at": iso_dt(t["return_at"]),
        "release_minutes": t["release_minutes"],
        "status": t["status"],
        "cancelled_reason": t["cancelled_reason"],
    }
    return _common(t, out)


def ser_injury(i):
    out = {
        "student_id": i["student_id"],
        "contest_id": i["contest_id"],
        "injury_type": i["injury_type"],
        "reported_at": iso_dt(i["reported_at"]),
        "reported_by_user_id": i["reported_by_user_id"],
        "status": i["status"],
        "rtp_stage": i["rtp_stage"],
        "last_stage_advanced_at": iso_dt(i["last_stage_advanced_at"]),
        "recurrence_count": i["recurrence_count"],
        "cleared_by_user_id": i["cleared_by_user_id"],
        "cleared_at": iso_dt(i["cleared_at"]),
    }
    return _common(i, out)


def ser_seed(s):
    out = {
        "sport_season_id": s["sport_season_id"],
        "school_id": s["school_id"],
        "wins": s["wins"],
        "losses": s["losses"],
        "forfeit_losses": s["forfeit_losses"],
        "raw_win_pct": to_num(s["raw_win_pct"], 4),
        "opponent_avg_win_pct": to_num(s["opponent_avg_win_pct"], 4),
        "power_rating": to_num(s["power_rating"], 4),
        "seed_number": s["seed_number"],
        "tiebreak_trace": s["tiebreak_trace"],
    }
    return _common(s, out, versioned=False)


# ---------------------------------------------------------------------------
# Lookups (tier 4/5 existence)
# ---------------------------------------------------------------------------
def get_school(sid, err="ERR_SCHOOL_NOT_FOUND"):
    r = DB.schools.get(sid)
    if r is None:
        fail(err, "school %s not found" % sid)
    return r


def get_student(sid, err="ERR_STUDENT_NOT_FOUND"):
    r = DB.students.get(sid)
    if r is None:
        fail(err, "student %s not found" % sid)
    return r


def get_season(sid, err="ERR_SEASON_NOT_FOUND"):
    r = DB.seasons.get(sid)
    if r is None:
        fail(err, "sport season %s not found" % sid)
    return r


def get_case(cid, err="ERR_CASE_NOT_FOUND"):
    r = DB.cases.get(cid)
    if r is None:
        fail(err, "eligibility case %s not found" % cid)
    return r


def get_contest(cid, err="ERR_CONTEST_NOT_FOUND"):
    r = DB.contests.get(cid)
    if r is None:
        fail(err, "contest %s not found" % cid)
    return r


def get_official(oid, err="ERR_OFFICIAL_NOT_FOUND"):
    r = DB.officials.get(oid)
    if r is None:
        fail(err, "official %s not found" % oid)
    return r


def get_assignment(aid, err="ERR_ASSIGNMENT_NOT_FOUND"):
    r = DB.assignments.get(aid)
    if r is None:
        fail(err, "assignment %s not found" % aid)
    return r


def get_transport(tid, err="ERR_TRANSPORT_REQUEST_NOT_FOUND"):
    r = DB.transports.get(tid)
    if r is None:
        fail(err, "transport request %s not found" % tid)
    return r


def get_injury(iid, err="ERR_INJURY_REPORT_NOT_FOUND"):
    r = DB.injuries.get(iid)
    if r is None:
        fail(err, "injury report %s not found" % iid)
    return r


def get_credential(cid, err="ERR_CREDENTIAL_NOT_FOUND"):
    r = DB.credentials.get(cid)
    if r is None:
        fail(err, "staff credential %s not found" % cid)
    return r
