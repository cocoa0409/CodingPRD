"""
K-12 Student Information System (SIS) API.

Single-file Flask implementation. All storage is in-memory (Python dicts keyed
by id). No entity data is seeded at startup; every entity is constructed by the
caller through the declared endpoints. A fresh process starts with empty stores.
"""

import os
import re
import uuid
import string
import random
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, g, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory data store (wiped on every process start — no seeding)
# ---------------------------------------------------------------------------

class Store:
    def __init__(self):
        self.schools = {}
        self.students = {}
        self.enrollments = {}
        self.courses = {}
        self.sections = {}
        self.schedule_assignments = {}
        self.attendance_records = {}
        self.daily_attendance = {}
        self.standard_scores = {}
        self.report_cards = {}
        self.discipline_incidents = {}
        self.discipline_consequences = {}
        self.ada_funding_reports = {}


db = Store()

ROLES = {"Registrar", "Teacher", "Administrator", "StateReportingOfficer", "Parent"}

# Map an entity-kind label to its NOT_FOUND error id.
NOT_FOUND = {
    "school": "ERR_SCHOOL_NOT_FOUND",
    "student": "ERR_STUDENT_NOT_FOUND",
    "enrollment": "ERR_ENROLLMENT_NOT_FOUND",
    "course": "ERR_COURSE_NOT_FOUND",
    "section": "ERR_SECTION_NOT_FOUND",
    "schedule_assignment": "ERR_SCHEDULE_ASSIGNMENT_NOT_FOUND",
    "attendance_record": "ERR_ATTENDANCE_RECORD_NOT_FOUND",
    "standard_score": "ERR_STANDARD_SCORE_NOT_FOUND",
    "report_card": "ERR_REPORT_CARD_NOT_FOUND",
    "incident": "ERR_INCIDENT_NOT_FOUND",
    "consequence": "ERR_CONSEQUENCE_NOT_FOUND",
    "ada_report": "ERR_ADA_REPORT_NOT_FOUND",
}

ERROR_HTTP = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_INSUFFICIENT_PERMISSIONS": 403,
    "ERR_NOT_GUARDIAN_OF_STUDENT": 403,
    "ERR_SCHOOL_NOT_FOUND": 404,
    "ERR_STUDENT_NOT_FOUND": 404,
    "ERR_ENROLLMENT_NOT_FOUND": 404,
    "ERR_COURSE_NOT_FOUND": 404,
    "ERR_SECTION_NOT_FOUND": 404,
    "ERR_SCHEDULE_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_ATTENDANCE_RECORD_NOT_FOUND": 404,
    "ERR_STANDARD_SCORE_NOT_FOUND": 404,
    "ERR_REPORT_CARD_NOT_FOUND": 404,
    "ERR_INCIDENT_NOT_FOUND": 404,
    "ERR_CONSEQUENCE_NOT_FOUND": 404,
    "ERR_ADA_REPORT_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_DUPLICATE_COURSE_CODE": 409,
    "ERR_DUPLICATE_STATE_STUDENT_ID": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_ENROLLMENT_NOT_ACTIVE": 409,
    "ERR_INVALID_EXIT_DAY": 422,
    "ERR_EXIT_DAY_IN_FUTURE": 422,
    "ERR_PRESENCE_ON_RECORD": 409,
    "ERR_PARENT_NOT_ACTIVE": 409,
    "ERR_SECTION_NOT_OPEN": 409,
    "ERR_SECTION_NOT_CLOSED": 409,
    "ERR_SECTION_CAPACITY_EXCEEDED": 409,
    "ERR_SCHEDULE_PERIOD_CONFLICT": 409,
    "ERR_ATTENDANCE_OUTSIDE_WINDOW": 422,
    "ERR_INVALID_GRADE_INPUT": 422,
    "ERR_REPORT_CARD_NOT_DRAFT": 409,
    "ERR_REPORT_CARD_NOT_FINALIZED": 409,
    "ERR_INCOMPLETE_GRADES": 409,
    "ERR_INCIDENT_NOT_REFERRED": 409,
    "ERR_INCIDENT_NOT_UNDER_REVIEW": 409,
    "ERR_INCIDENT_NOT_DISMISSIBLE": 409,
    "ERR_NOT_ASSIGNED_ADJUDICATOR": 403,
    "ERR_NO_CONSEQUENCE_RECORDED": 409,
    "ERR_INVALID_CONSEQUENCE": 422,
    "ERR_SUSPENSION_CAP_EXCEEDED": 422,
    "ERR_CONSEQUENCE_NOT_ACTIVE": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_REPORT_NOT_DRAFT": 409,
    "ERR_ATTENDANCE_NOT_POSTED": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------

def now_iso():
    # ISO 8601 UTC with three fractional digits.
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def request_id():
    chars = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(chars) for _ in range(20))


def meta(extra=None):
    m = {"api_request_id": request_id(), "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def success(data, status=200, response_type="object", pagination=None):
    body = {"meta": meta(pagination), "response_type": response_type, "data": data}
    return jsonify(body), status


def list_response(items, total_count, limit, offset, status=200):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return success(items, status=status, response_type="array", pagination=pagination)


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(_e):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": "Not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(_e):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": "Method not allowed"},
    }
    return jsonify(body), 405


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": str(e)},
    }
    return jsonify(body), 400


# ---------------------------------------------------------------------------
# Common entity helpers
# ---------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def stamp_new(obj):
    ts = now_iso()
    obj["id"] = new_id()
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    return obj


def touch(obj):
    """A mutation: refresh updated_at and increment version by one."""
    obj["updated_at"] = now_iso()
    obj["version"] = obj.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Auth / role enforcement
# ---------------------------------------------------------------------------

def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
    g.user_id = uid
    g.user_role = role
    return uid, role


def require_roles(allowed):
    uid, role = auth()
    if role not in allowed:
        raise ApiError("ERR_INSUFFICIENT_PERMISSIONS")
    return uid, role


def body():
    if request.method in ("POST", "PUT", "PATCH"):
        try:
            data = request.get_json(force=True, silent=True)
        except Exception:
            raise ApiError("ERR_INVALID_REQUEST")
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise ApiError("ERR_INVALID_REQUEST")
        return data
    return {}


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def find(coll, kind, _id):
    obj = coll.get(_id)
    if obj is None:
        raise ApiError(NOT_FOUND[kind])
    return obj


# ---------------------------------------------------------------------------
# Query / pagination helpers
# ---------------------------------------------------------------------------

