"""Head Start & Pre-K Enrollment API — Flask application.

In-memory storage only; the store starts empty on every process boot.
"""

import os
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request

import store
from store import (
    programs, cohorts, families, applications, offers, enrollments,
    attendance_records, health_screenings, home_visits, transition_plans,
    pir_reports, clock_now, set_clock, now_iso, new_record, touch,
    offer_expiry, format_dt, _parse_iso,
)
from errors import ApiError, err
import responses

app = Flask(__name__)

KNOWN_ROLES = {"ProgramAdmin", "EnrollmentSpecialist", "FamilyServicesWorker", "Family"}
ALL_ROLES = KNOWN_ROLES

Q4 = Decimal("0.0001")


# ===========================================================================
# Numeric helpers
# ===========================================================================
def ratio4(numer, denom):
    if denom == 0:
        return Decimal("0")
    return (Decimal(numer) / Decimal(denom)).quantize(Q4, rounding=ROUND_HALF_UP)


def age_months(child_dob, cutoff):
    d = datetime.strptime(child_dob, "%Y-%m-%d")
    c = datetime.strptime(cutoff, "%Y-%m-%d")
    months = (c.year - d.year) * 12 + (c.month - d.month)
    if c.day < d.day:
        months -= 1
    return months


def parse_hhmm(value):
    h, m = value.split(":")
    return int(h) * 60 + int(m)


# ===========================================================================
# Auth / authorization / ownership
# ===========================================================================
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in KNOWN_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise err("ERR_UNAUTHORIZED", "Role not permitted for this operation")


def check_owner(role, uid, family_id):
    if role == "Family" and uid != family_id:
        raise err("ERR_NOT_OWNER", "Acting family does not own the target resource")


# ===========================================================================
# Existence helpers
# ===========================================================================
def get_or_404(collection, rid, error_id):
    rec = collection.get(rid)
    if rec is None:
        raise err(error_id, "Resource not found")
    return rec


def resolve_fk(collection, rid, error_id):
    """Resolve a body FK only when it is present; absent -> let validation handle."""
    if rid is None:
        return None
    rec = collection.get(rid)
    if rec is None:
        raise err(error_id, "Referenced resource not found")
    return rec


# ===========================================================================
# Body / query validation helpers  (ERR_VALIDATION is evaluated last)
# ===========================================================================
def get_body():
    raw = request.get_json(silent=True)
    return raw if isinstance(raw, dict) else {}


