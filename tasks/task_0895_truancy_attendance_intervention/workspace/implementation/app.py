"""Truancy & Attendance-Intervention Program API — Flask reference implementation.

In-memory only. Boots empty on every process start (no seeding).
"""
import os
import random
import string
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
schools = {}
staff_store = {}
students = {}
records = {}          # attendance records
cases = {}
conferences = {}
contracts = {}
referrals = {}
citations = {}
checks = {}           # compliance checks

_seq_counter = 0


def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


# ---------------------------------------------------------------------------
# Constants / enums
# ---------------------------------------------------------------------------
ROLES = {"Administrator", "AttendanceClerk", "CaseManager", "CourtOfficer"}

STAFF_ROLE_TYPES = {"CASE_MANAGER", "OFFICER", "COUNSELOR"}
ENROLLMENT_STATUSES = {"ENROLLED", "WITHDRAWN", "GRADUATED"}
ATT_INPUT_STATUSES = {"PRESENT", "TARDY", "EXCUSED", "UNEXCUSED"}
ATT_ALL_STATUSES = {"PRESENT", "TARDY", "EXCUSED", "UNEXCUSED", "VOIDED"}
CASE_STATUSES = {"OPEN", "MONITORING", "RESOLVED", "CLOSED"}
TIER_ORDER = ["NONE", "TIER_1", "TIER_2", "TIER_3", "COURT_REFERRED"]
TIER_SET = set(TIER_ORDER)
CONFERENCE_STATUSES = {"SCHEDULED", "HELD", "NO_SHOW", "CANCELLED"}
CONTRACT_STATUSES = {"PROPOSED", "ACTIVE", "BREACHED", "FULFILLED", "CANCELLED"}
REFERRAL_STATUSES = {"REFERRED", "ACCEPTED", "IN_PROGRESS", "COMPLETED", "NO_SHOW", "DECLINED"}
SERVICE_TYPES = {"MENTOR", "COUNSELING", "HEALTH", "OTHER"}
CITATION_STATUSES = {"SCHEDULED", "HEARD", "DISMISSED", "WITHDRAWN"}
COMPLIANCE_RESULTS = {"COMPLIANT", "NON_COMPLIANT"}

HEARING_BUFFER = timedelta(minutes=30)
FULFILL_THRESHOLD = Decimal("80.00")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=""):
    raise ApiError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def gen_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def new_uuid():
    return str(uuid.uuid4())