def paginate(items):
    """items already filtered + sorted; apply limit/offset from query string."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST")
        if offset < 0:
            offset = 0
    total = len(items)
    page = items[offset: offset + limit]
    return page, total, limit, offset


def sorted_by_created(values):
    return sorted(values, key=lambda o: (o["created_at"], o["id"]))


# ---------------------------------------------------------------------------
# Input coercion helpers
# ---------------------------------------------------------------------------

def req_str(data, key):
    v = data.get(key)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_INVALID_REQUEST")
    return v


def opt_str(data, key, default=None):
    if key not in data or data[key] is None:
        return default
    v = data[key]
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST")
    return v


def req_int(data, key):
    v = data.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST")
    return v


def opt_int(data, key, default):
    if key not in data or data[key] is None:
        return default
    v = data[key]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST")
    return v


def req_num(data, key):
    v = data.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST")
    return v


def opt_num(data, key, default):
    if key not in data or data[key] is None:
        return default
    v = data[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST")
    return v


def req_enum(data, key, allowed):
    v = req_str(data, key)
    if v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST")
    return v


def opt_enum(data, key, allowed, default):
    if key not in data or data[key] is None:
        return default
    v = data[key]
    if not isinstance(v, str) or v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST")
    return v


# Rounding helpers
def round_hu(value, places):
    q = Decimal(1).scaleb(-places)  # 10^-places
    return Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)


def round_hu_float(value, places):
    return float(round_hu(value, places))


# ===========================================================================
# Public serializers (return public field views)
# ===========================================================================

def view_school(s):
    return {
        "id": s["id"], "created_at": s["created_at"], "updated_at": s["updated_at"],
        "version": s["version"], "name": s["name"], "state_code": s["state_code"],
        "ada_method": s["ada_method"], "minimum_daily_minutes": s["minimum_daily_minutes"],
        "current_school_day_index": s["current_school_day_index"],
        "session_total_days": s["session_total_days"],
    }


def view_student(s):
    return {
        "id": s["id"], "created_at": s["created_at"], "updated_at": s["updated_at"],
        "version": s["version"], "school_id": s["school_id"],
        "state_student_id": s["state_student_id"], "first_name": s["first_name"],
        "last_name": s["last_name"], "grade_level": s["grade_level"],
        "birth_date": s["birth_date"], "status": s["status"],
        "guardian_user_ids": list(s["guardian_user_ids"]),
    }


def view_enrollment(e):
    return {
        "id": e["id"], "created_at": e["created_at"], "updated_at": e["updated_at"],
        "version": e["version"], "student_id": e["student_id"], "school_id": e["school_id"],
        "entry_day_index": e["entry_day_index"], "exit_day_index": e["exit_day_index"],
        "fte": e["fte"], "membership_days": e["membership_days"],
        "present_days": e["present_days"], "status": e["status"],
    }


def view_course(c):
    return {
        "id": c["id"], "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"], "school_id": c["school_id"],
        "course_code": c["course_code"], "title": c["title"],
        "credit_value": c["credit_value"], "grading_mode": c["grading_mode"],
    }


def view_section(s):
    return {
        "id": s["id"], "created_at": s["created_at"], "updated_at": s["updated_at"],
        "version": s["version"], "course_id": s["course_id"], "school_id": s["school_id"],
        "teacher_user_id": s["teacher_user_id"], "period": s["period"],
        "meeting_minutes": s["meeting_minutes"], "capacity": s["capacity"],
        "enrolled_count": s["enrolled_count"], "status": s["status"],
    }


def view_assignment(a):
    return {
        "id": a["id"], "created_at": a["created_at"], "updated_at": a["updated_at"],
        "version": a["version"], "enrollment_id": a["enrollment_id"],
        "section_id": a["section_id"], "period": a["period"], "status": a["status"],
    }


def view_attendance(r):
    return {
        "id": r["id"], "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"], "schedule_assignment_id": r["schedule_assignment_id"],
        "enrollment_id": r["enrollment_id"], "day_index": r["day_index"],
        "period": r["period"], "code": r["code"], "source": r["source"],
        "present_minutes": r["present_minutes"], "status": r["status"],
    }


def view_daily(d):
    return {
        "id": d["id"], "created_at": d["created_at"], "updated_at": d["updated_at"],
        "version": d["version"], "enrollment_id": d["enrollment_id"],
        "day_index": d["day_index"], "present_minutes_total": d["present_minutes_total"],
        "daily_code": d["daily_code"], "ada_eligible": d["ada_eligible"],
    }


def view_score(s):
    return {
        "id": s["id"], "created_at": s["created_at"], "updated_at": s["updated_at"],
        "version": s["version"], "schedule_assignment_id": s["schedule_assignment_id"],
        "section_id": s["section_id"], "standard_code": s["standard_code"],
        "weight": s["weight"], "mastery_level": s["mastery_level"],
        "percentage_points": s["percentage_points"],
    }


def view_report_card(rc, compute=True):
    out = {
        "id": rc["id"], "created_at": rc["created_at"], "updated_at": rc["updated_at"],
        "version": rc["version"], "enrollment_id": rc["enrollment_id"],
        "term_label": rc["term_label"], "status": rc["status"],
        "overall_gpa": rc["overall_gpa"], "credits_earned": rc["credits_earned"],
        "line_items": rc["line_items"],
    }
    if compute and rc["status"] in ("DRAFT", "REOPENED"):
        # A draft computes its preview on read.
        gpa, credits, items = compute_report_card(rc["enrollment_id"])
        out["overall_gpa"] = gpa
        out["credits_earned"] = credits
        out["line_items"] = items
    return out


def view_incident(i):
    return {
        "id": i["id"], "created_at": i["created_at"], "updated_at": i["updated_at"],
        "version": i["version"], "enrollment_id": i["enrollment_id"],
        "referring_user_id": i["referring_user_id"], "category": i["category"],
        "severity": i["severity"], "incident_day_index": i["incident_day_index"],
        "adjudicator_user_id": i["adjudicator_user_id"], "status": i["status"],
    }


def view_consequence(c):
    return {
        "id": c["id"], "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"], "incident_id": c["incident_id"],
        "enrollment_id": c["enrollment_id"], "type": c["type"],
        "start_day_index": c["start_day_index"], "duration_days": c["duration_days"],
        "absence_code_applied": c["absence_code_applied"], "status": c["status"],
    }


def view_ada(r):
    return {
        "id": r["id"], "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"], "school_id": r["school_id"],
        "as_of_day_index": r["as_of_day_index"], "method_used": r["method_used"],
        "total_ada": r["total_ada"], "funded_enrollment_count": r["funded_enrollment_count"],
        "certifier_user_id": r["certifier_user_id"], "drafter_user_id": r["drafter_user_id"],
        "status": r["status"],
    }


# ===========================================================================
# Derived-field computation engine
# ===========================================================================

def enrollment_window_upper(enr, school):
    """One-past upper edge of the enrollment's active window."""
    if enr["status"] == "WITHDRAWN":
        return enr["exit_day_index"]
    if enr["status"] == "NO_SHOW":
        return enr["exit_day_index"]
    return school["current_school_day_index"] + 1


def assignments_of_enrollment(enrollment_id):
    return [a for a in db.schedule_assignments.values()
            if a["enrollment_id"] == enrollment_id]


def recompute_daily(enrollment_id, day_index):
    """Daily rollup for one (enrollment, day). Creates/updates the DailyAttendance row."""
    enr = db.enrollments[enrollment_id]
    school = db.schools[enr["school_id"]]

    # Scope: RECORDED records for this enrollment+day.
    recs = [r for r in db.attendance_records.values()
            if r["enrollment_id"] == enrollment_id
            and r["day_index"] == day_index
            and r["status"] == "RECORDED"]

    present_minutes_total = sum(r["present_minutes"] for r in recs)

    # expected_minutes: sum of meeting_minutes over enrollment's ENROLLED assignments
    # whose section period has any RECORDED record that day.
    periods_with_records = set(r["period"] for r in recs)
    expected_minutes = 0
    for a in assignments_of_enrollment(enrollment_id):
        if a["status"] != "ENROLLED":
            continue
        sec = db.sections[a["section_id"]]
        if sec["period"] in periods_with_records:
            expected_minutes += sec["meeting_minutes"]

    if not recs:
        daily_code = "ABSENT"
    elif present_minutes_total == 0:
        daily_code = "ABSENT"
    elif present_minutes_total >= expected_minutes and expected_minutes > 0:
        daily_code = "PRESENT"
    else:
        daily_code = "PARTIAL"

    # ADA eligibility per the school's funding method.
    if school["ada_method"] == "AGGREGATE_MEMBERSHIP":
        ada_eligible = (daily_code != "ABSENT")
    else:  # DAYS_PRESENT
        ada_eligible = (present_minutes_total >= school["minimum_daily_minutes"])

    key = (enrollment_id, day_index)
    existing = db.daily_attendance.get(key)
    if existing is None:
        d = {
            "enrollment_id": enrollment_id,
            "day_index": day_index,
            "present_minutes_total": present_minutes_total,
            "daily_code": daily_code,
            "ada_eligible": ada_eligible,
        }
        stamp_new(d)
        db.daily_attendance[key] = d
    else:
        changed = (existing["present_minutes_total"] != present_minutes_total
                   or existing["daily_code"] != daily_code
                   or existing["ada_eligible"] != ada_eligible)
        existing["present_minutes_total"] = present_minutes_total
        existing["daily_code"] = daily_code
        existing["ada_eligible"] = ada_eligible
        if changed:
            touch(existing)


def recompute_present_days(enrollment_id):
    enr = db.enrollments[enrollment_id]
    school = db.schools[enr["school_id"]]
    upper = enrollment_window_upper(enr, school)
    count = 0
    for (eid, day_index), d in db.daily_attendance.items():
        if eid != enrollment_id:
            continue
        if not d["ada_eligible"]:
            continue
        if enr["entry_day_index"] <= day_index < upper:
            count += 1
    if enr["present_days"] != count:
        enr["present_days"] = count
        touch(enr)