def v_required(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_VALIDATION", "Missing required field: %s" % field)
    return body[field]


def v_str(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_VALIDATION", "Missing required field: %s" % field)
        return None
    v = body[field]
    if not isinstance(v, str) or v == "":
        raise err("ERR_VALIDATION", "Field %s must be a non-empty string" % field)
    return v


def v_int(body, field, required=True, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_VALIDATION", "Missing required field: %s" % field)
        return None
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_VALIDATION", "Field %s must be an integer" % field)
    if minimum is not None and v < minimum:
        raise err("ERR_VALIDATION", "Field %s below minimum" % field)
    if maximum is not None and v > maximum:
        raise err("ERR_VALIDATION", "Field %s above maximum" % field)
    return v


def v_num(body, field, required=True, minimum=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_VALIDATION", "Missing required field: %s" % field)
        return None
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_VALIDATION", "Field %s must be a number" % field)
    if minimum is not None and v < minimum:
        raise err("ERR_VALIDATION", "Field %s below minimum" % field)
    return v


def v_bool(body, field, required=False, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_VALIDATION", "Missing required field: %s" % field)
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err("ERR_VALIDATION", "Field %s must be a boolean" % field)
    return v


def v_enum(body, field, allowed, required=True):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_VALIDATION", "Missing required field: %s" % field)
        return None
    v = body[field]
    if v not in allowed:
        raise err("ERR_VALIDATION", "Field %s not in allowed domain" % field)
    return v


def v_date(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_VALIDATION", "Missing required field: %s" % field)
        return None
    v = body[field]
    if not isinstance(v, str):
        raise err("ERR_VALIDATION", "Field %s must be a date string" % field)
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        raise err("ERR_VALIDATION", "Field %s must be YYYY-MM-DD" % field)
    return v


def v_time(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_VALIDATION", "Missing required field: %s" % field)
        return None
    v = body[field]
    if not isinstance(v, str):
        raise err("ERR_VALIDATION", "Field %s must be a HH:MM string" % field)
    try:
        parts = v.split(":")
        if len(parts) != 2:
            raise ValueError()
        hh, mm = int(parts[0]), int(parts[1])
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise ValueError()
    except (ValueError, TypeError):
        raise err("ERR_VALIDATION", "Field %s must be a valid HH:MM time" % field)
    return v


# ===========================================================================
# Pagination / listing
# ===========================================================================
def parse_pagination():
    args = request.args
    limit = 10
    if args.get("limit") is not None:
        try:
            limit = int(args.get("limit"))
        except (ValueError, TypeError):
            limit = 10
    limit = max(1, min(100, limit))
    offset = 0
    if args.get("offset") is not None:
        try:
            offset = int(args.get("offset"))
        except (ValueError, TypeError):
            offset = 0
    offset = max(0, offset)
    return limit, offset


def list_response(records, serialize):
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    limit, offset = parse_pagination()
    page = ordered[offset:offset + limit]
    return responses.ok_list([serialize(r) for r in page], limit, offset, total)


# ===========================================================================
# Serialization
# ===========================================================================
def _common(rec, with_version=True):
    out = {"id": rec["id"], "created_at": rec["created_at"]}
    if with_version:
        out["updated_at"] = rec["updated_at"]
        out["version"] = rec["version"]
    return out


def serialize_program(p):
    out = {
        "name": p["name"],
        "program_type": p["program_type"],
        "funded_enrollment": p["funded_enrollment"],
        "age_cutoff_date": p["age_cutoff_date"],
        "total_instructional_days": p["total_instructional_days"],
        "ada_chronic_threshold_pct": p["ada_chronic_threshold_pct"],
    }
    out.update(_common(p))
    return out


def cohort_accounting(c):
    filled = sum(1 for e in enrollments.values()
                 if e["cohort_id"] == c["id"] and e["status"] == "ACTIVE")
    reserved = sum(1 for o in offers.values()
                   if o["cohort_id"] == c["id"] and o["status"] == "PENDING")
    available = c["funded_slots"] - filled - reserved
    if available < 0:
        available = 0
    selection_status = "OPEN" if available > 0 else "FULL"
    return filled, reserved, available, selection_status


def serialize_cohort(c):
    filled, reserved, available, sel = cohort_accounting(c)
    out = {
        "program_id": c["program_id"],
        "age_band": c["age_band"],
        "funded_slots": c["funded_slots"],
        "min_age_months": c["min_age_months"],
        "max_age_months": c["max_age_months"],
        "session_start": c["session_start"],
        "session_end": c["session_end"],
        "filled_slots": filled,
        "reserved_slots": reserved,
        "available_slots": available,
        "selection_status": sel,
    }
    out.update(_common(c))
    return out


def serialize_family(f):
    out = {
        "guardian_name": f["guardian_name"],
        "household_size": f["household_size"],
        "annual_income_cents": f["annual_income_cents"],
        "categorical_eligibility": f["categorical_eligibility"],
        "homeless_status": f["homeless_status"],
    }
    out.update(_common(f))
    return out


def serialize_application(a):
    out = {
        "program_id": a["program_id"],
        "cohort_id": a["cohort_id"],
        "family_id": a["family_id"],
        "child_first_name": a["child_first_name"],
        "child_last_name": a["child_last_name"],
        "child_dob": a["child_dob"],
        "child_has_iep": a["child_has_iep"],
        "verified_income_cents": a["verified_income_cents"],
        "status": a["status"],
        "eligibility_category": a["eligibility_category"],
        "income_ratio": a["income_ratio"],
        "age_months_at_cutoff": a["age_months_at_cutoff"],
        "priority_points": a["priority_points"],
        "submitted_at": a["submitted_at"],
        "waitlisted_at": a["waitlisted_at"],
    }
    out.update(_common(a))
    return out


def serialize_offer(o):
    out = {
        "application_id": o["application_id"],
        "cohort_id": o["cohort_id"],
        "status": o["status"],
        "offered_at": o["offered_at"],
        "offer_expires_at": o["offer_expires_at"],
    }
    out.update(_common(o))
    return out


def compute_ada(e):
    cohort = cohorts[e["cohort_id"]]
    program = programs[cohort["program_id"]]
    recs = [r for r in attendance_records.values()
            if r["enrollment_id"] == e["id"] and r["instructional_day"]]
    inst = len(recs)
    present = sum(1 for r in recs if r["status"] == "PRESENT")
    unexcused = sum(1 for r in recs if r["status"] == "ABSENT_UNEXCUSED")
    ada = ratio4(present, inst) if inst > 0 else Decimal("0")
    ann = ratio4(present, program["total_instructional_days"])
    une = ratio4(unexcused, inst) if inst > 0 else Decimal("0")
    threshold = Decimal(str(program["ada_chronic_threshold_pct"]))
    chronic = une >= threshold
    return {
        "ada_rate": float(ada),
        "annualized_ada_rate": float(ann),
        "unexcused_absence_rate": float(une),
        "chronic_absence": chronic,
        "ada_dec": ada,
    }


def serialize_enrollment(e):
    ada = compute_ada(e)
    out = {
        "application_id": e["application_id"],
        "cohort_id": e["cohort_id"],
        "status": e["status"],
        "health_compliance_status": e["health_compliance_status"],
        "enrolled_at": e["enrolled_at"],
        "ada_rate": ada["ada_rate"],
        "annualized_ada_rate": ada["annualized_ada_rate"],
        "unexcused_absence_rate": ada["unexcused_absence_rate"],
        "chronic_absence": ada["chronic_absence"],
    }
    out.update(_common(e))
    return out


def serialize_attendance(r):
    out = {
        "enrollment_id": r["enrollment_id"],
        "attendance_date": r["attendance_date"],
        "status": r["status"],
        "instructional_day": r["instructional_day"],
    }
    out.update(_common(r, with_version=False))
    return out


def serialize_screening(s):
    out = {
        "enrollment_id": s["enrollment_id"],
        "screening_type": s["screening_type"],
        "status": s["status"],
        "due_date": s["due_date"],
        "completed_date": s["completed_date"],
    }
    out.update(_common(s))
    return out


def home_visit_number(h):
    siblings = [v for v in home_visits.values() if v["enrollment_id"] == h["enrollment_id"]]
    siblings.sort(key=lambda v: (v["scheduled_date"], v["window_start"], v["created_at"], v["_seq"]))
    for idx, v in enumerate(siblings):
        if v["id"] == h["id"]:
            return idx + 1
    return 1


def serialize_home_visit(h):
    out = {
        "enrollment_id": h["enrollment_id"],
        "scheduled_date": h["scheduled_date"],
        "window_start": h["window_start"],
        "window_end": h["window_end"],
        "visit_number": home_visit_number(h),
        "status": h["status"],
    }
    out.update(_common(h))
    return out


def serialize_transition_plan(t):
    out = {
        "enrollment_id": t["enrollment_id"],
        "target_school": t["target_school"],
        "transition_date": t["transition_date"],
        "status": t["status"],
    }
    out.update(_common(t))
    return out


def serialize_pir(p):
    out = {
        "program_id": p["program_id"],
        "reporting_period": p["reporting_period"],
        "total_enrolled": p["total_enrolled"],
        "income_eligible_count": p["income_eligible_count"],
        "categorical_count": p["categorical_count"],
        "homeless_count": p["homeless_count"],
        "immunization_compliant_count": p["immunization_compliant_count"],
        "avg_ada_rate": p["avg_ada_rate"],
        "status": p["status"],
    }
    out.update(_common(p))
    return out


# ===========================================================================
# Business computations
# ===========================================================================
def fpl_for_household(household_size):
    return store.FPL_BASE_CENTS + store.FPL_INCREMENT_CENTS * (household_size - 1)


def compute_eligibility(family, income_source):
    fpl = fpl_for_household(family["household_size"])
    ratio = ratio4(income_source, fpl)
    if family["homeless_status"]:
        cat = "HOMELESS"
    elif family["categorical_eligibility"] != "NONE":
        cat = "CATEGORICAL"
    elif ratio <= Decimal("1.00"):
        cat = "INCOME"
    else:
        cat = "OVER_INCOME"
    return ratio, cat


def count_active_enrollments(family_id):
    n = 0
    for e in enrollments.values():
        if e["status"] == "ACTIVE":
            a = applications.get(e["application_id"])
            if a and a["family_id"] == family_id:
                n += 1
    return n


def compute_priority(app_rec, family, cohort, program, income_ratio):
    homeless_pts = 40 if family["homeless_status"] else 0
    cat_map = {"FOSTER": 35, "TANF": 30, "SSI": 30, "SNAP": 20, "NONE": 0}
    categorical_points = max(homeless_pts, cat_map[family["categorical_eligibility"]])
    if income_ratio <= Decimal("0.50"):
        income_points = 25
    elif income_ratio <= Decimal("0.75"):
        income_points = 18
    elif income_ratio <= Decimal("1.00"):
        income_points = 10
    else:
        income_points = 0
    disability = 15 if app_rec["child_has_iep"] else 0
    age_pts = 10 if (program["program_type"] == "HEAD_START"
                     and cohort["age_band"] == "PRESCHOOL_4") else 0
    sibling = 5 if count_active_enrollments(app_rec["family_id"]) >= 1 else 0
    raw = categorical_points + income_points + disability + age_pts + sibling
    return min(store.MAX_PRIORITY_POINTS, raw)


def recompute_health(enrollment):
    scr = [s for s in health_screenings.values() if s["enrollment_id"] == enrollment["id"]]
    imms = [s for s in scr if s["screening_type"] == "IMMUNIZATION"]
    if any(s["status"] == "OVERDUE" for s in imms):
        new_status = "NON_COMPLIANT"
    elif imms and all(s["status"] in ("UP_TO_DATE", "EXEMPT") for s in scr):
        if all(s["status"] == "EXEMPT" for s in imms):
            new_status = "EXEMPT"
        else:
            new_status = "COMPLIANT"
    else:
        new_status = enrollment["health_compliance_status"]
    if new_status != enrollment["health_compliance_status"]:
        enrollment["health_compliance_status"] = new_status
        touch(enrollment)


def application_of_offer(o):
    return applications.get(o["application_id"])


# ===========================================================================
# Error handling
# ===========================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return responses.error(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return responses.error("ERR_VALIDATION", 404, "Route not found")


@app.errorhandler(405)
def handle_405(e):
    return responses.error("ERR_VALIDATION", 405, "Method not allowed")


@app.errorhandler(Exception)
def handle_uncaught(e):
    if isinstance(e, ApiError):
        return responses.error(e.error_id, e.http_status, e.message)
    return responses.error("ERR_VALIDATION", 500, "Internal error: %s" % e)


@app.route("/", methods=["GET"])
def root():
    return responses.ok({})


# ===========================================================================
# Programs
# ===========================================================================
@app.route("/programs", methods=["POST"])
def create_program():
    _, role = authenticate()
    authorize(role, {"ProgramAdmin"})
    body = get_body()
    name = v_str(body, "name")
    program_type = v_enum(body, "program_type", {"HEAD_START", "PRE_K", "EARLY_HEAD_START"})
    funded_enrollment = v_int(body, "funded_enrollment", minimum=0)
    age_cutoff_date = v_date(body, "age_cutoff_date")
    total_instructional_days = v_int(body, "total_instructional_days", minimum=1)
    ada_threshold = v_num(body, "ada_chronic_threshold_pct", required=False, minimum=0)
    if ada_threshold is None:
        ada_threshold = store.DEFAULT_ADA_CHRONIC_THRESHOLD
    rec = new_record({
        "name": name,
        "program_type": program_type,
        "funded_enrollment": funded_enrollment,
        "age_cutoff_date": age_cutoff_date,
        "total_instructional_days": total_instructional_days,
        "ada_chronic_threshold_pct": ada_threshold,
    })
    programs[rec["id"]] = rec
    return responses.ok(serialize_program(rec), 201)


@app.route("/programs/<pid>", methods=["GET"])
def get_program(pid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(programs, pid, "ERR_PROGRAM_NOT_FOUND")
    return responses.ok(serialize_program(rec))


@app.route("/programs", methods=["GET"])
def list_programs():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    return list_response(list(programs.values()), serialize_program)


# ===========================================================================
# Cohorts
# ===========================================================================
@app.route("/cohorts", methods=["POST"])
def create_cohort():
    _, role = authenticate()
    authorize(role, {"ProgramAdmin"})
    body = get_body()
    program_id = body.get("program_id")
    resolve_fk(programs, program_id, "ERR_PROGRAM_NOT_FOUND")
    # structural validation last
    program_id = v_str(body, "program_id")
    resolve_fk(programs, program_id, "ERR_PROGRAM_NOT_FOUND")
    age_band = v_enum(body, "age_band", {"INFANT", "TODDLER", "PRESCHOOL_3", "PRESCHOOL_4"})
    funded_slots = v_int(body, "funded_slots", minimum=0)
    min_age = v_int(body, "min_age_months")
    max_age = v_int(body, "max_age_months")
    session_start = v_time(body, "session_start")
    session_end = v_time(body, "session_end")
    rec = new_record({
        "program_id": program_id,
        "age_band": age_band,
        "funded_slots": funded_slots,
        "min_age_months": min_age,
        "max_age_months": max_age,
        "session_start": session_start,
        "session_end": session_end,
    })
    cohorts[rec["id"]] = rec
    return responses.ok(serialize_cohort(rec), 201)


@app.route("/cohorts/<cid>", methods=["GET"])
def get_cohort(cid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(cohorts, cid, "ERR_COHORT_NOT_FOUND")
    return responses.ok(serialize_cohort(rec))


@app.route("/cohorts", methods=["GET"])
def list_cohorts():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(cohorts.values())
    pid = request.args.get("program_id")
    if pid is not None:
        items = [c for c in items if c["program_id"] == pid]
    return list_response(items, serialize_cohort)


@app.route("/cohorts/<cid>/run-selection", methods=["POST"])
def run_selection(cid):
    _, role = authenticate()
    authorize(role, {"ProgramAdmin"})
    cohort = get_or_404(cohorts, cid, "ERR_COHORT_NOT_FOUND")
    pool = [a for a in applications.values()
            if a["cohort_id"] == cid and a["status"] == "WAITLISTED"]
    if not pool:
        raise err("ERR_NO_ELIGIBLE_APPLICANTS", "No eligible waitlisted applicants")
    pool.sort(key=lambda a: (-a["priority_points"], a["submitted_at"] or "",
                             a["created_at"], a["_seq"]))
    _, _, available, _ = cohort_accounting(cohort)
    selected = pool[:available] if available > 0 else []
    created = []
    for app_rec in selected:
        offered_at = clock_now()
        expires = offer_expiry(offered_at)
        offer = new_record({
            "application_id": app_rec["id"],
            "cohort_id": cid,
            "status": "PENDING",
            "offered_at": format_dt(offered_at),
            "offer_expires_at": format_dt(expires),
        })
        offers[offer["id"]] = offer
        app_rec["status"] = "OFFERED"
        touch(app_rec)
        touch(cohort)
        created.append(offer)
    return responses.ok([serialize_offer(o) for o in created], 201)


# ===========================================================================
# Families
# ===========================================================================
@app.route("/families", methods=["POST"])
def create_family():
    _, role = authenticate()
    authorize(role, {"EnrollmentSpecialist", "Family"})
    body = get_body()
    guardian_name = v_str(body, "guardian_name")
    household_size = v_int(body, "household_size", minimum=1)
    annual_income_cents = v_int(body, "annual_income_cents", minimum=0)
    categorical = v_enum(body, "categorical_eligibility",
                         {"NONE", "TANF", "SSI", "SNAP", "FOSTER"})
    homeless = v_bool(body, "homeless_status", default=False)
    rec = new_record({
        "guardian_name": guardian_name,
        "household_size": household_size,
        "annual_income_cents": annual_income_cents,
        "categorical_eligibility": categorical,
        "homeless_status": homeless,
    })
    families[rec["id"]] = rec
    return responses.ok(serialize_family(rec), 201)


@app.route("/families/<fid>", methods=["GET"])
def get_family(fid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(families, fid, "ERR_FAMILY_NOT_FOUND")
    return responses.ok(serialize_family(rec))


# ===========================================================================
# Applications
# ===========================================================================
@app.route("/applications", methods=["POST"])
def create_application():
    _, role = authenticate()
    authorize(role, {"EnrollmentSpecialist", "Family"})
    body = get_body()
    # existence (priority 4) for present FKs, left-to-right
    resolve_fk(programs, body.get("program_id"), "ERR_PROGRAM_NOT_FOUND")
    resolve_fk(cohorts, body.get("cohort_id"), "ERR_COHORT_NOT_FOUND")
    resolve_fk(families, body.get("family_id"), "ERR_FAMILY_NOT_FOUND")
    # structural validation (priority 18)
    program_id = v_str(body, "program_id")
    resolve_fk(programs, program_id, "ERR_PROGRAM_NOT_FOUND")
    cohort_id = v_str(body, "cohort_id")
    resolve_fk(cohorts, cohort_id, "ERR_COHORT_NOT_FOUND")
    family_id = v_str(body, "family_id")
    resolve_fk(families, family_id, "ERR_FAMILY_NOT_FOUND")
    first = v_str(body, "child_first_name")
    last = v_str(body, "child_last_name")
    dob = v_date(body, "child_dob")
    has_iep = v_bool(body, "child_has_iep", default=False)
    rec = new_record({
        "program_id": program_id,
        "cohort_id": cohort_id,
        "family_id": family_id,
        "child_first_name": first,
        "child_last_name": last,
        "child_dob": dob,
        "child_has_iep": has_iep,
        "verified_income_cents": None,
        "status": "DRAFT",
        "eligibility_category": None,
        "income_ratio": None,
        "age_months_at_cutoff": None,
        "priority_points": None,
        "submitted_at": None,
        "waitlisted_at": None,
    })
    applications[rec["id"]] = rec
    return responses.ok(serialize_application(rec), 201)


@app.route("/applications/<aid>", methods=["GET"])
def get_application(aid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(applications, aid, "ERR_APPLICATION_NOT_FOUND")
    return responses.ok(serialize_application(rec))


@app.route("/applications", methods=["GET"])
def list_applications():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(applications.values())
    for key in ("program_id", "cohort_id", "family_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [a for a in items if a[key] == val]
    return list_response(items, serialize_application)


@app.route("/applications/<aid>/submit", methods=["POST"])
def submit_application(aid):
    uid, role = authenticate()
    authorize(role, {"EnrollmentSpecialist", "Family"})
    app_rec = get_or_404(applications, aid, "ERR_APPLICATION_NOT_FOUND")
    check_owner(role, uid, app_rec["family_id"])
    if app_rec["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Application is not in DRAFT")
    # duplicate check (priority 10)
    for other in applications.values():
        if other["id"] == app_rec["id"]:
            continue
        if (other["family_id"] == app_rec["family_id"]
                and other["child_dob"] == app_rec["child_dob"]
                and other["program_id"] == app_rec["program_id"]
                and other["status"] not in ("INELIGIBLE", "WITHDRAWN")):
            raise err("ERR_DUPLICATE_APPLICATION", "Duplicate non-terminal application exists")
    program = programs[app_rec["program_id"]]
    cohort = cohorts[app_rec["cohort_id"]]
    family = families[app_rec["family_id"]]
    months = age_months(app_rec["child_dob"], program["age_cutoff_date"])
    # age band check (priority 11)
    if months < cohort["min_age_months"] or months > cohort["max_age_months"]:
        raise err("ERR_AGE_OUT_OF_BAND", "Child age outside cohort band")
    # side effects
    app_rec["age_months_at_cutoff"] = months
    ratio, cat = compute_eligibility(family, family["annual_income_cents"])
    app_rec["income_ratio"] = float(ratio)
    app_rec["eligibility_category"] = cat
    app_rec["priority_points"] = compute_priority(app_rec, family, cohort, program, ratio)
    app_rec["submitted_at"] = now_iso()
    app_rec["status"] = "SUBMITTED"
    touch(app_rec)
    return responses.ok(serialize_application(app_rec))


@app.route("/applications/<aid>/verify-eligibility", methods=["POST"])
def verify_eligibility(aid):
    _, role = authenticate()
    authorize(role, {"EnrollmentSpecialist"})
    app_rec = get_or_404(applications, aid, "ERR_APPLICATION_NOT_FOUND")
    if app_rec["status"] != "SUBMITTED":
        raise err("ERR_APPLICATION_NOT_SUBMITTED", "Application is not SUBMITTED")
    body = get_body()
    verified = v_int(body, "verified_income_cents", minimum=0)
    program = programs[app_rec["program_id"]]
    cohort = cohorts[app_rec["cohort_id"]]
    family = families[app_rec["family_id"]]
    app_rec["verified_income_cents"] = verified
    ratio, cat = compute_eligibility(family, verified)
    app_rec["income_ratio"] = float(ratio)
    app_rec["eligibility_category"] = cat
    app_rec["priority_points"] = compute_priority(app_rec, family, cohort, program, ratio)
    if cat == "OVER_INCOME":
        app_rec["status"] = "INELIGIBLE"
    else:
        app_rec["status"] = "ELIGIBLE"
    touch(app_rec)
    return responses.ok(serialize_application(app_rec))


@app.route("/applications/<aid>/waitlist", methods=["POST"])
def waitlist_application(aid):
    _, role = authenticate()
    authorize(role, {"EnrollmentSpecialist"})
    app_rec = get_or_404(applications, aid, "ERR_APPLICATION_NOT_FOUND")
    if app_rec["status"] != "ELIGIBLE":
        raise err("ERR_APPLICATION_NOT_ELIGIBLE", "Application is not ELIGIBLE")
    app_rec["waitlisted_at"] = now_iso()
    app_rec["status"] = "WAITLISTED"
    touch(app_rec)
    return responses.ok(serialize_application(app_rec))


@app.route("/applications/<aid>/withdraw", methods=["POST"])
def withdraw_application(aid):
    uid, role = authenticate()
    authorize(role, {"EnrollmentSpecialist", "Family"})
    app_rec = get_or_404(applications, aid, "ERR_APPLICATION_NOT_FOUND")
    check_owner(role, uid, app_rec["family_id"])
    if app_rec["status"] in ("INELIGIBLE", "WITHDRAWN"):
        raise err("ERR_INVALID_STATE", "Application already in a terminal state")
    # cancel any pending offer
    for o in offers.values():
        if o["application_id"] == app_rec["id"] and o["status"] == "PENDING":
            o["status"] = "WITHDRAWN"
            touch(o)
            cohort = cohorts.get(o["cohort_id"])
            if cohort:
                touch(cohort)
    app_rec["status"] = "WITHDRAWN"
    touch(app_rec)
    return responses.ok(serialize_application(app_rec))


# ===========================================================================
# Offers
# ===========================================================================
@app.route("/offers/<oid>", methods=["GET"])
def get_offer(oid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(offers, oid, "ERR_OFFER_NOT_FOUND")
    return responses.ok(serialize_offer(rec))


@app.route("/offers", methods=["GET"])
def list_offers():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(offers.values())
    for key in ("cohort_id", "application_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [o for o in items if o[key] == val]
    return list_response(items, serialize_offer)


@app.route("/offers/<oid>/accept", methods=["POST"])
def accept_offer(oid):
    uid, role = authenticate()
    authorize(role, {"Family"})
    offer = get_or_404(offers, oid, "ERR_OFFER_NOT_FOUND")
    app_rec = application_of_offer(offer)
    check_owner(role, uid, app_rec["family_id"])
    if offer["status"] != "PENDING":
        raise err("ERR_OFFER_NOT_PENDING", "Offer is not PENDING")
    if clock_now() >= _parse_iso(offer["offer_expires_at"]):
        raise err("ERR_OFFER_EXPIRED", "Offer has expired")
    cohort = cohorts[offer["cohort_id"]]
    body = get_body()
    expected = body.get("expected_cohort_version")
    # OCC (priority 17): compare only when a well-typed value is provided
    if isinstance(expected, int) and not isinstance(expected, bool):
        if expected != cohort["version"]:
            raise err("ERR_STALE_VERSION", "Cohort version is stale")
    else:
        # structural validation (priority 18)
        v_int(body, "expected_cohort_version")
    # side effects
    offer["status"] = "ACCEPTED"
    touch(offer)
    app_rec["status"] = "ENROLLED"
    touch(app_rec)
    enrollment = new_record({
        "application_id": app_rec["id"],
        "cohort_id": offer["cohort_id"],
        "status": "ACTIVE",
        "health_compliance_status": "PENDING",
        "enrolled_at": now_iso(),
    })
    enrollments[enrollment["id"]] = enrollment
    touch(cohort)
    return responses.ok(serialize_offer(offer))


@app.route("/offers/<oid>/decline", methods=["POST"])
def decline_offer(oid):
    uid, role = authenticate()
    authorize(role, {"Family"})
    offer = get_or_404(offers, oid, "ERR_OFFER_NOT_FOUND")
    app_rec = application_of_offer(offer)
    check_owner(role, uid, app_rec["family_id"])
    if offer["status"] != "PENDING":
        raise err("ERR_OFFER_NOT_PENDING", "Offer is not PENDING")
    offer["status"] = "DECLINED"
    touch(offer)
    if app_rec["status"] == "OFFERED":
        app_rec["status"] = "WAITLISTED"
        touch(app_rec)
    cohort = cohorts.get(offer["cohort_id"])
    if cohort:
        touch(cohort)
    return responses.ok(serialize_offer(offer))


@app.route("/offers/<oid>/expire", methods=["POST"])
def expire_offer(oid):
    _, role = authenticate()
    authorize(role, {"ProgramAdmin"})
    offer = get_or_404(offers, oid, "ERR_OFFER_NOT_FOUND")
    if offer["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Offer is not PENDING")
    if clock_now() < _parse_iso(offer["offer_expires_at"]):
        raise err("ERR_INVALID_STATE", "Offer window has not passed")
    offer["status"] = "EXPIRED"
    touch(offer)
    app_rec = application_of_offer(offer)
    if app_rec and app_rec["status"] == "OFFERED":
        app_rec["status"] = "WAITLISTED"
        touch(app_rec)
    cohort = cohorts.get(offer["cohort_id"])
    if cohort:
        touch(cohort)
    return responses.ok(serialize_offer(offer))


# ===========================================================================
# Enrollments
# ===========================================================================
@app.route("/enrollments/<eid>", methods=["GET"])
def get_enrollment(eid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(enrollments, eid, "ERR_ENROLLMENT_NOT_FOUND")
    return responses.ok(serialize_enrollment(rec))


@app.route("/enrollments", methods=["GET"])
def list_enrollments():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(enrollments.values())
    for key in ("cohort_id", "application_id"):
        val = request.args.get(key)
        if val is not None:
            items = [e for e in items if e[key] == val]
    return list_response(items, serialize_enrollment)


@app.route("/enrollments/<eid>/withdraw", methods=["POST"])
def withdraw_enrollment(eid):
    uid, role = authenticate()
    authorize(role, {"EnrollmentSpecialist", "ProgramAdmin", "Family"})
    enrollment = get_or_404(enrollments, eid, "ERR_ENROLLMENT_NOT_FOUND")
    app_rec = applications.get(enrollment["application_id"])
    check_owner(role, uid, app_rec["family_id"] if app_rec else None)
    if enrollment["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Enrollment is not ACTIVE")
    enrollment["status"] = "WITHDRAWN"
    touch(enrollment)
    if app_rec:
        app_rec["status"] = "WITHDRAWN"
        touch(app_rec)
    cohort = cohorts.get(enrollment["cohort_id"])
    if cohort:
        touch(cohort)
    return responses.ok(serialize_enrollment(enrollment))


@app.route("/enrollments/<eid>/disenroll", methods=["POST"])
def disenroll_enrollment(eid):
    _, role = authenticate()
    authorize(role, {"ProgramAdmin"})
    enrollment = get_or_404(enrollments, eid, "ERR_ENROLLMENT_NOT_FOUND")
    if enrollment["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Enrollment is not ACTIVE")
    enrollment["status"] = "DISENROLLED"
    touch(enrollment)
    cohort = cohorts.get(enrollment["cohort_id"])
    if cohort:
        touch(cohort)
    return responses.ok(serialize_enrollment(enrollment))


# ===========================================================================
# Attendance
# ===========================================================================
@app.route("/attendance-records", methods=["POST"])
def create_attendance():
    _, role = authenticate()
    authorize(role, {"FamilyServicesWorker"})
    body = get_body()
    enrollment = resolve_fk(enrollments, body.get("enrollment_id"), "ERR_ENROLLMENT_NOT_FOUND")
    if enrollment is not None and enrollment["status"] != "ACTIVE":
        raise err("ERR_ENROLLMENT_NOT_ACTIVE", "Enrollment is not ACTIVE")
    enrollment_id = v_str(body, "enrollment_id")
    enrollment = resolve_fk(enrollments, enrollment_id, "ERR_ENROLLMENT_NOT_FOUND")
    if enrollment["status"] != "ACTIVE":
        raise err("ERR_ENROLLMENT_NOT_ACTIVE", "Enrollment is not ACTIVE")
    attendance_date = v_date(body, "attendance_date")
    status = v_enum(body, "status", {"PRESENT", "ABSENT_EXCUSED", "ABSENT_UNEXCUSED"})
    instructional_day = v_bool(body, "instructional_day", default=True)
    rec = new_record({
        "enrollment_id": enrollment_id,
        "attendance_date": attendance_date,
        "status": status,
        "instructional_day": instructional_day,
    }, with_version=False)
    attendance_records[rec["id"]] = rec
    return responses.ok(serialize_attendance(rec), 201)


@app.route("/enrollments/<eid>/attendance-records", methods=["GET"])
def list_attendance(eid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    get_or_404(enrollments, eid, "ERR_ENROLLMENT_NOT_FOUND")
    items = [r for r in attendance_records.values() if r["enrollment_id"] == eid]
    return list_response(items, serialize_attendance)


# ===========================================================================
# Health screenings
# ===========================================================================
@app.route("/health-screenings", methods=["POST"])
def create_screening():
    _, role = authenticate()
    authorize(role, {"FamilyServicesWorker"})
    body = get_body()
    enrollment = resolve_fk(enrollments, body.get("enrollment_id"), "ERR_ENROLLMENT_NOT_FOUND")
    if enrollment is not None and enrollment["status"] != "ACTIVE":
        raise err("ERR_ENROLLMENT_NOT_ACTIVE", "Enrollment is not ACTIVE")
    enrollment_id = v_str(body, "enrollment_id")
    enrollment = resolve_fk(enrollments, enrollment_id, "ERR_ENROLLMENT_NOT_FOUND")
    if enrollment["status"] != "ACTIVE":
        raise err("ERR_ENROLLMENT_NOT_ACTIVE", "Enrollment is not ACTIVE")
    screening_type = v_enum(body, "screening_type", {"IMMUNIZATION", "PHYSICAL", "DENTAL"})
    due_date = v_date(body, "due_date")
    rec = new_record({
        "enrollment_id": enrollment_id,
        "screening_type": screening_type,
        "status": "DUE",
        "due_date": due_date,
        "completed_date": None,
    })
    health_screenings[rec["id"]] = rec
    return responses.ok(serialize_screening(rec), 201)


@app.route("/health-screenings/<sid>", methods=["PATCH"])
def update_screening(sid):
    _, role = authenticate()
    authorize(role, {"FamilyServicesWorker"})
    screening = get_or_404(health_screenings, sid, "ERR_HEALTH_SCREENING_NOT_FOUND")
    body = get_body()
    status = v_enum(body, "status", {"DUE", "UP_TO_DATE", "OVERDUE", "EXEMPT"})
    completed_date = v_date(body, "completed_date", required=False)
    screening["status"] = status
    if completed_date is not None:
        screening["completed_date"] = completed_date
    elif status == "UP_TO_DATE" and screening["completed_date"] is None:
        screening["completed_date"] = None
    touch(screening)
    enrollment = enrollments.get(screening["enrollment_id"])
    if enrollment:
        recompute_health(enrollment)
    return responses.ok(serialize_screening(screening))


@app.route("/enrollments/<eid>/health-screenings", methods=["GET"])
def list_screenings(eid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    get_or_404(enrollments, eid, "ERR_ENROLLMENT_NOT_FOUND")
    items = [s for s in health_screenings.values() if s["enrollment_id"] == eid]
    return list_response(items, serialize_screening)


# ===========================================================================
# Home visits
# ===========================================================================
@app.route("/home-visits", methods=["POST"])
def create_home_visit():
    _, role = authenticate()
    authorize(role, {"FamilyServicesWorker"})
    body = get_body()
    enrollment = resolve_fk(enrollments, body.get("enrollment_id"), "ERR_ENROLLMENT_NOT_FOUND")
    if enrollment is not None and enrollment["status"] != "ACTIVE":
        raise err("ERR_ENROLLMENT_NOT_ACTIVE", "Enrollment is not ACTIVE")
    # Business temporal checks (priority 13, 14) only when the window is well-formed.
    scheduled_date = body.get("scheduled_date")
    ws = body.get("window_start")
    we = body.get("window_end")
    window_ok = (isinstance(scheduled_date, str) and isinstance(ws, str)
                 and isinstance(we, str))
    ws_min = we_min = None
    if window_ok:
        try:
            datetime.strptime(scheduled_date, "%Y-%m-%d")
            ws_min = parse_hhmm(ws)
            we_min = parse_hhmm(we)
        except (ValueError, TypeError):
            window_ok = False
    if enrollment is not None and window_ok and ws_min is not None:
        # overlap with existing non-cancelled visits same enrollment + date
        for v in home_visits.values():
            if (v["enrollment_id"] == enrollment["id"]
                    and v["scheduled_date"] == scheduled_date
                    and v["status"] != "CANCELLED"):
                ev_s = parse_hhmm(v["window_start"])
                ev_e = parse_hhmm(v["window_end"])
                if ws_min < ev_e and ev_s < we_min:
                    raise err("ERR_HOME_VISIT_OVERLAP", "Home visit window overlaps")
        # intersection with cohort session window
        cohort = cohorts[enrollment["cohort_id"]]
        s_start = parse_hhmm(cohort["session_start"])
        s_end = parse_hhmm(cohort["session_end"])
        if ws_min < s_end and s_start < we_min:
            raise err("ERR_VISIT_DURING_SESSION", "Home visit intersects session window")
    # structural validation (priority 18)
    enrollment_id = v_str(body, "enrollment_id")
    enrollment = resolve_fk(enrollments, enrollment_id, "ERR_ENROLLMENT_NOT_FOUND")
    if enrollment["status"] != "ACTIVE":
        raise err("ERR_ENROLLMENT_NOT_ACTIVE", "Enrollment is not ACTIVE")
    scheduled_date = v_date(body, "scheduled_date")
    window_start = v_time(body, "window_start")
    window_end = v_time(body, "window_end")
    rec = new_record({
        "enrollment_id": enrollment_id,
        "scheduled_date": scheduled_date,
        "window_start": window_start,
        "window_end": window_end,
        "status": "SCHEDULED",
    })
    home_visits[rec["id"]] = rec
    return responses.ok(serialize_home_visit(rec), 201)


@app.route("/home-visits/<hid>/complete", methods=["POST"])
def complete_home_visit(hid):
    _, role = authenticate()
    authorize(role, {"FamilyServicesWorker"})
    visit = get_or_404(home_visits, hid, "ERR_HOME_VISIT_NOT_FOUND")
    if visit["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Home visit is not SCHEDULED")
    visit["status"] = "COMPLETED"
    touch(visit)
    return responses.ok(serialize_home_visit(visit))


@app.route("/enrollments/<eid>/home-visits", methods=["GET"])
def list_home_visits(eid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    get_or_404(enrollments, eid, "ERR_ENROLLMENT_NOT_FOUND")
    items = [h for h in home_visits.values() if h["enrollment_id"] == eid]
    return list_response(items, serialize_home_visit)


# ===========================================================================
# Transition plans
# ===========================================================================
@app.route("/transition-plans", methods=["POST"])
def create_transition_plan():
    _, role = authenticate()
    authorize(role, {"FamilyServicesWorker", "ProgramAdmin"})
    body = get_body()
    enrollment = resolve_fk(enrollments, body.get("enrollment_id"), "ERR_ENROLLMENT_NOT_FOUND")
    if enrollment is not None and enrollment["status"] != "ACTIVE":
        raise err("ERR_ENROLLMENT_NOT_ACTIVE", "Enrollment is not ACTIVE")
    enrollment_id = v_str(body, "enrollment_id")
    enrollment = resolve_fk(enrollments, enrollment_id, "ERR_ENROLLMENT_NOT_FOUND")
    if enrollment["status"] != "ACTIVE":
        raise err("ERR_ENROLLMENT_NOT_ACTIVE", "Enrollment is not ACTIVE")
    target_school = v_str(body, "target_school")
    transition_date = v_date(body, "transition_date")
    rec = new_record({
        "enrollment_id": enrollment_id,
        "target_school": target_school,
        "transition_date": transition_date,
        "status": "DRAFT",
    })
    transition_plans[rec["id"]] = rec
    return responses.ok(serialize_transition_plan(rec), 201)


@app.route("/transition-plans/<tid>/complete", methods=["POST"])
def complete_transition_plan(tid):
    _, role = authenticate()
    authorize(role, {"ProgramAdmin"})
    plan = get_or_404(transition_plans, tid, "ERR_TRANSITION_PLAN_NOT_FOUND")
    if plan["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Transition plan is not DRAFT")
    enrollment = enrollments.get(plan["enrollment_id"])
    completed_visits = sum(1 for h in home_visits.values()
                           if h["enrollment_id"] == plan["enrollment_id"]
                           and h["status"] == "COMPLETED")
    if (enrollment is None or enrollment["status"] != "ACTIVE"
            or enrollment["health_compliance_status"] != "COMPLIANT"
            or completed_visits < 2):
        raise err("ERR_TRANSITION_PREREQ_NOT_MET",
                  "Transition prerequisites not met")
    plan["status"] = "COMPLETED"
    touch(plan)
    enrollment["status"] = "COMPLETED_TRANSITION"
    touch(enrollment)
    cohort = cohorts.get(enrollment["cohort_id"])
    if cohort:
        touch(cohort)
    return responses.ok(serialize_transition_plan(plan))


@app.route("/enrollments/<eid>/transition-plans", methods=["GET"])
def list_transition_plans(eid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    get_or_404(enrollments, eid, "ERR_ENROLLMENT_NOT_FOUND")
    items = [t for t in transition_plans.values() if t["enrollment_id"] == eid]
    return list_response(items, serialize_transition_plan)


# ===========================================================================
# PIR reports
# ===========================================================================
@app.route("/pir-reports", methods=["POST"])
def create_pir_report():
    _, role = authenticate()
    authorize(role, {"ProgramAdmin"})
    body = get_body()
    program = resolve_fk(programs, body.get("program_id"), "ERR_PROGRAM_NOT_FOUND")
    program_id = v_str(body, "program_id")
    program = resolve_fk(programs, program_id, "ERR_PROGRAM_NOT_FOUND")
    reporting_period = v_str(body, "reporting_period")
    # pool: enrollments in program with status ACTIVE or COMPLETED_TRANSITION
    pool = []
    for e in enrollments.values():
        cohort = cohorts.get(e["cohort_id"])
        if cohort and cohort["program_id"] == program_id \
                and e["status"] in ("ACTIVE", "COMPLETED_TRANSITION"):
            pool.append(e)
    total = len(pool)
    income_count = 0
    categorical_count = 0
    homeless_count = 0
    immunization_count = 0
    rates = []
    for e in pool:
        a = applications.get(e["application_id"])
        cat = a["eligibility_category"] if a else None
        if cat == "INCOME":
            income_count += 1
        elif cat == "CATEGORICAL":
            categorical_count += 1
        elif cat == "HOMELESS":
            homeless_count += 1
        if e["health_compliance_status"] == "COMPLIANT":
            immunization_count += 1
        rates.append(compute_ada(e)["ada_dec"])
    if total > 0:
        avg = (sum(rates) / Decimal(total)).quantize(Q4, rounding=ROUND_HALF_UP)
        avg_ada = float(avg)
    else:
        avg_ada = 0.0
    rec = new_record({
        "program_id": program_id,
        "reporting_period": reporting_period,
        "total_enrolled": total,
        "income_eligible_count": income_count,
        "categorical_count": categorical_count,
        "homeless_count": homeless_count,
        "immunization_compliant_count": immunization_count,
        "avg_ada_rate": avg_ada,
        "status": "DRAFT",
    })
    pir_reports[rec["id"]] = rec
    return responses.ok(serialize_pir(rec), 201)


@app.route("/pir-reports/<rid>", methods=["GET"])
def get_pir_report(rid):
    _, role = authenticate()
    authorize(role, {"ProgramAdmin", "EnrollmentSpecialist"})
    rec = pir_reports.get(rid)
    if rec is None:
        raise ApiError("ERR_PIR_REPORT_NOT_FOUND", 404, "PIR report not found")
    return responses.ok(serialize_pir(rec))


@app.route("/pir-reports", methods=["GET"])
def list_pir_reports():
    _, role = authenticate()
    authorize(role, {"ProgramAdmin", "EnrollmentSpecialist"})
    items = list(pir_reports.values())
    pid = request.args.get("program_id")
    if pid is not None:
        items = [p for p in items if p["program_id"] == pid]
    return list_response(items, serialize_pir)


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _, role = authenticate()
    authorize(role, {"ProgramAdmin"})
    body = get_body()
    to_iso = v_str(body, "to_iso8601")
    try:
        set_clock(to_iso)
    except (ValueError, TypeError):
        raise err("ERR_VALIDATION", "Invalid to_iso8601 value")
    return responses.ok({})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