def new_common():
    ts = now_iso()
    return {
        "id": new_uuid(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(entity):
    entity["updated_at"] = now_iso()
    entity["version"] += 1


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_str(v):
    return isinstance(v, str)


def round2(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def parse_instant(s):
    if not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def parse_date(s):
    if not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s).date()
    except Exception:
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def meta_base(extra=None):
    m = {"api_request_id": gen_request_id(), "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, response_type="object"):
    body = {"meta": meta_base(), "response_type": response_type, "data": data}
    return jsonify(body), status


def ok_list(items, pag):
    body = {"meta": meta_base(pag), "response_type": "array", "data": items}
    return jsonify(body), 200


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
@app.before_request
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid auth headers")
    g.user_id = uid
    g.role = role


def require(*roles):
    if g.role not in roles:
        err("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")


# ---------------------------------------------------------------------------
# Body / validation helpers
# ---------------------------------------------------------------------------
def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        err("ERR_VALIDATION", 400, "Request body must be a JSON object")
    return data


def need(data, key):
    if key not in data or data[key] is None:
        err("ERR_VALIDATION", 400, f"Missing required field: {key}")
    return data[key]


def paginate(items):
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            err("ERR_PAGINATION_INVALID", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            err("ERR_PAGINATION_INVALID", 400, "limit out of bounds")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            err("ERR_PAGINATION_INVALID", 400, "offset must be an integer")
        if offset < 0:
            err("ERR_PAGINATION_INVALID", 400, "offset out of bounds")
    ordered = sorted(items, key=lambda x: x["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    has_more = (offset + len(page)) < total
    pag = {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}
    return page, pag


def enum_check(value, allowed, field):
    if value not in allowed:
        err("ERR_INVALID_ENUM", 422, f"Invalid enum value for {field}: {value}")


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def school_dict(s):
    return {
        "id": s["id"],
        "name": s["name"],
        "tier1_unexcused_threshold": s["tier1_unexcused_threshold"],
        "tier2_unexcused_threshold": s["tier2_unexcused_threshold"],
        "tier3_unexcused_threshold": s["tier3_unexcused_threshold"],
        "court_unexcused_threshold": s["court_unexcused_threshold"],
        "required_instructional_days": s["required_instructional_days"],
        "chronic_absence_pct_threshold": s["chronic_absence_pct_threshold"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def staff_dict(s):
    return {
        "id": s["id"],
        "school_id": s["school_id"],
        "full_name": s["full_name"],
        "role_type": s["role_type"],
        "max_caseload": s["max_caseload"],
        "active_caseload": s["active_caseload"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def student_dict(s):
    return {
        "id": s["id"],
        "school_id": s["school_id"],
        "full_name": s["full_name"],
        "grade_level": s["grade_level"],
        "enrollment_status": s["enrollment_status"],
        "present_count": s["present_count"],
        "tardy_count": s["tardy_count"],
        "excused_count": s["excused_count"],
        "unexcused_count": s["unexcused_count"],
        "attendance_rate_recorded": s["attendance_rate_recorded"],
        "attendance_rate_official": s["attendance_rate_official"],
        "chronic_absent": s["chronic_absent"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def record_dict(r):
    return {
        "id": r["id"],
        "student_id": r["student_id"],
        "attendance_date": r["attendance_date"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def case_dict(c):
    return {
        "id": c["id"],
        "student_id": c["student_id"],
        "assigned_staff_id": c["assigned_staff_id"],
        "tier": c["tier"],
        "status": c["status"],
        "unexcused_at_open": c["unexcused_at_open"],
        "breach_count": c["breach_count"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def conference_dict(c):
    return {
        "id": c["id"],
        "case_id": c["case_id"],
        "scheduled_start": c["scheduled_start"],
        "scheduled_end": c["scheduled_end"],
        "status": c["status"],
        "outcome": c["outcome"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def contract_dict(c):
    actual, projected = compute_scores(c["goals"])
    return {
        "id": c["id"],
        "case_id": c["case_id"],
        "start_date": c["start_date"],
        "end_date": c["end_date"],
        "status": c["status"],
        "goals": [
            {
                "goal_id": g["goal_id"],
                "description": g["description"],
                "weight": g["weight"],
                "target_value": g["target_value"],
                "met_value": g["met_value"],
            }
            for g in c["goals"]
        ],
        "compliance_score_actual": actual,
        "compliance_score_projected": projected,
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def referral_dict(r):
    return {
        "id": r["id"],
        "case_id": r["case_id"],
        "service_type": r["service_type"],
        "provider_name": r["provider_name"],
        "status": r["status"],
        "auto_created": r["auto_created"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def citation_dict(c):
    return {
        "id": c["id"],
        "case_id": c["case_id"],
        "courtroom_id": c["courtroom_id"],
        "hearing_start": c["hearing_start"],
        "hearing_end": c["hearing_end"],
        "status": c["status"],
        "disposition": c["disposition"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def check_dict(c):
    return {
        "id": c["id"],
        "case_id": c["case_id"],
        "check_date": c["check_date"],
        "result": c["result"],
        "notes": c["notes"],
        "created_at": c["created_at"],
    }


# ---------------------------------------------------------------------------
# Computation / cascades
# ---------------------------------------------------------------------------
def recompute_student(student):
    recs = [r for r in records.values()
            if r["student_id"] == student["id"] and r["status"] != "VOIDED"]
    present = sum(1 for r in recs if r["status"] == "PRESENT")
    tardy = sum(1 for r in recs if r["status"] == "TARDY")
    excused = sum(1 for r in recs if r["status"] == "EXCUSED")
    unexcused = sum(1 for r in recs if r["status"] == "UNEXCUSED")
    student["present_count"] = present
    student["tardy_count"] = tardy
    student["excused_count"] = excused
    student["unexcused_count"] = unexcused

    school = schools[student["school_id"]]
    required = school["required_instructional_days"]

    attended = present + tardy
    absent = excused + unexcused
    if attended + absent == 0:
        student["attendance_rate_recorded"] = None
    else:
        student["attendance_rate_recorded"] = round2(attended / (attended + absent) * 100)

    remaining = required - excused - unexcused
    student["attendance_rate_official"] = round2(max(remaining, 0) / required * 100)

    absence_pct = round2((excused + unexcused) / required * 100)
    student["chronic_absent"] = absence_pct >= school["chronic_absence_pct_threshold"]


def computed_tier_idx(student):
    school = schools[student["school_id"]]
    adj = 1 if student["grade_level"] <= 5 else 0
    u = student["unexcused_count"]
    if u >= school["court_unexcused_threshold"] - adj:
        base = 4
    elif u >= school["tier3_unexcused_threshold"] - adj:
        base = 3
    elif u >= school["tier2_unexcused_threshold"] - adj:
        base = 2
    elif u >= school["tier1_unexcused_threshold"] - adj:
        base = 1
    else:
        base = 0
    prior_closed = sum(1 for c in cases.values()
                       if c["student_id"] == student["id"] and c["status"] == "CLOSED")
    if prior_closed >= 1 and base != 0:
        base = min(base + 1, 4)
    return base


def maybe_create_mentor(case):
    active = any(r for r in referrals.values()
                 if r["case_id"] == case["id"]
                 and r["status"] in {"REFERRED", "ACCEPTED", "IN_PROGRESS"})
    if active:
        return
    ref = new_common()
    ref.update({
        "case_id": case["id"],
        "service_type": "MENTOR",
        "provider_name": "UNASSIGNED",
        "status": "REFERRED",
        "auto_created": True,
    })
    referrals[ref["id"]] = ref


def set_case_tier(case, new_idx):
    """Raise case tier monotonically to max(current, new_idx). Returns True if it rose."""
    old_idx = TIER_ORDER.index(case["tier"])
    target = max(old_idx, min(new_idx, 4))
    if target == old_idx:
        return False
    case["tier"] = TIER_ORDER[target]
    touch(case)
    if TIER_ORDER[target] == "TIER_2" and old_idx < 2:
        maybe_create_mentor(case)
    return True


def non_terminal_case(student_id):
    for c in cases.values():
        if c["student_id"] == student_id and c["status"] != "CLOSED":
            return c
    return None


def open_new_case(student):
    idx = computed_tier_idx(student)
    case = new_common()
    case.update({
        "student_id": student["id"],
        "assigned_staff_id": None,
        "tier": TIER_ORDER[idx],
        "status": "OPEN",
        "unexcused_at_open": student["unexcused_count"],
        "breach_count": 0,
    })
    cases[case["id"]] = case
    if TIER_ORDER[idx] == "TIER_2":
        maybe_create_mentor(case)
    return case


def count_caseload(staff_id):
    return sum(1 for c in cases.values()
               if c["assigned_staff_id"] == staff_id and c["status"] in {"OPEN", "MONITORING"})


def recompute_caseload(staff_id):
    if not staff_id:
        return
    staff = staff_store.get(staff_id)
    if staff is None:
        return
    val = count_caseload(staff_id)
    if staff["active_caseload"] != val:
        staff["active_caseload"] = val
        touch(staff)


def compute_scores(goals):
    if not goals:
        return None, None
    sum_w = sum(g["weight"] for g in goals)
    actual = Decimal("0")
    projected = Decimal("0")
    for g in goals:
        met = Decimal(str(g["met_value"]))
        target = Decimal(str(g["target_value"]))
        ratio = met / target
        if ratio > 1:
            ratio = Decimal("1")
        ratio_actual = ratio
        ratio_proj = Decimal("1") if met == 0 else ratio
        share = Decimal(g["weight"]) / Decimal(sum_w)
        line_a = (ratio_actual * share * Decimal("100")).quantize(Decimal("0.01"), ROUND_HALF_UP)
        line_p = (ratio_proj * share * Decimal("100")).quantize(Decimal("0.01"), ROUND_HALF_UP)
        actual += line_a
        projected += line_p
    actual = actual.quantize(Decimal("0.01"), ROUND_HALF_UP)
    projected = projected.quantize(Decimal("0.01"), ROUND_HALF_UP)
    return float(actual), float(projected)


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------
def get_or_404(store, key):
    obj = store.get(key)
    if obj is None:
        err("ERR_NOT_FOUND", 404, "Resource not found")
    return obj


def get_child_or_404(store, child_id, case_id):
    obj = store.get(child_id)
    if obj is None or obj["case_id"] != case_id:
        err("ERR_NOT_FOUND", 404, "Resource not found")
    return obj


# ===========================================================================
# School endpoints
# ===========================================================================
@app.route("/schools", methods=["POST"])
def create_school():
    require("Administrator")
    data = get_body()
    name = need(data, "name")
    if not is_str(name):
        err("ERR_VALIDATION", 400, "name must be a string")

    def opt_int(key, default):
        if key in data and data[key] is not None:
            if not is_int(data[key]):
                err("ERR_VALIDATION", 400, f"{key} must be an integer")
            return data[key]
        return default

    def opt_num(key, default):
        if key in data and data[key] is not None:
            if not is_num(data[key]):
                err("ERR_VALIDATION", 400, f"{key} must be a number")
            return data[key]
        return default

    s = new_common()
    s.update({
        "name": name,
        "tier1_unexcused_threshold": opt_int("tier1_unexcused_threshold", 3),
        "tier2_unexcused_threshold": opt_int("tier2_unexcused_threshold", 6),
        "tier3_unexcused_threshold": opt_int("tier3_unexcused_threshold", 10),
        "court_unexcused_threshold": opt_int("court_unexcused_threshold", 15),
        "required_instructional_days": opt_int("required_instructional_days", 180),
        "chronic_absence_pct_threshold": opt_num("chronic_absence_pct_threshold", 10.0),
    })
    schools[s["id"]] = s
    return ok(school_dict(s), 201)


@app.route("/schools/<sid>", methods=["GET"])
def get_school(sid):
    require("Administrator", "AttendanceClerk", "CaseManager", "CourtOfficer")
    s = get_or_404(schools, sid)
    return ok(school_dict(s), 200)


@app.route("/schools/<sid>/students", methods=["GET"])
def list_school_students(sid):
    require("Administrator", "AttendanceClerk", "CaseManager", "CourtOfficer")
    get_or_404(schools, sid)
    items = [s for s in students.values() if s["school_id"] == sid]
    page, pag = paginate(items)
    return ok_list([student_dict(s) for s in page], pag)


@app.route("/schools/<sid>/staff", methods=["GET"])
def list_school_staff(sid):
    require("Administrator", "AttendanceClerk", "CaseManager", "CourtOfficer")
    get_or_404(schools, sid)
    role_type = request.args.get("role_type")
    items = [s for s in staff_store.values() if s["school_id"] == sid]
    if role_type is not None:
        items = [s for s in items if s["role_type"] == role_type]
    page, pag = paginate(items)
    return ok_list([staff_dict(s) for s in page], pag)


@app.route("/schools/<sid>/report", methods=["GET"])
def school_report(sid):
    require("Administrator", "AttendanceClerk", "CaseManager", "CourtOfficer")
    get_or_404(schools, sid)
    school_students = [s for s in students.values() if s["school_id"] == sid]
    student_ids = {s["id"] for s in school_students}
    school_cases = [c for c in cases.values() if c["student_id"] in student_ids]
    cases_by_tier = {t: 0 for t in TIER_ORDER}
    cases_by_status = {st: 0 for st in ["OPEN", "MONITORING", "RESOLVED", "CLOSED"]}
    for c in school_cases:
        cases_by_tier[c["tier"]] += 1
        cases_by_status[c["status"]] += 1
    case_ids = {c["id"] for c in school_cases}
    open_citations = sum(1 for ci in citations.values()
                         if ci["case_id"] in case_ids and ci["status"] == "SCHEDULED")
    data = {
        "total_students": len(school_students),
        "chronic_absent_count": sum(1 for s in school_students if s["chronic_absent"]),
        "cases_by_tier": cases_by_tier,
        "cases_by_status": cases_by_status,
        "open_citation_count": open_citations,
    }
    return ok(data, 200)


# ===========================================================================
# Staff endpoints
# ===========================================================================
@app.route("/staff", methods=["POST"])
def create_staff():
    require("Administrator")
    data = get_body()
    school_id = need(data, "school_id")
    full_name = need(data, "full_name")
    role_type = need(data, "role_type")
    if not is_str(school_id) or not is_str(full_name):
        err("ERR_VALIDATION", 400, "school_id and full_name must be strings")
    max_caseload = 25
    if "max_caseload" in data and data["max_caseload"] is not None:
        if not is_int(data["max_caseload"]):
            err("ERR_VALIDATION", 400, "max_caseload must be an integer")
        max_caseload = data["max_caseload"]
    enum_check(role_type, STAFF_ROLE_TYPES, "role_type")
    get_or_404(schools, school_id)
    s = new_common()
    s.update({
        "school_id": school_id,
        "full_name": full_name,
        "role_type": role_type,
        "max_caseload": max_caseload,
        "active_caseload": 0,
    })
    staff_store[s["id"]] = s
    return ok(staff_dict(s), 201)


@app.route("/staff/<staff_id>", methods=["GET"])
def get_staff(staff_id):
    require("Administrator", "AttendanceClerk", "CaseManager", "CourtOfficer")
    s = get_or_404(staff_store, staff_id)
    return ok(staff_dict(s), 200)


# ===========================================================================
# Student endpoints
# ===========================================================================
@app.route("/students", methods=["POST"])
def create_student():
    require("Administrator")
    data = get_body()
    school_id = need(data, "school_id")
    full_name = need(data, "full_name")
    grade_level = need(data, "grade_level")
    if not is_str(school_id) or not is_str(full_name):
        err("ERR_VALIDATION", 400, "school_id and full_name must be strings")
    if not is_int(grade_level) or grade_level < 0 or grade_level > 12:
        err("ERR_VALIDATION", 400, "grade_level must be an integer 0..12")
    get_or_404(schools, school_id)
    s = new_common()
    s.update({
        "school_id": school_id,
        "full_name": full_name,
        "grade_level": grade_level,
        "enrollment_status": "ENROLLED",
        "present_count": 0,
        "tardy_count": 0,
        "excused_count": 0,
        "unexcused_count": 0,
        "attendance_rate_recorded": None,
        "attendance_rate_official": None,
        "chronic_absent": False,
    })
    students[s["id"]] = s
    recompute_student(s)
    return ok(student_dict(s), 201)


@app.route("/students/<student_id>", methods=["GET"])
def get_student(student_id):
    require("Administrator", "AttendanceClerk", "CaseManager", "CourtOfficer")
    s = get_or_404(students, student_id)
    return ok(student_dict(s), 200)


@app.route("/students/<student_id>/enrollment", methods=["POST"])
def change_enrollment(student_id):
    require("Administrator")
    data = get_body()
    to_status = need(data, "to_status")
    enum_check(to_status, ENROLLMENT_STATUSES, "to_status")
    student = get_or_404(students, student_id)
    cur = student["enrollment_status"]
    allowed = {
        ("ENROLLED", "WITHDRAWN"),
        ("ENROLLED", "GRADUATED"),
        ("WITHDRAWN", "ENROLLED"),
    }
    if (cur, to_status) not in allowed:
        err("ERR_INVALID_STATE", 409, f"Cannot move enrollment {cur} -> {to_status}")
    student["enrollment_status"] = to_status
    touch(student)
    return ok(student_dict(student), 200)


@app.route("/students/<student_id>/attendance-records", methods=["POST"])
def create_attendance(student_id):
    require("Administrator", "AttendanceClerk")
    data = get_body()
    attendance_date = need(data, "attendance_date")
    status = need(data, "status")
    if not is_str(attendance_date) or parse_date(attendance_date) is None:
        err("ERR_VALIDATION", 400, "attendance_date must be an ISO date (YYYY-MM-DD)")
    enum_check(status, ATT_INPUT_STATUSES, "status")
    student = get_or_404(students, student_id)
    if student["enrollment_status"] != "ENROLLED":
        err("ERR_STUDENT_NOT_ENROLLED", 409, "Student is not enrolled")
    dup = any(r for r in records.values()
              if r["student_id"] == student_id
              and r["attendance_date"] == attendance_date
              and r["status"] != "VOIDED")
    if dup:
        err("ERR_DUPLICATE_ATTENDANCE", 409, "Attendance already recorded for this date")

    r = new_common()
    r.update({
        "student_id": student_id,
        "attendance_date": attendance_date,
        "status": status,
    })
    records[r["id"]] = r
    recompute_student(student)

    if status == "UNEXCUSED":
        case = non_terminal_case(student_id)
        if case is not None:
            rose = set_case_tier(case, computed_tier_idx(student))
            if rose and case["status"] == "RESOLVED":
                case["status"] = "OPEN"
                touch(case)
                recompute_caseload(case["assigned_staff_id"])
        else:
            if computed_tier_idx(student) >= 1:
                open_new_case(student)

    return ok(record_dict(r), 201)


@app.route("/students/<student_id>/attendance-records", methods=["GET"])
def list_attendance(student_id):
    require("Administrator", "AttendanceClerk", "CaseManager", "CourtOfficer")
    get_or_404(students, student_id)
    status = request.args.get("status")
    items = [r for r in records.values() if r["student_id"] == student_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, pag = paginate(items)
    return ok_list([record_dict(r) for r in page], pag)


@app.route("/students/<student_id>/attendance-records/<record_id>/reclassify", methods=["POST"])
def reclassify_attendance(student_id, record_id):
    require("Administrator", "AttendanceClerk")
    data = get_body()
    to_status = need(data, "to_status")
    enum_check(to_status, ATT_ALL_STATUSES, "to_status")
    student = get_or_404(students, student_id)
    record = records.get(record_id)
    if record is None or record["student_id"] != student_id:
        err("ERR_NOT_FOUND", 404, "Attendance record not found")
    if student["enrollment_status"] != "ENROLLED":
        err("ERR_STUDENT_NOT_ENROLLED", 409, "Student is not enrolled")

    cur = record["status"]
    allowed = {
        ("UNEXCUSED", "EXCUSED"),
        ("EXCUSED", "UNEXCUSED"),
        ("PRESENT", "UNEXCUSED"),
        ("UNEXCUSED", "VOIDED"),
    }
    if cur == "VOIDED" or (cur, to_status) not in allowed:
        err("ERR_INVALID_STATE", 409, f"Cannot reclassify {cur} -> {to_status}")

    prev_unexcused = student["unexcused_count"]
    record["status"] = to_status
    touch(record)
    recompute_student(student)

    if student["unexcused_count"] > prev_unexcused:
        case = non_terminal_case(student_id)
        if case is not None:
            set_case_tier(case, computed_tier_idx(student))

    return ok(record_dict(record), 200)


# ===========================================================================
# TruancyCase endpoints
# ===========================================================================
@app.route("/cases", methods=["POST"])
def create_case():
    require("Administrator", "CaseManager")
    data = get_body()
    student_id = need(data, "student_id")
    if not is_str(student_id):
        err("ERR_VALIDATION", 400, "student_id must be a string")
    student = get_or_404(students, student_id)
    if non_terminal_case(student_id) is not None:
        err("ERR_CASE_ALREADY_OPEN", 409, "Student already has a non-terminal case")
    if student["enrollment_status"] != "ENROLLED":
        err("ERR_STUDENT_NOT_ENROLLED", 409, "Student is not enrolled")
    case = open_new_case(student)
    return ok(case_dict(case), 201)


@app.route("/cases/<case_id>", methods=["GET"])
def get_case(case_id):
    require("Administrator", "AttendanceClerk", "CaseManager", "CourtOfficer")
    c = get_or_404(cases, case_id)
    return ok(case_dict(c), 200)


@app.route("/cases", methods=["GET"])
def list_cases():
    require("Administrator", "AttendanceClerk", "CaseManager", "CourtOfficer")
    items = list(cases.values())
    student_id = request.args.get("student_id")
    assigned_staff_id = request.args.get("assigned_staff_id")
    tier = request.args.get("tier")
    status = request.args.get("status")
    if student_id is not None:
        items = [c for c in items if c["student_id"] == student_id]
    if assigned_staff_id is not None:
        items = [c for c in items if c["assigned_staff_id"] == assigned_staff_id]
    if tier is not None:
        items = [c for c in items if c["tier"] == tier]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, pag = paginate(items)
    return ok_list([case_dict(c) for c in page], pag)


@app.route("/cases/<case_id>/assign", methods=["POST"])
def assign_case(case_id):
    require("Administrator", "CaseManager")
    data = get_body()
    staff_id = need(data, "staff_id")
    if not is_str(staff_id):
        err("ERR_VALIDATION", 400, "staff_id must be a string")
    case = get_or_404(cases, case_id)
    staff = staff_store.get(staff_id)
    if staff is None:
        err("ERR_NOT_FOUND", 404, "Staff not found")
    if staff["role_type"] != "CASE_MANAGER":
        err("ERR_INVALID_STAFF_ROLE", 409, "Assignee must be a CASE_MANAGER")
    counts_toward = case["status"] in {"OPEN", "MONITORING"}
    already = case["assigned_staff_id"] == staff_id
    projected = count_caseload(staff_id) + (1 if counts_toward and not already else 0)
    if projected > staff["max_caseload"]:
        err("ERR_CASELOAD_EXCEEDED", 409, "Assignment exceeds max caseload")
    prior = case["assigned_staff_id"]
    case["assigned_staff_id"] = staff_id
    touch(case)
    if prior and prior != staff_id:
        recompute_caseload(prior)
    recompute_caseload(staff_id)
    return ok(case_dict(case), 200)


def case_tier_transition(case, to_tier):
    cur = TIER_ORDER.index(case["tier"])
    tgt = TIER_ORDER.index(to_tier)
    if tgt <= cur:
        err("ERR_TIER_REGRESSION", 409, "to_tier must be strictly above current tier")
    if cur != 0 and tgt != cur + 1:
        err("ERR_TIER_REGRESSION", 409, "to_tier must be exactly one step above current tier")
    set_case_tier(case, tgt)


def case_status_transition(case, to_status):
    cur = case["status"]
    cid = case["id"]
    if cur == "OPEN" and to_status == "MONITORING":
        held = any(c for c in conferences.values()
                   if c["case_id"] == cid and c["status"] == "HELD")
        if not held:
            err("ERR_NO_CONFERENCE_HELD", 409, "A HELD conference is required")
        case["status"] = "MONITORING"
        touch(case)
        recompute_caseload(case["assigned_staff_id"])
    elif cur == "MONITORING" and to_status == "RESOLVED":
        scheduled = any(ci for ci in citations.values()
                        if ci["case_id"] == cid and ci["status"] == "SCHEDULED")
        if scheduled:
            err("ERR_INVALID_STATE", 409, "Cannot resolve with a SCHEDULED citation")
        case["status"] = "RESOLVED"
        touch(case)
        for r in referrals.values():
            if r["case_id"] == cid and r["status"] in {"REFERRED", "ACCEPTED", "IN_PROGRESS"}:
                r["status"] = "COMPLETED"
                touch(r)
        recompute_caseload(case["assigned_staff_id"])
    elif cur in {"MONITORING", "RESOLVED"} and to_status == "CLOSED":
        blocking_contract = any(ct for ct in contracts.values()
                                if ct["case_id"] == cid
                                and ct["status"] in {"PROPOSED", "ACTIVE", "BREACHED"})
        if blocking_contract:
            err("ERR_INVALID_STATE", 409, "Cannot close with an active contract")
        scheduled = any(ci for ci in citations.values()
                        if ci["case_id"] == cid and ci["status"] == "SCHEDULED")
        if scheduled:
            err("ERR_INVALID_STATE", 409, "Cannot close with a SCHEDULED citation")
        case["status"] = "CLOSED"
        touch(case)
        recompute_caseload(case["assigned_staff_id"])
    else:
        err("ERR_INVALID_STATE", 409, f"Cannot move status {cur} -> {to_status}")


@app.route("/cases/<case_id>/transition", methods=["POST"])
def transition_case(case_id):
    require("Administrator", "CaseManager")
    data = get_body()
    to_status = data.get("to_status")
    to_tier = data.get("to_tier")
    if to_status is None and to_tier is None:
        err("ERR_VALIDATION", 400, "to_status or to_tier is required")
    if to_status is not None:
        enum_check(to_status, CASE_STATUSES, "to_status")
    if to_tier is not None:
        enum_check(to_tier, TIER_SET, "to_tier")
    case = get_or_404(cases, case_id)
    if to_tier is not None:
        case_tier_transition(case, to_tier)
    if to_status is not None:
        case_status_transition(case, to_status)
    return ok(case_dict(case), 200)


# ===========================================================================
# Conference endpoints
# ===========================================================================
@app.route("/cases/<case_id>/conferences", methods=["POST"])
def create_conference(case_id):
    require("Administrator", "CaseManager")
    data = get_body()
    scheduled_start = need(data, "scheduled_start")
    scheduled_end = need(data, "scheduled_end")
    start_dt = parse_instant(scheduled_start)
    end_dt = parse_instant(scheduled_end)
    if start_dt is None or end_dt is None:
        err("ERR_VALIDATION", 400, "scheduled_start/scheduled_end must be ISO 8601 instants")
    if end_dt <= start_dt:
        err("ERR_VALIDATION", 400, "scheduled_end must be strictly after scheduled_start")
    case = get_or_404(cases, case_id)
    resource = case["assigned_staff_id"]
    for other in conferences.values():
        if other["status"] != "SCHEDULED":
            continue
        other_case = cases.get(other["case_id"])
        if other_case is None:
            continue
        if other_case["assigned_staff_id"] != resource:
            continue
        o_start = parse_instant(other["scheduled_start"])
        o_end = parse_instant(other["scheduled_end"])
        if start_dt < o_end and o_start < end_dt:
            err("ERR_CONFERENCE_OVERLAP", 409, "Conference overlaps existing on assigned staff")
    conf = new_common()
    conf.update({
        "case_id": case_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "status": "SCHEDULED",
        "outcome": None,
    })
    conferences[conf["id"]] = conf
    return ok(conference_dict(conf), 201)


@app.route("/cases/<case_id>/conferences", methods=["GET"])
def list_conferences(case_id):
    require("Administrator", "AttendanceClerk", "CaseManager", "CourtOfficer")
    get_or_404(cases, case_id)
    status = request.args.get("status")
    items = [c for c in conferences.values() if c["case_id"] == case_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, pag = paginate(items)
    return ok_list([conference_dict(c) for c in page], pag)


@app.route("/cases/<case_id>/conferences/<conference_id>/transition", methods=["POST"])
def transition_conference(case_id, conference_id):
    require("Administrator", "CaseManager")
    data = get_body()
    to_status = need(data, "to_status")
    enum_check(to_status, CONFERENCE_STATUSES, "to_status")
    get_or_404(cases, case_id)
    conf = get_child_or_404(conferences, conference_id, case_id)
    if conf["status"] != "SCHEDULED" or to_status not in {"HELD", "NO_SHOW", "CANCELLED"}:
        err("ERR_INVALID_STATE", 409, f"Cannot transition conference to {to_status}")
    conf["status"] = to_status
    if to_status == "HELD" and "outcome" in data and data["outcome"] is not None:
        conf["outcome"] = data["outcome"]
    elif to_status == "NO_SHOW" and "outcome" in data and data["outcome"] is not None:
        conf["outcome"] = data["outcome"]
    touch(conf)
    return ok(conference_dict(conf), 200)


# ===========================================================================
# AttendanceContract endpoints
# ===========================================================================
def validate_goals(goals):
    if not isinstance(goals, list):
        err("ERR_VALIDATION", 400, "goals must be an array")
    result = []
    for g in goals:
        if not isinstance(g, dict):
            err("ERR_VALIDATION", 400, "each goal must be an object")
        description = g.get("description")
        weight = g.get("weight")
        target_value = g.get("target_value")
        if description is None or not is_str(description):
            err("ERR_VALIDATION", 400, "goal.description required (string)")
        if not is_int(weight) or weight <= 0:
            err("ERR_VALIDATION", 400, "goal.weight must be a positive integer")
        if not is_num(target_value) or target_value <= 0:
            err("ERR_VALIDATION", 400, "goal.target_value must be a positive number")
        met_value = 0
        if "met_value" in g and g["met_value"] is not None:
            if not is_num(g["met_value"]) or g["met_value"] < 0:
                err("ERR_VALIDATION", 400, "goal.met_value must be a non-negative number")
            met_value = g["met_value"]
        result.append({
            "goal_id": new_uuid(),
            "description": description,
            "weight": weight,
            "target_value": target_value,
            "met_value": met_value,
        })
    return result


@app.route("/cases/<case_id>/contracts", methods=["POST"])
def create_contract(case_id):
    require("Administrator", "CaseManager")
    data = get_body()
    start_date = need(data, "start_date")
    end_date = need(data, "end_date")
    goals_in = need(data, "goals")
    expected_case_version = need(data, "expected_case_version")
    if not is_int(expected_case_version):
        err("ERR_VALIDATION", 400, "expected_case_version must be an integer")
    sd = parse_date(start_date)
    ed = parse_date(end_date)
    if sd is None or ed is None:
        err("ERR_VALIDATION", 400, "start_date/end_date must be ISO dates")
    if ed <= sd:
        err("ERR_VALIDATION", 400, "end_date must be after start_date")
    goals = validate_goals(goals_in)
    case = get_or_404(cases, case_id)
    if expected_case_version != case["version"]:
        err("ERR_STALE_VERSION", 412, "expected_case_version does not match case version")
    # supersede prior non-terminal contracts
    for ct in contracts.values():
        if ct["case_id"] == case_id and ct["status"] in {"PROPOSED", "ACTIVE", "BREACHED"}:
            ct["status"] = "CANCELLED"
            touch(ct)
    contract = new_common()
    contract.update({
        "case_id": case_id,
        "start_date": start_date,
        "end_date": end_date,
        "status": "PROPOSED",
        "goals": goals,
    })
    contracts[contract["id"]] = contract
    touch(case)  # increments case.version by 1
    return ok(contract_dict(contract), 201)


@app.route("/cases/<case_id>/contracts", methods=["GET"])
def list_contracts(case_id):
    require("Administrator", "AttendanceClerk", "CaseManager", "CourtOfficer")
    get_or_404(cases, case_id)
    status = request.args.get("status")
    items = [c for c in contracts.values() if c["case_id"] == case_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, pag = paginate(items)
    return ok_list([contract_dict(c) for c in page], pag)


@app.route("/cases/<case_id>/contracts/<contract_id>/goals/<goal_id>/progress", methods=["POST"])
def update_goal_progress(case_id, contract_id, goal_id):
    require("Administrator", "CaseManager")
    data = get_body()
    met_value = need(data, "met_value")
    if not is_num(met_value) or met_value < 0:
        err("ERR_VALIDATION", 400, "met_value must be a non-negative number")
    get_or_404(cases, case_id)
    contract = get_child_or_404(contracts, contract_id, case_id)
    goal = next((g for g in contract["goals"] if g["goal_id"] == goal_id), None)
    if goal is None:
        err("ERR_GOAL_NOT_FOUND", 404, "Goal not found in contract")
    goal["met_value"] = met_value
    touch(contract)
    return ok(contract_dict(contract), 200)


def breach_contract(contract, case):
    contract["status"] = "BREACHED"
    touch(contract)
    case["breach_count"] += 1
    cur = TIER_ORDER.index(case["tier"])
    touch(case)
    set_case_tier(case, min(cur + 1, 4))


@app.route("/cases/<case_id>/contracts/<contract_id>/transition", methods=["POST"])
def transition_contract(case_id, contract_id):
    require("Administrator", "CaseManager")
    data = get_body()
    to_status = need(data, "to_status")
    enum_check(to_status, CONTRACT_STATUSES, "to_status")
    case = get_or_404(cases, case_id)
    contract = get_child_or_404(contracts, contract_id, case_id)
    cur = contract["status"]

    if cur == "PROPOSED" and to_status == "ACTIVE":
        held = any(c for c in conferences.values()
                   if c["case_id"] == case_id and c["status"] == "HELD")
        if not held:
            err("ERR_NO_CONFERENCE_HELD", 409, "A HELD conference is required")
        contract["status"] = "ACTIVE"
        touch(contract)
    elif cur == "ACTIVE" and to_status == "BREACHED":
        breach_contract(contract, case)
    elif cur == "BREACHED" and to_status == "ACTIVE":
        contract["status"] = "ACTIVE"
        touch(contract)
    elif cur == "ACTIVE" and to_status == "FULFILLED":
        actual, _ = compute_scores(contract["goals"])
        if actual is None or Decimal(str(actual)) < FULFILL_THRESHOLD:
            err("ERR_INVALID_STATE", 409, "compliance_score_actual must be >= 80.00")
        contract["status"] = "FULFILLED"
        touch(contract)
    elif cur in {"PROPOSED", "ACTIVE"} and to_status == "CANCELLED":
        contract["status"] = "CANCELLED"
        touch(contract)
    else:
        err("ERR_INVALID_STATE", 409, f"Cannot move contract {cur} -> {to_status}")

    return ok(contract_dict(contract), 200)


# ===========================================================================
# ServiceReferral endpoints
# ===========================================================================
@app.route("/cases/<case_id>/service-referrals", methods=["POST"])
def create_referral(case_id):
    require("Administrator", "CaseManager")
    data = get_body()
    service_type = need(data, "service_type")
    enum_check(service_type, SERVICE_TYPES, "service_type")
    provider_name = "UNASSIGNED"
    if "provider_name" in data and data["provider_name"] is not None:
        if not is_str(data["provider_name"]):
            err("ERR_VALIDATION", 400, "provider_name must be a string")
        provider_name = data["provider_name"]
    get_or_404(cases, case_id)
    ref = new_common()
    ref.update({
        "case_id": case_id,
        "service_type": service_type,
        "provider_name": provider_name,
        "status": "REFERRED",
        "auto_created": False,
    })
    referrals[ref["id"]] = ref
    return ok(referral_dict(ref), 201)


@app.route("/cases/<case_id>/service-referrals", methods=["GET"])
def list_referrals(case_id):
    require("Administrator", "AttendanceClerk", "CaseManager", "CourtOfficer")
    get_or_404(cases, case_id)
    status = request.args.get("status")
    service_type = request.args.get("service_type")
    items = [r for r in referrals.values() if r["case_id"] == case_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if service_type is not None:
        items = [r for r in items if r["service_type"] == service_type]
    page, pag = paginate(items)
    return ok_list([referral_dict(r) for r in page], pag)


@app.route("/cases/<case_id>/service-referrals/<referral_id>/transition", methods=["POST"])
def transition_referral(case_id, referral_id):
    require("Administrator", "CaseManager")
    data = get_body()
    to_status = need(data, "to_status")
    enum_check(to_status, REFERRAL_STATUSES, "to_status")
    get_or_404(cases, case_id)
    ref = get_child_or_404(referrals, referral_id, case_id)
    cur = ref["status"]
    allowed = {
        ("REFERRED", "ACCEPTED"),
        ("ACCEPTED", "IN_PROGRESS"),
        ("IN_PROGRESS", "COMPLETED"),
        ("REFERRED", "DECLINED"),
        ("ACCEPTED", "NO_SHOW"),
        ("IN_PROGRESS", "NO_SHOW"),
    }
    if (cur, to_status) not in allowed:
        err("ERR_INVALID_STATE", 409, f"Cannot move referral {cur} -> {to_status}")
    ref["status"] = to_status
    touch(ref)
    return ok(referral_dict(ref), 200)


# ===========================================================================
# CourtCitation endpoints
# ===========================================================================
@app.route("/cases/<case_id>/court-citations", methods=["POST"])
def create_citation(case_id):
    require("Administrator", "CourtOfficer")
    data = get_body()
    courtroom_id = need(data, "courtroom_id")
    hearing_start = need(data, "hearing_start")
    hearing_end = need(data, "hearing_end")
    if not is_str(courtroom_id):
        err("ERR_VALIDATION", 400, "courtroom_id must be a string")
    start_dt = parse_instant(hearing_start)
    end_dt = parse_instant(hearing_end)
    if start_dt is None or end_dt is None:
        err("ERR_VALIDATION", 400, "hearing_start/hearing_end must be ISO 8601 instants")
    if end_dt <= start_dt:
        err("ERR_VALIDATION", 400, "hearing_end must be strictly after hearing_start")
    case = get_or_404(cases, case_id)
    if case["tier"] != "COURT_REFERRED":
        err("ERR_CASE_NOT_COURT_ELIGIBLE", 409, "Case is not COURT_REFERRED")
    for other in citations.values():
        if other["status"] != "SCHEDULED":
            continue
        if other["courtroom_id"] != courtroom_id:
            continue
        o_start = parse_instant(other["hearing_start"])
        o_end = parse_instant(other["hearing_end"])
        if start_dt < (o_end + HEARING_BUFFER) and (o_start - HEARING_BUFFER) < end_dt:
            err("ERR_HEARING_OVERLAP", 409, "Hearing overlaps existing in courtroom")
    cit = new_common()
    cit.update({
        "case_id": case_id,
        "courtroom_id": courtroom_id,
        "hearing_start": hearing_start,
        "hearing_end": hearing_end,
        "status": "SCHEDULED",
        "disposition": None,
    })
    citations[cit["id"]] = cit
    return ok(citation_dict(cit), 201)


@app.route("/cases/<case_id>/court-citations", methods=["GET"])
def list_citations(case_id):
    require("Administrator", "AttendanceClerk", "CaseManager", "CourtOfficer")
    get_or_404(cases, case_id)
    status = request.args.get("status")
    courtroom_id = request.args.get("courtroom_id")
    items = [c for c in citations.values() if c["case_id"] == case_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if courtroom_id is not None:
        items = [c for c in items if c["courtroom_id"] == courtroom_id]
    page, pag = paginate(items)
    return ok_list([citation_dict(c) for c in page], pag)


@app.route("/cases/<case_id>/court-citations/<citation_id>/transition", methods=["POST"])
def transition_citation(case_id, citation_id):
    require("Administrator", "CourtOfficer")
    data = get_body()
    to_status = need(data, "to_status")
    if to_status == "HEARD" and not data.get("disposition"):
        err("ERR_VALIDATION", 400, "disposition is required when marking HEARD")
    enum_check(to_status, CITATION_STATUSES, "to_status")
    get_or_404(cases, case_id)
    cit = get_child_or_404(citations, citation_id, case_id)
    cur = cit["status"]
    if cur != "SCHEDULED" or to_status not in {"HEARD", "DISMISSED", "WITHDRAWN"}:
        err("ERR_INVALID_STATE", 409, f"Cannot transition citation to {to_status}")
    cit["status"] = to_status
    if to_status == "HEARD":
        cit["disposition"] = data.get("disposition")
    touch(cit)
    return ok(citation_dict(cit), 200)


# ===========================================================================
# ComplianceCheck endpoints
# ===========================================================================
@app.route("/cases/<case_id>/compliance-checks", methods=["POST"])
def create_compliance_check(case_id):
    require("Administrator", "CaseManager")
    data = get_body()
    check_date = need(data, "check_date")
    result = need(data, "result")
    if not is_str(check_date) or parse_date(check_date) is None:
        err("ERR_VALIDATION", 400, "check_date must be an ISO date")
    enum_check(result, COMPLIANCE_RESULTS, "result")
    notes = None
    if "notes" in data and data["notes"] is not None:
        if not is_str(data["notes"]):
            err("ERR_VALIDATION", 400, "notes must be a string")
        notes = data["notes"]
    case = get_or_404(cases, case_id)

    ts = now_iso()
    chk = {
        "id": new_uuid(),
        "created_at": ts,
        "_seq": next_seq(),
        "case_id": case_id,
        "check_date": check_date,
        "result": result,
        "notes": notes,
    }
    checks[chk["id"]] = chk

    if result == "NON_COMPLIANT":
        active_contract = next(
            (ct for ct in contracts.values()
             if ct["case_id"] == case_id and ct["status"] == "ACTIVE"),
            None,
        )
        if active_contract is not None:
            breach_contract(active_contract, case)

    return ok(check_dict(chk), 201)


@app.route("/cases/<case_id>/compliance-checks", methods=["GET"])
def list_compliance_checks(case_id):
    require("Administrator", "AttendanceClerk", "CaseManager", "CourtOfficer")
    get_or_404(cases, case_id)
    items = [c for c in checks.values() if c["case_id"] == case_id]
    page, pag = paginate(items)
    return ok_list([check_dict(c) for c in page], pag)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