# ===========================================================================
# Report card grade computation
# ===========================================================================

def grade_section(section, scores):
    """Return (letter_grade, grade_points, mastery_or_percent, passed)."""
    course = db.courses[section["course_id"]]
    total_w = sum(Decimal(str(s["weight"])) for s in scores)
    if total_w == 0:
        total_w = Decimal("1")

    if course["grading_mode"] == "STANDARDS":
        num = sum(Decimal(str(s["weight"])) * Decimal(str(s["mastery_level"])) for s in scores)
        wm = num / total_w
        wm_f = float(round_hu(wm, 2))
        if wm >= Decimal("3.5"):
            letter, points = "A", 4.0
        elif wm >= Decimal("3.0"):
            letter, points = "B", 3.0
        elif wm >= Decimal("2.5"):
            letter, points = "C", 2.0
        elif wm >= Decimal("2.0"):
            letter, points = "D", 1.0
        else:
            letter, points = "F", 0.0
        passed = wm >= Decimal("2.0")
        return letter, points, wm_f, passed
    else:  # TRADITIONAL
        num = sum(Decimal(str(s["weight"])) * Decimal(str(s["percentage_points"] or 0))
                  for s in scores)
        wp = num / total_w
        wp_f = float(round_hu(wp, 2))
        if wp >= Decimal("90"):
            letter, points = "A", 4.0
        elif wp >= Decimal("80"):
            letter, points = "B", 3.0
        elif wp >= Decimal("70"):
            letter, points = "C", 2.0
        elif wp >= Decimal("60"):
            letter, points = "D", 1.0
        else:
            letter, points = "F", 0.0
        passed = wp >= Decimal("60")
        return letter, points, wp_f, passed


def compute_report_card(enrollment_id):
    """Compute (overall_gpa, credits_earned, line_items) for an enrollment.

    Sections accumulated in ascending created_at order of their ScheduleAssignment.
    Only ENROLLED assignments that have >=1 StandardScore are graded.
    """
    assigns = [a for a in assignments_of_enrollment(enrollment_id)
               if a["status"] == "ENROLLED"]
    assigns = sorted_by_created(assigns)

    line_items = []
    weighted_sum = Decimal("0")   # sum(credit_value * grade_points)
    credit_sum = Decimal("0")     # sum(credit_value) over graded sections
    credits_earned = Decimal("0")

    for a in assigns:
        scores = [s for s in db.standard_scores.values()
                  if s["schedule_assignment_id"] == a["id"]]
        if not scores:
            continue
        section = db.sections[a["section_id"]]
        course = db.courses[section["course_id"]]
        letter, points, mastery_or_percent, passed = grade_section(section, scores)
        cv = Decimal(str(course["credit_value"]))
        weighted_sum += cv * Decimal(str(points))
        credit_sum += cv
        if passed:
            credits_earned += cv
        line_items.append({
            "section_id": section["id"],
            "course_code": course["course_code"],
            "grading_mode": course["grading_mode"],
            "letter_grade": letter,
            "grade_points": points,
            "mastery_or_percent": mastery_or_percent,
            "passed": passed,
        })

    if credit_sum > 0:
        overall_gpa = float(round_hu(weighted_sum / credit_sum, 2))
    else:
        overall_gpa = None

    return overall_gpa, _num(credits_earned), line_items


def _num(dec):
    """Render a Decimal as int when integral, else float."""
    if dec == dec.to_integral_value():
        return int(dec)
    return float(dec)


# ===========================================================================
# ADA funding computation
# ===========================================================================

def compute_ada(school, as_of_day_index):
    """Return (total_ada, funded_enrollment_count, method_used)."""
    method = school["ada_method"]
    session_total_days = Decimal(str(school["session_total_days"]))

    scope = [e for e in db.enrollments.values()
             if e["school_id"] == school["id"]
             and e["entry_day_index"] <= as_of_day_index
             and e["status"] != "NO_SHOW"]

    per_enrollment = []
    for e in scope:
        # span(e) = min(as_of+1, exit_or_now(e)) - entry, clamped >= 0
        upper = enrollment_window_upper(e, school)
        span = min(as_of_day_index + 1, upper) - e["entry_day_index"]
        if span < 0:
            span = 0

        if method == "AGGREGATE_MEMBERSHIP":
            numerator = Decimal(span)
        else:  # DAYS_PRESENT
            present = present_days_through(e, as_of_day_index)
            numerator = Decimal(present)

        if session_total_days == 0:
            ada = Decimal("0")
        else:
            ada = round_hu(
                (numerator / session_total_days) * Decimal(str(e["fte"])), 4)
        per_enrollment.append(ada)

    total = round_hu(sum(per_enrollment, Decimal("0")), 4)
    funded = sum(1 for a in per_enrollment if a > 0)
    return _num(total), funded, method


def present_days_through(enr, as_of_day_index):
    """Count of the enrollment's ada-eligible present days with day_index <= as_of."""
    count = 0
    for (eid, day_index), d in db.daily_attendance.items():
        if eid != enr["id"]:
            continue
        if d["ada_eligible"] and day_index <= as_of_day_index:
            count += 1
    return count


# ===========================================================================
# ROUTES
# ===========================================================================

# ---- Schools + clock ----

@app.route("/schools", methods=["POST"])
def create_school():
    require_roles({"Registrar"})
    data = body()
    name = req_str(data, "name")
    state_code = req_str(data, "state_code")
    ada_method = opt_enum(data, "ada_method",
                          {"AGGREGATE_MEMBERSHIP", "DAYS_PRESENT"}, "AGGREGATE_MEMBERSHIP")
    minimum_daily_minutes = opt_int(data, "minimum_daily_minutes", 240)
    session_total_days = opt_int(data, "session_total_days", 180)
    s = {
        "name": name, "state_code": state_code, "ada_method": ada_method,
        "minimum_daily_minutes": minimum_daily_minutes,
        "current_school_day_index": 0, "session_total_days": session_total_days,
    }
    stamp_new(s)
    db.schools[s["id"]] = s
    return success(view_school(s), status=201)


@app.route("/schools/<school_id>", methods=["GET"])
def get_school(school_id):
    require_roles({"Registrar", "Teacher", "Administrator", "StateReportingOfficer", "Parent"})
    s = find(db.schools, "school", school_id)
    return success(view_school(s))


@app.route("/schools/<school_id>/clock/advance", methods=["POST"])
def advance_clock(school_id):
    require_roles({"Registrar"})
    s = find(db.schools, "school", school_id)
    data = body()
    by_days = req_int(data, "by_days")
    if by_days < 1 or by_days > 10000:
        raise ApiError("ERR_INVALID_REQUEST")
    s["current_school_day_index"] += by_days
    touch(s)
    return success(view_school(s))


# ---- Students ----

VALID_GRADES = {"K", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"}


@app.route("/students", methods=["POST"])
def create_student():
    require_roles({"Registrar"})
    data = body()
    school_id = req_str(data, "school_id")
    state_student_id = req_str(data, "state_student_id")
    first_name = req_str(data, "first_name")
    last_name = req_str(data, "last_name")
    grade_level = req_str(data, "grade_level")
    birth_date = req_str(data, "birth_date")
    if grade_level not in VALID_GRADES:
        raise ApiError("ERR_INVALID_REQUEST")
    find(db.schools, "school", school_id)
    # Uniqueness of state_student_id within the school.
    for st in db.students.values():
        if st["school_id"] == school_id and st["state_student_id"] == state_student_id:
            raise ApiError("ERR_DUPLICATE_STATE_STUDENT_ID")
    s = {
        "school_id": school_id, "state_student_id": state_student_id,
        "first_name": first_name, "last_name": last_name,
        "grade_level": grade_level, "birth_date": birth_date,
        "status": "PROSPECTIVE", "guardian_user_ids": set(),
    }
    stamp_new(s)
    db.students[s["id"]] = s
    return success(view_student(s), status=201)


@app.route("/students", methods=["GET"])
def list_students():
    require_roles({"Registrar", "Administrator", "Teacher", "StateReportingOfficer"})
    items = list(db.students.values())
    school_id = request.args.get("school_id")
    status = request.args.get("status")
    if school_id is not None:
        items = [s for s in items if s["school_id"] == school_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items = sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return list_response([view_student(s) for s in page], total, limit, offset)


def guardian_check(student):
    if g.user_role == "Parent":
        if g.user_id not in student["guardian_user_ids"]:
            raise ApiError("ERR_NOT_GUARDIAN_OF_STUDENT")


@app.route("/students/<student_id>", methods=["GET"])
def get_student(student_id):
    require_roles({"Registrar", "Administrator", "Teacher", "StateReportingOfficer", "Parent"})
    s = find(db.students, "student", student_id)
    guardian_check(s)
    return success(view_student(s))


@app.route("/students/<student_id>/portal-summary", methods=["GET"])
def portal_summary(student_id):
    require_roles({"Parent", "Registrar", "Administrator"})
    s = find(db.students, "student", student_id)
    guardian_check(s)
    # Gather: demographics, current grades, attendance present-day count, open incidents.
    enrollments = [e for e in db.enrollments.values() if e["student_id"] == student_id]
    present_days = sum(e["present_days"] for e in enrollments)
    enr_ids = {e["id"] for e in enrollments}
    open_incidents = [view_incident(i) for i in sorted_by_created(
        [i for i in db.discipline_incidents.values()
         if i["enrollment_id"] in enr_ids
         and i["status"] in ("REFERRED", "UNDER_REVIEW")])]
    current_grades = []
    for e in enrollments:
        gpa, credits, items = compute_report_card(e["id"])
        current_grades.append({
            "enrollment_id": e["id"], "overall_gpa": gpa,
            "credits_earned": credits, "line_items": items,
        })
    out = view_student(s)
    out["present_days"] = present_days
    out["current_grades"] = current_grades
    out["open_incidents"] = open_incidents
    return success(out)


@app.route("/students/<student_id>/guardians", methods=["POST"])
def link_guardian(student_id):
    require_roles({"Registrar"})
    s = find(db.students, "student", student_id)
    data = body()
    guardian_user_id = req_str(data, "guardian_user_id")
    s["guardian_user_ids"].add(guardian_user_id)
    touch(s)
    return success(view_student(s), status=201)


# ---- Enrollments ----

@app.route("/enrollments", methods=["POST"])
def create_enrollment():
    require_roles({"Registrar"})
    data = body()
    student_id = req_str(data, "student_id")
    entry_day_index = req_int(data, "entry_day_index")
    fte = opt_num(data, "fte", 1.0)
    if not (0 < fte <= 1.0):
        raise ApiError("ERR_INVALID_REQUEST")
    student = find(db.students, "student", student_id)
    e = {
        "student_id": student_id, "school_id": student["school_id"],
        "entry_day_index": entry_day_index, "exit_day_index": None,
        "fte": fte, "membership_days": 0, "present_days": 0, "status": "ACTIVE",
    }
    stamp_new(e)
    db.enrollments[e["id"]] = e
    if student["status"] != "ENROLLED":
        student["status"] = "ENROLLED"
        touch(student)
    return success(view_enrollment(e), status=201)


@app.route("/enrollments", methods=["GET"])
def list_enrollments():
    require_roles({"Registrar", "Administrator", "StateReportingOfficer"})
    items = list(db.enrollments.values())
    student_id = request.args.get("student_id")
    school_id = request.args.get("school_id")
    status = request.args.get("status")
    if student_id is not None:
        items = [e for e in items if e["student_id"] == student_id]
    if school_id is not None:
        items = [e for e in items if e["school_id"] == school_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    items = sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return list_response([view_enrollment(e) for e in page], total, limit, offset)


@app.route("/enrollments/<enrollment_id>", methods=["GET"])
def get_enrollment(enrollment_id):
    require_roles({"Registrar", "Administrator", "StateReportingOfficer", "Teacher"})
    e = find(db.enrollments, "enrollment", enrollment_id)
    return success(view_enrollment(e))


def drop_enrollment_assignments(enrollment_id):
    for a in assignments_of_enrollment(enrollment_id):
        if a["status"] == "ENROLLED":
            a["status"] = "DROPPED"
            touch(a)
            sec = db.sections[a["section_id"]]
            sec["enrolled_count"] -= 1
            touch(sec)


def maybe_withdraw_student(student_id):
    has_active = any(e["student_id"] == student_id and e["status"] == "ACTIVE"
                     for e in db.enrollments.values())
    if not has_active:
        student = db.students.get(student_id)
        if student and student["status"] != "WITHDRAWN":
            student["status"] = "WITHDRAWN"
            touch(student)


@app.route("/enrollments/<enrollment_id>/withdraw", methods=["POST"])
def withdraw_enrollment(enrollment_id):
    require_roles({"Registrar"})
    e = find(db.enrollments, "enrollment", enrollment_id)
    data = body()
    if e["status"] != "ACTIVE":
        raise ApiError("ERR_ENROLLMENT_NOT_ACTIVE")
    exit_day_index = req_int(data, "exit_day_index")
    school = db.schools[e["school_id"]]
    if exit_day_index < e["entry_day_index"]:
        raise ApiError("ERR_INVALID_EXIT_DAY")
    if exit_day_index > school["current_school_day_index"]:
        raise ApiError("ERR_EXIT_DAY_IN_FUTURE")
    e["status"] = "WITHDRAWN"
    e["exit_day_index"] = exit_day_index
    e["membership_days"] = max(0, exit_day_index - e["entry_day_index"])
    touch(e)
    drop_enrollment_assignments(enrollment_id)
    recompute_present_days(enrollment_id)
    maybe_withdraw_student(e["student_id"])
    return success(view_enrollment(e))


@app.route("/enrollments/<enrollment_id>/mark-no-show", methods=["POST"])
def mark_no_show(enrollment_id):
    require_roles({"Registrar"})
    e = find(db.enrollments, "enrollment", enrollment_id)
    if e["status"] != "ACTIVE":
        raise ApiError("ERR_ENROLLMENT_NOT_ACTIVE")
    has_present = any(r["enrollment_id"] == enrollment_id and r["code"] == "PRESENT"
                      for r in db.attendance_records.values())
    if has_present:
        raise ApiError("ERR_PRESENCE_ON_RECORD")
    e["status"] = "NO_SHOW"
    e["membership_days"] = 0
    e["present_days"] = 0
    e["exit_day_index"] = e["entry_day_index"]
    touch(e)
    drop_enrollment_assignments(enrollment_id)
    maybe_withdraw_student(e["student_id"])
    return success(view_enrollment(e))


@app.route("/enrollments/<enrollment_id>/daily-attendance", methods=["GET"])
def list_daily_attendance(enrollment_id):
    require_roles({"Registrar", "Administrator", "StateReportingOfficer", "Teacher", "Parent"})
    e = find(db.enrollments, "enrollment", enrollment_id)
    if g.user_role == "Parent":
        student = db.students.get(e["student_id"])
        guardian_check(student)
    items = [d for (eid, di), d in db.daily_attendance.items() if eid == enrollment_id]
    day_index = request.args.get("day_index")
    if day_index is not None:
        try:
            di = int(day_index)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST")
        items = [d for d in items if d["day_index"] == di]
    items = sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return list_response([view_daily(d) for d in page], total, limit, offset)


# ---- Courses ----

@app.route("/courses", methods=["POST"])
def create_course():
    require_roles({"Registrar"})
    data = body()
    school_id = req_str(data, "school_id")
    course_code = req_str(data, "course_code")
    title = req_str(data, "title")
    credit_value = opt_num(data, "credit_value", 1.0)
    grading_mode = opt_enum(data, "grading_mode", {"STANDARDS", "TRADITIONAL"}, "STANDARDS")
    find(db.schools, "school", school_id)
    for c in db.courses.values():
        if c["school_id"] == school_id and c["course_code"] == course_code:
            raise ApiError("ERR_DUPLICATE_COURSE_CODE")
    c = {
        "school_id": school_id, "course_code": course_code, "title": title,
        "credit_value": credit_value, "grading_mode": grading_mode,
    }
    stamp_new(c)
    db.courses[c["id"]] = c
    return success(view_course(c), status=201)


@app.route("/courses", methods=["GET"])
def list_courses():
    require_roles({"Registrar", "Administrator", "Teacher"})
    items = list(db.courses.values())
    school_id = request.args.get("school_id")
    if school_id is not None:
        items = [c for c in items if c["school_id"] == school_id]
    items = sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return list_response([view_course(c) for c in page], total, limit, offset)


@app.route("/courses/<course_id>", methods=["GET"])
def get_course(course_id):
    require_roles({"Registrar", "Administrator", "Teacher"})
    c = find(db.courses, "course", course_id)
    return success(view_course(c))


# ---- Sections ----

@app.route("/sections", methods=["POST"])
def create_section():
    require_roles({"Registrar"})
    data = body()
    course_id = req_str(data, "course_id")
    teacher_user_id = req_str(data, "teacher_user_id")
    period = req_int(data, "period")
    meeting_minutes = opt_int(data, "meeting_minutes", 50)
    capacity = opt_int(data, "capacity", 30)
    if period < 1 or period > 8:
        raise ApiError("ERR_INVALID_REQUEST")
    course = find(db.courses, "course", course_id)
    s = {
        "course_id": course_id, "school_id": course["school_id"],
        "teacher_user_id": teacher_user_id, "period": period,
        "meeting_minutes": meeting_minutes, "capacity": capacity,
        "enrolled_count": 0, "status": "OPEN",
    }
    stamp_new(s)
    db.sections[s["id"]] = s
    return success(view_section(s), status=201)


@app.route("/sections", methods=["GET"])
def list_sections():
    require_roles({"Registrar", "Administrator", "Teacher"})
    items = list(db.sections.values())
    course_id = request.args.get("course_id")
    school_id = request.args.get("school_id")
    period = request.args.get("period")
    if course_id is not None:
        items = [s for s in items if s["course_id"] == course_id]
    if school_id is not None:
        items = [s for s in items if s["school_id"] == school_id]
    if period is not None:
        try:
            p = int(period)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST")
        items = [s for s in items if s["period"] == p]
    items = sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return list_response([view_section(s) for s in page], total, limit, offset)


@app.route("/sections/<section_id>", methods=["GET"])
def get_section(section_id):
    require_roles({"Registrar", "Administrator", "Teacher"})
    s = find(db.sections, "section", section_id)
    return success(view_section(s))


@app.route("/sections/<section_id>/close", methods=["POST"])
def close_section(section_id):
    require_roles({"Registrar"})
    s = find(db.sections, "section", section_id)
    if s["status"] != "OPEN":
        raise ApiError("ERR_SECTION_NOT_OPEN")
    s["status"] = "CLOSED"
    touch(s)
    return success(view_section(s))


@app.route("/sections/<section_id>/reopen", methods=["POST"])
def reopen_section(section_id):
    require_roles({"Registrar"})
    s = find(db.sections, "section", section_id)
    if s["status"] != "CLOSED":
        raise ApiError("ERR_SECTION_NOT_CLOSED")
    s["status"] = "OPEN"
    touch(s)
    return success(view_section(s))


@app.route("/sections/<section_id>/schedule-assignments", methods=["GET"])
def list_section_assignments(section_id):
    require_roles({"Registrar", "Administrator", "Teacher"})
    find(db.sections, "section", section_id)
    items = [a for a in db.schedule_assignments.values() if a["section_id"] == section_id]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items = sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return list_response([view_assignment(a) for a in page], total, limit, offset)


# ---- Schedule assignments ----

@app.route("/schedule-assignments", methods=["POST"])
def create_assignment():
    require_roles({"Registrar"})
    data = body()
    enrollment_id = req_str(data, "enrollment_id")
    section_id = req_str(data, "section_id")
    enr = find(db.enrollments, "enrollment", enrollment_id)
    sec = find(db.sections, "section", section_id)
    # ERR_PARENT_NOT_ACTIVE: enrollment must be ACTIVE and section OPEN.
    if enr["status"] != "ACTIVE" or sec["status"] != "OPEN":
        raise ApiError("ERR_PARENT_NOT_ACTIVE")
    # Period-exclusive overlap.
    for a in assignments_of_enrollment(enrollment_id):
        if a["status"] == "ENROLLED" and a["period"] == sec["period"]:
            raise ApiError("ERR_SCHEDULE_PERIOD_CONFLICT")
    # Capacity: ENROLLED assignments must not exceed capacity.
    if sec["enrolled_count"] + 1 > sec["capacity"]:
        raise ApiError("ERR_SECTION_CAPACITY_EXCEEDED")
    a = {
        "enrollment_id": enrollment_id, "section_id": section_id,
        "period": sec["period"], "status": "ENROLLED",
    }
    stamp_new(a)
    db.schedule_assignments[a["id"]] = a
    sec["enrolled_count"] += 1
    touch(sec)
    return success(view_assignment(a), status=201)


@app.route("/schedule-assignments", methods=["GET"])
def list_assignments():
    require_roles({"Registrar", "Administrator", "Teacher"})
    items = list(db.schedule_assignments.values())
    enrollment_id = request.args.get("enrollment_id")
    section_id = request.args.get("section_id")
    status = request.args.get("status")
    if enrollment_id is not None:
        items = [a for a in items if a["enrollment_id"] == enrollment_id]
    if section_id is not None:
        items = [a for a in items if a["section_id"] == section_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items = sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return list_response([view_assignment(a) for a in page], total, limit, offset)


@app.route("/schedule-assignments/<assignment_id>", methods=["GET"])
def get_assignment(assignment_id):
    require_roles({"Registrar", "Administrator", "Teacher"})
    a = find(db.schedule_assignments, "schedule_assignment", assignment_id)
    return success(view_assignment(a))


@app.route("/schedule-assignments/<assignment_id>/drop", methods=["POST"])
def drop_assignment(assignment_id):
    require_roles({"Registrar"})
    a = find(db.schedule_assignments, "schedule_assignment", assignment_id)
    if a["status"] == "ENROLLED":
        a["status"] = "DROPPED"
        touch(a)
        sec = db.sections[a["section_id"]]
        sec["enrolled_count"] -= 1
        touch(sec)
    else:
        a["status"] = "DROPPED"
        touch(a)
    return success(view_assignment(a))


# ---- Attendance ----

ATTENDANCE_CODES = {"PRESENT", "ABSENT_EXCUSED", "ABSENT_UNEXCUSED", "TARDY"}


def attendance_window_ok(enr, school, day_index):
    if day_index < enr["entry_day_index"]:
        return False
    if day_index > school["current_school_day_index"]:
        return False
    if enr["status"] == "WITHDRAWN" and enr["exit_day_index"] is not None:
        if day_index >= enr["exit_day_index"]:
            return False
    return True


def present_minutes_for(section, code):
    return section["meeting_minutes"] if code in ("PRESENT", "TARDY") else 0


@app.route("/attendance-records", methods=["POST"])
def create_attendance():
    require_roles({"Teacher", "Registrar"})
    data = body()
    schedule_assignment_id = req_str(data, "schedule_assignment_id")
    day_index = req_int(data, "day_index")
    code = req_enum(data, "code", ATTENDANCE_CODES)
    assignment = find(db.schedule_assignments, "schedule_assignment", schedule_assignment_id)
    enr = db.enrollments[assignment["enrollment_id"]]
    school = db.schools[enr["school_id"]]
    # Validation ordering (§2.12 final tier, scaffold priority): the attendance
    # window check (priority 10) precedes the parent-active check (priority 13).
    # The window rule explicitly handles the WITHDRAWN case ("strictly below
    # exit_day_index when the enrollment is WITHDRAWN", §3.5), so a WITHDRAWN
    # enrollment posting outside its window surfaces ERR_ATTENDANCE_OUTSIDE_WINDOW
    # before ERR_PARENT_NOT_ACTIVE.
    if not attendance_window_ok(enr, school, day_index):
        raise ApiError("ERR_ATTENDANCE_OUTSIDE_WINDOW")
    # ERR_PARENT_NOT_ACTIVE: attendance only against ACTIVE enrollment.
    if enr["status"] != "ACTIVE":
        raise ApiError("ERR_PARENT_NOT_ACTIVE")
    section = db.sections[assignment["section_id"]]
    r = {
        "schedule_assignment_id": schedule_assignment_id,
        "enrollment_id": enr["id"], "day_index": day_index,
        "period": assignment["period"], "code": code, "source": "TEACHER",
        "present_minutes": present_minutes_for(section, code), "status": "RECORDED",
    }
    stamp_new(r)
    db.attendance_records[r["id"]] = r
    recompute_daily(enr["id"], day_index)
    recompute_present_days(enr["id"])
    return success(view_attendance(r), status=201)


@app.route("/attendance-records", methods=["GET"])
def list_attendance():
    require_roles({"Teacher", "Registrar", "Administrator", "StateReportingOfficer"})
    items = list(db.attendance_records.values())
    sa = request.args.get("schedule_assignment_id")
    eid = request.args.get("enrollment_id")
    day_index = request.args.get("day_index")
    status = request.args.get("status")
    if sa is not None:
        items = [r for r in items if r["schedule_assignment_id"] == sa]
    if eid is not None:
        items = [r for r in items if r["enrollment_id"] == eid]
    if day_index is not None:
        try:
            di = int(day_index)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST")
        items = [r for r in items if r["day_index"] == di]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return list_response([view_attendance(r) for r in page], total, limit, offset)


@app.route("/attendance-records/<record_id>", methods=["GET"])
def get_attendance(record_id):
    require_roles({"Teacher", "Registrar", "Administrator", "StateReportingOfficer"})
    r = find(db.attendance_records, "attendance_record", record_id)
    return success(view_attendance(r))


@app.route("/attendance-records/<record_id>/correct", methods=["POST"])
def correct_attendance(record_id):
    require_roles({"Teacher", "Registrar"})
    prior = find(db.attendance_records, "attendance_record", record_id)
    data = body()
    code = req_enum(data, "code", ATTENDANCE_CODES)
    enr = db.enrollments[prior["enrollment_id"]]
    school = db.schools[enr["school_id"]]
    if not attendance_window_ok(enr, school, prior["day_index"]):
        raise ApiError("ERR_ATTENDANCE_OUTSIDE_WINDOW")
    assignment = db.schedule_assignments[prior["schedule_assignment_id"]]
    section = db.sections[assignment["section_id"]]
    prior["status"] = "SUPERSEDED"
    touch(prior)
    r = {
        "schedule_assignment_id": prior["schedule_assignment_id"],
        "enrollment_id": enr["id"], "day_index": prior["day_index"],
        "period": prior["period"], "code": code, "source": "TEACHER",
        "present_minutes": present_minutes_for(section, code), "status": "RECORDED",
    }
    stamp_new(r)
    db.attendance_records[r["id"]] = r
    recompute_daily(enr["id"], prior["day_index"])
    recompute_present_days(enr["id"])
    return success(view_attendance(r), status=201)


# ---- Standards gradebook ----

@app.route("/standard-scores", methods=["POST"])
def create_score():
    require_roles({"Teacher"})
    data = body()
    schedule_assignment_id = req_str(data, "schedule_assignment_id")
    standard_code = req_str(data, "standard_code")
    weight = opt_num(data, "weight", 1.0)
    assignment = find(db.schedule_assignments, "schedule_assignment", schedule_assignment_id)
    enr = db.enrollments[assignment["enrollment_id"]]
    section = db.sections[assignment["section_id"]]
    course = db.courses[section["course_id"]]
    # ERR_PARENT_NOT_ACTIVE: scores only against ACTIVE enrollment.
    if enr["status"] != "ACTIVE":
        raise ApiError("ERR_PARENT_NOT_ACTIVE")
    mastery_level = data.get("mastery_level")
    percentage_points = data.get("percentage_points")
    # Grade-input validation depends on the course grading mode.
    if course["grading_mode"] == "STANDARDS":
        if isinstance(mastery_level, bool) or not isinstance(mastery_level, int) \
                or mastery_level < 1 or mastery_level > 4:
            raise ApiError("ERR_INVALID_GRADE_INPUT")
        pct = percentage_points if isinstance(percentage_points, (int, float)) \
            and not isinstance(percentage_points, bool) else None
    else:  # TRADITIONAL
        if isinstance(percentage_points, bool) or not isinstance(percentage_points, (int, float)) \
                or percentage_points < 0 or percentage_points > 100:
            raise ApiError("ERR_INVALID_GRADE_INPUT")
        pct = percentage_points
        if isinstance(mastery_level, bool) or not isinstance(mastery_level, int):
            mastery_level = None
    # PRD §3.7: scores are *upserted* against (schedule_assignment_id, standard_code).
    # An existing score for that pair is updated in place; otherwise a new one is
    # inserted. This prevents a re-grade of the same standard from accumulating a
    # second score and skewing the section's weighted mastery/percentage.
    existing = next(
        (s for s in db.standard_scores.values()
         if s["schedule_assignment_id"] == schedule_assignment_id
         and s["standard_code"] == standard_code),
        None)
    if existing is not None:
        existing["weight"] = weight
        existing["mastery_level"] = mastery_level
        existing["percentage_points"] = pct
        touch(existing)
        s = existing
        created = False
    else:
        s = {
            "schedule_assignment_id": schedule_assignment_id,
            "section_id": section["id"], "standard_code": standard_code,
            "weight": weight, "mastery_level": mastery_level,
            "percentage_points": pct,
        }
        stamp_new(s)
        db.standard_scores[s["id"]] = s
        created = True
    # Bump version of any DRAFT/REOPENED report card for the enrollment.
    for rc in db.report_cards.values():
        if rc["enrollment_id"] == enr["id"] and rc["status"] in ("DRAFT", "REOPENED"):
            touch(rc)
    return success(view_score(s), status=201 if created else 200)


@app.route("/standard-scores", methods=["GET"])
def list_scores():
    require_roles({"Teacher", "Registrar", "Administrator"})
    items = list(db.standard_scores.values())
    sa = request.args.get("schedule_assignment_id")
    section_id = request.args.get("section_id")
    if sa is not None:
        items = [s for s in items if s["schedule_assignment_id"] == sa]
    if section_id is not None:
        items = [s for s in items if s["section_id"] == section_id]
    items = sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return list_response([view_score(s) for s in page], total, limit, offset)


@app.route("/standard-scores/<score_id>", methods=["GET"])
def get_score(score_id):
    require_roles({"Teacher", "Registrar", "Administrator"})
    s = find(db.standard_scores, "standard_score", score_id)
    return success(view_score(s))


# ---- Report cards ----

@app.route("/report-cards", methods=["POST"])
def create_report_card():
    require_roles({"Teacher", "Registrar"})
    data = body()
    enrollment_id = req_str(data, "enrollment_id")
    term_label = req_str(data, "term_label")
    enr = find(db.enrollments, "enrollment", enrollment_id)
    # ERR_PARENT_NOT_ACTIVE: report card only against ACTIVE enrollment.
    if enr["status"] != "ACTIVE":
        raise ApiError("ERR_PARENT_NOT_ACTIVE")
    rc = {
        "enrollment_id": enrollment_id, "term_label": term_label,
        "overall_gpa": None, "credits_earned": 0, "line_items": [],
        "status": "DRAFT",
    }
    stamp_new(rc)
    db.report_cards[rc["id"]] = rc
    return success(view_report_card(rc), status=201)


@app.route("/report-cards", methods=["GET"])
def list_report_cards():
    require_roles({"Teacher", "Registrar", "Administrator", "Parent"})
    items = list(db.report_cards.values())
    enrollment_id = request.args.get("enrollment_id")
    status = request.args.get("status")
    if enrollment_id is not None:
        items = [rc for rc in items if rc["enrollment_id"] == enrollment_id]
    if status is not None:
        items = [rc for rc in items if rc["status"] == status]
    if g.user_role == "Parent":
        items = [rc for rc in items if parent_owns_enrollment(rc["enrollment_id"])]
    items = sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return list_response([view_report_card(rc) for rc in page], total, limit, offset)


def parent_owns_enrollment(enrollment_id):
    enr = db.enrollments.get(enrollment_id)
    if not enr:
        return False
    student = db.students.get(enr["student_id"])
    return bool(student and g.user_id in student["guardian_user_ids"])


@app.route("/report-cards/<rc_id>", methods=["GET"])
def get_report_card(rc_id):
    require_roles({"Teacher", "Registrar", "Administrator", "Parent"})
    rc = find(db.report_cards, "report_card", rc_id)
    if g.user_role == "Parent":
        enr = db.enrollments.get(rc["enrollment_id"])
        student = db.students.get(enr["student_id"]) if enr else None
        if not student or g.user_id not in student["guardian_user_ids"]:
            raise ApiError("ERR_NOT_GUARDIAN_OF_STUDENT")
    return success(view_report_card(rc))


@app.route("/report-cards/<rc_id>/finalize", methods=["POST"])
def finalize_report_card(rc_id):
    require_roles({"Teacher"})
    rc = find(db.report_cards, "report_card", rc_id)
    data = body()
    # OCC check runs first (after auth/role), before state preconditions.
    expected = data.get("expected_report_card_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError("ERR_INVALID_REQUEST")
    if expected != rc["version"]:
        raise ApiError("ERR_STALE_VERSION")
    if rc["status"] not in ("DRAFT", "REOPENED"):
        raise ApiError("ERR_REPORT_CARD_NOT_DRAFT")
    # Every ENROLLED schedule assignment must have >=1 StandardScore.
    enrolled = [a for a in assignments_of_enrollment(rc["enrollment_id"])
                if a["status"] == "ENROLLED"]
    for a in enrolled:
        has_score = any(s["schedule_assignment_id"] == a["id"]
                        for s in db.standard_scores.values())
        if not has_score:
            raise ApiError("ERR_INCOMPLETE_GRADES")
    gpa, credits, items = compute_report_card(rc["enrollment_id"])
    rc["overall_gpa"] = gpa
    rc["credits_earned"] = credits
    rc["line_items"] = items
    rc["status"] = "FINALIZED"
    touch(rc)
    return success(view_report_card(rc, compute=False))


@app.route("/report-cards/<rc_id>/reopen", methods=["POST"])
def reopen_report_card(rc_id):
    require_roles({"Administrator"})
    rc = find(db.report_cards, "report_card", rc_id)
    if rc["status"] != "FINALIZED":
        raise ApiError("ERR_REPORT_CARD_NOT_FINALIZED")
    rc["status"] = "REOPENED"
    rc["line_items"] = []
    rc["overall_gpa"] = None
    rc["credits_earned"] = 0
    touch(rc)
    return success(view_report_card(rc))


# ---- Discipline incidents ----

INCIDENT_CATEGORIES = {"DISRUPTION", "FIGHTING", "TRUANCY", "ACADEMIC_DISHONESTY", "WEAPON"}


@app.route("/discipline-incidents", methods=["POST"])
def create_incident():
    uid, _role = require_roles({"Teacher", "Administrator"})
    data = body()
    enrollment_id = req_str(data, "enrollment_id")
    category = req_enum(data, "category", INCIDENT_CATEGORIES)
    severity = req_int(data, "severity")
    incident_day_index = req_int(data, "incident_day_index")
    if severity < 1 or severity > 5:
        raise ApiError("ERR_INVALID_REQUEST")
    find(db.enrollments, "enrollment", enrollment_id)
    i = {
        "enrollment_id": enrollment_id, "referring_user_id": uid,
        "category": category, "severity": severity,
        "incident_day_index": incident_day_index,
        "adjudicator_user_id": None, "status": "REFERRED",
    }
    stamp_new(i)
    db.discipline_incidents[i["id"]] = i
    return success(view_incident(i), status=201)


@app.route("/discipline-incidents", methods=["GET"])
def list_incidents():
    require_roles({"Teacher", "Administrator", "Registrar", "Parent"})
    items = list(db.discipline_incidents.values())
    enrollment_id = request.args.get("enrollment_id")
    status = request.args.get("status")
    if enrollment_id is not None:
        items = [i for i in items if i["enrollment_id"] == enrollment_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    if g.user_role == "Parent":
        items = [i for i in items if parent_owns_enrollment(i["enrollment_id"])]
    items = sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return list_response([view_incident(i) for i in page], total, limit, offset)


@app.route("/discipline-incidents/<incident_id>", methods=["GET"])
def get_incident(incident_id):
    require_roles({"Teacher", "Administrator", "Registrar", "Parent"})
    i = find(db.discipline_incidents, "incident", incident_id)
    if g.user_role == "Parent":
        if not parent_owns_enrollment(i["enrollment_id"]):
            raise ApiError("ERR_NOT_GUARDIAN_OF_STUDENT")
    return success(view_incident(i))


@app.route("/discipline-incidents/<incident_id>/begin-review", methods=["POST"])
def begin_review(incident_id):
    uid, _role = require_roles({"Administrator"})
    i = find(db.discipline_incidents, "incident", incident_id)
    if i["status"] != "REFERRED":
        raise ApiError("ERR_INCIDENT_NOT_REFERRED")
    if uid == i["referring_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    i["status"] = "UNDER_REVIEW"
    i["adjudicator_user_id"] = uid
    touch(i)
    return success(view_incident(i))


@app.route("/discipline-incidents/<incident_id>/adjudicate", methods=["POST"])
def adjudicate(incident_id):
    uid, _role = require_roles({"Administrator"})
    i = find(db.discipline_incidents, "incident", incident_id)
    if i["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INCIDENT_NOT_UNDER_REVIEW")
    if uid != i["adjudicator_user_id"]:
        raise ApiError("ERR_NOT_ASSIGNED_ADJUDICATOR")
    has_consequence = any(c["incident_id"] == incident_id
                          for c in db.discipline_consequences.values())
    if not has_consequence:
        raise ApiError("ERR_NO_CONSEQUENCE_RECORDED")
    i["status"] = "ADJUDICATED"
    touch(i)
    return success(view_incident(i))


@app.route("/discipline-incidents/<incident_id>/dismiss", methods=["POST"])
def dismiss_incident(incident_id):
    uid, _role = require_roles({"Administrator"})
    i = find(db.discipline_incidents, "incident", incident_id)
    if i["status"] not in ("REFERRED", "UNDER_REVIEW"):
        raise ApiError("ERR_INCIDENT_NOT_DISMISSIBLE")
    if uid == i["referring_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    i["status"] = "DISMISSED"
    touch(i)
    # Rescind any still-active consequence of this incident.
    for c in db.discipline_consequences.values():
        if c["incident_id"] == incident_id and c["status"] == "ACTIVE":
            rescind_consequence_internal(c)
    return success(view_incident(i))


# ---- Discipline consequences ----

CONSEQUENCE_TYPES = {"WARNING", "DETENTION", "IN_SCHOOL_SUSPENSION", "OUT_OF_SCHOOL_SUSPENSION"}


@app.route("/discipline-incidents/<incident_id>/consequences", methods=["POST"])
def create_consequence(incident_id):
    uid, _role = require_roles({"Administrator"})
    i = find(db.discipline_incidents, "incident", incident_id)
    data = body()
    ctype = req_enum(data, "type", CONSEQUENCE_TYPES)
    start_day_index = opt_int(data, "start_day_index", None)
    duration_days = opt_int(data, "duration_days", 0)
    if i["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INCIDENT_NOT_UNDER_REVIEW")
    if uid != i["adjudicator_user_id"]:
        raise ApiError("ERR_NOT_ASSIGNED_ADJUDICATOR")
    if ctype == "OUT_OF_SCHOOL_SUSPENSION":
        # WEAPON cap is checked at priority 8 (before the generic invalid check).
        if i["category"] == "WEAPON" and duration_days > 10:
            raise ApiError("ERR_SUSPENSION_CAP_EXCEEDED")
        if duration_days < 1 or start_day_index is None \
                or start_day_index < i["incident_day_index"]:
            raise ApiError("ERR_INVALID_CONSEQUENCE")
    c = {
        "incident_id": incident_id, "enrollment_id": i["enrollment_id"],
        "type": ctype, "start_day_index": start_day_index,
        "duration_days": duration_days, "absence_code_applied": None,
        "status": "ACTIVE",
    }
    stamp_new(c)
    db.discipline_consequences[c["id"]] = c
    if ctype == "OUT_OF_SCHOOL_SUSPENSION":
        c["absence_code_applied"] = "ABSENT_EXCUSED"
        apply_suspension_cascade(c)
    return success(view_consequence(c), status=201)


def apply_suspension_cascade(consequence):
    enrollment_id = consequence["enrollment_id"]
    start = consequence["start_day_index"]
    duration = consequence["duration_days"]
    enr = db.enrollments[enrollment_id]
    section_minutes_cache = {}
    affected = set()
    for d in range(start, start + duration):
        for a in assignments_of_enrollment(enrollment_id):
            if a["status"] != "ENROLLED":
                continue
            # Supersede any existing RECORDED record for that assignment+day.
            for r in db.attendance_records.values():
                if r["schedule_assignment_id"] == a["id"] \
                        and r["day_index"] == d and r["status"] == "RECORDED":
                    r["status"] = "SUPERSEDED"
                    touch(r)
            new_rec = {
                "schedule_assignment_id": a["id"], "enrollment_id": enrollment_id,
                "day_index": d, "period": a["period"], "code": "ABSENT_EXCUSED",
                "source": "SYSTEM_SUSPENSION", "present_minutes": 0,
                "status": "RECORDED",
            }
            stamp_new(new_rec)
            new_rec["consequence_id"] = consequence["id"]
            db.attendance_records[new_rec["id"]] = new_rec
            affected.add(d)
    for d in affected:
        recompute_daily(enrollment_id, d)
    recompute_present_days(enrollment_id)


def rescind_consequence_internal(consequence):
    consequence["status"] = "RESCINDED"
    touch(consequence)
    enrollment_id = consequence["enrollment_id"]
    affected = set()
    # Delete every SYSTEM_SUSPENSION record this consequence created and still RECORDED.
    to_delete = []
    for rid, r in db.attendance_records.items():
        if r.get("consequence_id") == consequence["id"] \
                and r["source"] == "SYSTEM_SUSPENSION" and r["status"] == "RECORDED":
            to_delete.append(rid)
            affected.add((r["schedule_assignment_id"], r["day_index"]))
    for rid in to_delete:
        del db.attendance_records[rid]
    # Restore the most recent SUPERSEDED record for each affected assignment+day.
    for (sa_id, day_index) in affected:
        candidates = [r for r in db.attendance_records.values()
                      if r["schedule_assignment_id"] == sa_id
                      and r["day_index"] == day_index
                      and r["status"] == "SUPERSEDED"]
        if candidates:
            latest = sorted(candidates, key=lambda r: (r["created_at"], r["id"]))[-1]
            latest["status"] = "RECORDED"
            touch(latest)
    days = set(d for (_sa, d) in affected)
    for d in days:
        recompute_daily(enrollment_id, d)
    recompute_present_days(enrollment_id)


@app.route("/discipline-incidents/<incident_id>/consequences", methods=["GET"])
def list_incident_consequences(incident_id):
    require_roles({"Teacher", "Administrator", "Registrar", "Parent"})
    i = find(db.discipline_incidents, "incident", incident_id)
    if g.user_role == "Parent":
        if not parent_owns_enrollment(i["enrollment_id"]):
            raise ApiError("ERR_NOT_GUARDIAN_OF_STUDENT")
    items = [c for c in db.discipline_consequences.values() if c["incident_id"] == incident_id]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return list_response([view_consequence(c) for c in page], total, limit, offset)


@app.route("/discipline-consequences", methods=["GET"])
def list_consequences():
    require_roles({"Teacher", "Administrator", "Registrar", "Parent"})
    items = list(db.discipline_consequences.values())
    enrollment_id = request.args.get("enrollment_id")
    incident_id = request.args.get("incident_id")
    status = request.args.get("status")
    if enrollment_id is not None:
        items = [c for c in items if c["enrollment_id"] == enrollment_id]
    if incident_id is not None:
        items = [c for c in items if c["incident_id"] == incident_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if g.user_role == "Parent":
        items = [c for c in items if parent_owns_enrollment(c["enrollment_id"])]
    items = sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return list_response([view_consequence(c) for c in page], total, limit, offset)


@app.route("/discipline-consequences/<consequence_id>", methods=["GET"])
def get_consequence(consequence_id):
    require_roles({"Teacher", "Administrator", "Registrar", "Parent"})
    c = find(db.discipline_consequences, "consequence", consequence_id)
    if g.user_role == "Parent":
        if not parent_owns_enrollment(c["enrollment_id"]):
            raise ApiError("ERR_NOT_GUARDIAN_OF_STUDENT")
    return success(view_consequence(c))


@app.route("/discipline-consequences/<consequence_id>/rescind", methods=["POST"])
def rescind_consequence(consequence_id):
    require_roles({"Administrator"})
    c = find(db.discipline_consequences, "consequence", consequence_id)
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_CONSEQUENCE_NOT_ACTIVE")
    rescind_consequence_internal(c)
    return success(view_consequence(c))


# ---- ADA funding reports ----

@app.route("/ada-funding-reports", methods=["POST"])
def create_ada_report():
    uid, _role = require_roles({"Registrar", "StateReportingOfficer"})
    data = body()
    school_id = req_str(data, "school_id")
    as_of_day_index = req_int(data, "as_of_day_index")
    school = find(db.schools, "school", school_id)
    total_ada, funded, method = compute_ada(school, as_of_day_index)
    r = {
        "school_id": school_id, "as_of_day_index": as_of_day_index,
        "method_used": method, "total_ada": total_ada,
        "funded_enrollment_count": funded, "certifier_user_id": None,
        "drafter_user_id": uid, "status": "DRAFT",
    }
    stamp_new(r)
    db.ada_funding_reports[r["id"]] = r
    return success(view_ada(r), status=201)


@app.route("/ada-funding-reports", methods=["GET"])
def list_ada_reports():
    require_roles({"Registrar", "StateReportingOfficer", "Administrator"})
    items = list(db.ada_funding_reports.values())
    school_id = request.args.get("school_id")
    status = request.args.get("status")
    if school_id is not None:
        items = [r for r in items if r["school_id"] == school_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return list_response([view_ada(r) for r in page], total, limit, offset)


@app.route("/ada-funding-reports/<report_id>", methods=["GET"])
def get_ada_report(report_id):
    require_roles({"Registrar", "StateReportingOfficer", "Administrator"})
    r = find(db.ada_funding_reports, "ada_report", report_id)
    return success(view_ada(r))


@app.route("/ada-funding-reports/<report_id>/recompute", methods=["POST"])
def recompute_ada_report(report_id):
    require_roles({"Registrar", "StateReportingOfficer"})
    r = find(db.ada_funding_reports, "ada_report", report_id)
    if r["status"] != "DRAFT":
        raise ApiError("ERR_REPORT_NOT_DRAFT")
    school = db.schools[r["school_id"]]
    total_ada, funded, _method = compute_ada(school, r["as_of_day_index"])
    r["total_ada"] = total_ada
    r["funded_enrollment_count"] = funded
    touch(r)
    return success(view_ada(r))


@app.route("/ada-funding-reports/<report_id>/certify", methods=["POST"])
def certify_ada_report(report_id):
    uid, _role = require_roles({"StateReportingOfficer"})
    r = find(db.ada_funding_reports, "ada_report", report_id)
    data = body()
    # OCC check first.
    expected = data.get("expected_report_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError("ERR_INVALID_REQUEST")
    if expected != r["version"]:
        raise ApiError("ERR_STALE_VERSION")
    if r["status"] != "DRAFT":
        raise ApiError("ERR_REPORT_NOT_DRAFT")
    if uid == r["drafter_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    # No in-scope ACTIVE enrollment with entry <= as_of yet zero DailyAttendance through as_of.
    as_of = r["as_of_day_index"]
    for e in db.enrollments.values():
        if e["school_id"] != r["school_id"]:
            continue
        if e["status"] != "ACTIVE":
            continue
        if e["entry_day_index"] > as_of:
            continue
        has_daily = any(eid == e["id"] and day <= as_of
                        for (eid, day) in db.daily_attendance.keys())
        if not has_daily:
            raise ApiError("ERR_ATTENDANCE_NOT_POSTED")
    r["status"] = "CERTIFIED"
    r["certifier_user_id"] = uid
    touch(r)
    return success(view_ada(r))


@app.route("/ada-funding-reports/<report_id>/reject", methods=["POST"])
def reject_ada_report(report_id):
    uid, _role = require_roles({"StateReportingOfficer"})
    r = find(db.ada_funding_reports, "ada_report", report_id)
    if r["status"] != "DRAFT":
        raise ApiError("ERR_REPORT_NOT_DRAFT")
    if uid == r["drafter_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    r["status"] = "REJECTED"
    touch(r)
    return success(view_ada(r))


# ---------------------------------------------------------------------------
# Health + entrypoint
# ---------------------------------------------------------------------------

@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
