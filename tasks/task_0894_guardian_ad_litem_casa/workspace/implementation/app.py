"""Guardian-ad-Litem & CASA Volunteer Management API (Flask, in-memory)."""
import os
from decimal import Decimal
from flask import Flask, request, jsonify

import store

app = Flask(__name__)

ROLES = ("ProgramAdmin", "Supervisor", "Volunteer")

# Calculation constants
STD_RATE_CENTS_PER_MILE = 50
TIER1_MILES = 100
TIER1_RATE_CENTS = 50
TIER2_RATE_CENTS = 35
OTHER_EXPENSE_CAP_CENTS = 5000
MONTHLY_REIMBURSEMENT_CAP_CENTS = 15000
CONTACT_STANDARD_PER_MONTH = 3
BACKGROUND_VALID_DAYS = 365
REPORT_LEAD_DAYS = 3
TRAINING_HOURS_REQUIRED = 30
HEARING_BUFFER_DAYS = 7


# ---------------------------------------------------------------------------
# Errors & envelope
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http, message=""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http = http
        self.message = message or error_id


def _meta(extra=None):
    m = {
        "api_request_id": store.gen_request_id(),
        "api_request_timestamp": store.wall_now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, code=200, list_meta=None):
    rt = "array" if isinstance(data, list) else "object"
    return jsonify({"meta": _meta(list_meta), "response_type": rt, "data": data}), code


@app.errorhandler(ApiError)
def _handle_api_error(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http


@app.errorhandler(404)
def _handle_404(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": "Not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def _handle_405(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": "Method not allowed"},
    }
    return jsonify(body), 405


# ---------------------------------------------------------------------------
# Request context / body helpers
# ---------------------------------------------------------------------------
def get_ctx():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or role not in ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            400,
            "Missing or invalid user context headers",
        )
    return uid, role


def get_body():
    b = request.get_json(force=True, silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise ApiError("ERR_VALIDATION", 400, "Request body must be a JSON object")
    return b


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")


def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def require_present(body, name):
    if body.get(name) is None:
        raise ApiError("ERR_VALIDATION", 400, "Missing required field: %s" % name)
    return body.get(name)


def validation_error(msg):
    raise ApiError("ERR_VALIDATION", 400, msg)


# ---------------------------------------------------------------------------
# Lookups (existence -> 404)
# ---------------------------------------------------------------------------
def get_volunteer(vid):
    r = store.volunteers.get(vid)
    if not r:
        raise ApiError("ERR_VOLUNTEER_NOT_FOUND", 404, "Volunteer not found")
    return r


def get_supervisor(sid):
    r = store.supervisors.get(sid)
    if not r:
        raise ApiError("ERR_SUPERVISOR_NOT_FOUND", 404, "Supervisor not found")
    return r


def get_case(cid):
    r = store.cases.get(cid)
    if not r:
        raise ApiError("ERR_CASE_NOT_FOUND", 404, "Case not found")
    return r


def get_assignment_on_case(cid, aid):
    r = store.assignments.get(aid)
    if not r or r["case_id"] != cid:
        raise ApiError("ERR_ASSIGNMENT_NOT_FOUND", 404, "Assignment not found")
    return r


def get_visit(vid):
    r = store.visits.get(vid)
    if not r:
        raise ApiError("ERR_VISIT_NOT_FOUND", 404, "Visit not found")
    return r


def get_hearing(hid):
    r = store.hearings.get(hid)
    if not r:
        raise ApiError("ERR_HEARING_NOT_FOUND", 404, "Hearing not found")
    return r


def get_report(rid):
    r = store.court_reports.get(rid)
    if not r:
        raise ApiError("ERR_REPORT_NOT_FOUND", 404, "Court report not found")
    return r


def get_background_check(bid):
    r = store.background_checks.get(bid)
    if not r:
        raise ApiError("ERR_BACKGROUND_CHECK_NOT_FOUND", 404, "Background check not found")
    return r


def get_expense_claim(eid):
    r = store.expense_claims.get(eid)
    if not r:
        raise ApiError("ERR_EXPENSE_CLAIM_NOT_FOUND", 404, "Expense claim not found")
    return r


def ensure_case_supervisor(uid, case):
    if uid != case["supervisor_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Supervisor does not own this case")


# ---------------------------------------------------------------------------
# Derived computations
# ---------------------------------------------------------------------------
def refresh_check(c):
    if (
        c["status"] == "CLEARED"
        and c.get("expiry_date") is not None
        and store.now() >= c["expiry_date"]
    ):
        c["status"] = "EXPIRED"
        store.touch(c)


def volunteer_checks(vid):
    return [c for c in store.background_checks.values() if c["volunteer_id"] == vid]


def compute_background(v):
    cs = volunteer_checks(v["id"])
    for c in cs:
        refresh_check(c)
    if not cs:
        return "NONE", None
    newest = max(cs, key=lambda c: (c["created_at"], c["_seq"]))
    status = newest["status"]
    cleared = [c for c in cs if c["status"] == "CLEARED"]
    expiry = None
    if cleared:
        expiry = max(cleared, key=lambda c: (c["created_at"], c["_seq"]))["expiry_date"]
    return status, expiry


def training_hours_total(vid):
    total = 0
    for t in store.training_records.values():
        if t["volunteer_id"] == vid:
            total += t["hours"]
    return total


def active_case_count(vid):
    return sum(
        1
        for a in store.assignments.values()
        if a["volunteer_id"] == vid and a["status"] == "ACTIVE"
    )


def committed_cents(case_id):
    return sum(
        e["final_reimbursement_cents"] or 0
        for e in store.expense_claims.values()
        if e["case_id"] == case_id and e["status"] in ("APPROVED", "PAID")
    )


def active_assignment_of_case(case_id):
    for a in store.assignments.values():
        if a["case_id"] == case_id and a["status"] == "ACTIVE":
            return a
    return None


def month_range(y0, m0, y1, m1):
    res = []
    y, m = y0, m0
    while (y, m) <= (y1, m1):
        res.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return res


def compute_compliance(case, qualifying):
    case_assignments = [a for a in store.assignments.values() if a["case_id"] == case["id"]]
    if not case_assignments:
        return 0.0
    earliest = min(a["created_at"] for a in case_assignments)
    n = store.now()
    months = month_range(earliest.year, earliest.month, n.year, n.month)
    required = len(months)
    if required == 0:
        return 0.0
    logged = [
        v
        for v in store.visits.values()
        if v["case_id"] == case["id"] and v["status"] == "LOGGED"
    ]
    parsed = []
    for v in logged:
        if v["contact_type"] in qualifying:
            try:
                cs = store.parse_dt(v["contact_start"])
                parsed.append((cs.year, cs.month))
            except Exception:
                pass
    total = Decimal(0)
    for (y, m) in months:
        q = sum(1 for (vy, vm) in parsed if vy == y and vm == m)
        ratio = Decimal(q) / Decimal(CONTACT_STANDARD_PER_MONTH)
        if ratio > Decimal(1):
            ratio = Decimal(1)
        month_score = store.rhu(ratio, 2)
        total += month_score
    pct = store.rhu(total / Decimal(required) * Decimal(100), 1)
    return float(pct)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def s_volunteer(v):
    status, expiry = compute_background(v)
    return {
        "id": v["id"],
        "full_name": v["full_name"],
        "email": v["email"],
        "home_zip": v["home_zip"],
        "max_caseload": v["max_caseload"],
        "status": v["status"],
        "sworn_in_at": store.fmt_dt(v["sworn_in_at"]),
        "deactivation_reason": v["deactivation_reason"],
        "training_hours_total": training_hours_total(v["id"]),
        "background_status": status,
        "background_expiry_date": store.fmt_dt(expiry),
        "active_case_count": active_case_count(v["id"]),
        "created_at": store.fmt_dt(v["created_at"]),
        "updated_at": store.fmt_dt(v["updated_at"]),
        "version": v["version"],
    }


def s_supervisor(s):
    return {
        "id": s["id"],
        "full_name": s["full_name"],
        "email": s["email"],
        "status": s["status"],
        "created_at": store.fmt_dt(s["created_at"]),
        "updated_at": store.fmt_dt(s["updated_at"]),
        "version": s["version"],
    }


def s_case(c):
    return {
        "id": c["id"],
        "child_initials": c["child_initials"],
        "child_dob": c["child_dob"],
        "jurisdiction": c["jurisdiction"],
        "supervisor_id": c["supervisor_id"],
        "status": c["status"],
        "outcome": c["outcome"],
        "reimbursement_budget_cents": c["reimbursement_budget_cents"],
        "reimbursement_committed_cents": committed_cents(c["id"]),
        "contact_compliance_pct": compute_compliance(c, {"IN_PERSON", "VIDEO"}),
        "audit_compliance_pct": c["audit_compliance_pct"],
        "created_at": store.fmt_dt(c["created_at"]),
        "updated_at": store.fmt_dt(c["updated_at"]),
        "version": c["version"],
    }


def s_assignment(a):
    return {
        "id": a["id"],
        "case_id": a["case_id"],
        "volunteer_id": a["volunteer_id"],
        "status": a["status"],
        "ended_reason": a["ended_reason"],
        "created_at": store.fmt_dt(a["created_at"]),
        "updated_at": store.fmt_dt(a["updated_at"]),
        "version": a["version"],
    }


def s_visit(v):
    return {
        "id": v["id"],
        "case_id": v["case_id"],
        "volunteer_id": v["volunteer_id"],
        "contact_type": v["contact_type"],
        "contact_start": v["contact_start"],
        "contact_end": v["contact_end"],
        "miles": v["miles"],
        "notes": v["notes"],
        "status": v["status"],
        "duration_minutes": v["duration_minutes"],
        "created_at": store.fmt_dt(v["created_at"]),
        "updated_at": store.fmt_dt(v["updated_at"]),
        "version": v["version"],
    }


def s_hearing(h):
    return {
        "id": h["id"],
        "case_id": h["case_id"],
        "hearing_type": h["hearing_type"],
        "scheduled_at": h["scheduled_at"],
        "status": h["status"],
        "report_due_date": store.fmt_dt(h["report_due_date"]),
        "created_at": store.fmt_dt(h["created_at"]),
        "updated_at": store.fmt_dt(h["updated_at"]),
        "version": h["version"],
    }


def s_report(r):
    return {
        "id": r["id"],
        "case_id": r["case_id"],
        "hearing_id": r["hearing_id"],
        "author_volunteer_id": r["author_volunteer_id"],
        "reviewer_supervisor_id": r["reviewer_supervisor_id"],
        "content_summary": r["content_summary"],
        "recommendation": r["recommendation"],
        "status": r["status"],
        "submitted_at": store.fmt_dt(r["submitted_at"]),
        "revision_count": r["revision_count"],
        "created_at": store.fmt_dt(r["created_at"]),
        "updated_at": store.fmt_dt(r["updated_at"]),
        "version": r["version"],
    }


def s_review_note(n):
    return {
        "id": n["id"],
        "report_id": n["report_id"],
        "supervisor_id": n["supervisor_id"],
        "decision": n["decision"],
        "comments": n["comments"],
        "created_at": store.fmt_dt(n["created_at"]),
    }


def s_background_check(c):
    refresh_check(c)
    return {
        "id": c["id"],
        "volunteer_id": c["volunteer_id"],
        "check_type": c["check_type"],
        "status": c["status"],
        "cleared_at": store.fmt_dt(c["cleared_at"]),
        "expiry_date": store.fmt_dt(c["expiry_date"]),
        "flag_reason": c["flag_reason"],
        "created_at": store.fmt_dt(c["created_at"]),
        "updated_at": store.fmt_dt(c["updated_at"]),
        "version": c["version"],
    }


def s_training_record(t):
    return {
        "id": t["id"],
        "volunteer_id": t["volunteer_id"],
        "module_name": t["module_name"],
        "hours": t["hours"],
        "completed_at": t["completed_at"],
        "created_at": store.fmt_dt(t["created_at"]),
    }


def s_expense_claim(e):
    return {
        "id": e["id"],
        "volunteer_id": e["volunteer_id"],
        "case_id": e["case_id"],
        "period_month": e["period_month"],
        "total_miles": e["total_miles"],
        "other_expense_cents": e["other_expense_cents"],
        "status": e["status"],
        "estimated_reimbursement_cents": e["estimated_reimbursement_cents"],
        "final_reimbursement_cents": e["final_reimbursement_cents"],
        "created_at": store.fmt_dt(e["created_at"]),
        "updated_at": store.fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def paginate(records):
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (ValueError, TypeError):
        limit = 10
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    try:
        offset = int(args.get("offset", 0))
    except (ValueError, TypeError):
        offset = 0
    if offset < 0:
        offset = 0
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    has_more = (offset + len(page)) < total
    lm = {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}
    return page, lm


# ---------------------------------------------------------------------------
# Expense reimbursement calculations
# ---------------------------------------------------------------------------
def provisional_estimate(total_miles, other_expense_cents):
    mileage = int(store.rhu(Decimal(str(total_miles)) * Decimal(STD_RATE_CENTS_PER_MILE), 0))
    return mileage + int(other_expense_cents)


def final_reimbursement(total_miles, other_expense_cents):
    tm = Decimal(str(total_miles))
    tier1 = min(tm, Decimal(TIER1_MILES)) * Decimal(TIER1_RATE_CENTS)
    tier2 = max(Decimal(0), tm - Decimal(TIER1_MILES)) * Decimal(TIER2_RATE_CENTS)
    mileage = int(store.rhu(tier1 + tier2, 0))
    other = min(int(other_expense_cents), OTHER_EXPENSE_CAP_CENTS)
    return min(mileage + other, MONTHLY_REIMBURSEMENT_CAP_CENTS)


# ===========================================================================
# ROUTES
# ===========================================================================

# ---- Logical clock --------------------------------------------------------
@app.route("/_clock/set_current_utc", methods=["POST"])
def clock_set():
    uid, role = get_ctx()
    require_role(role, ["ProgramAdmin"])
    body = get_body()
    raw = require_present(body, "to_iso8601")
    try:
        dt = store.parse_dt(raw)
    except Exception:
        return validation_error("to_iso8601 is not a valid datetime")
    store.set_now(dt)
    return ok({"current_utc": store.fmt_dt(store.now())}, 200)


# ---- Volunteers -----------------------------------------------------------
@app.route("/volunteers", methods=["POST"])
def create_volunteer():
    uid, role = get_ctx()
    require_role(role, ["ProgramAdmin"])
    body = get_body()
    full_name = require_present(body, "full_name")
    email = require_present(body, "email")
    home_zip = require_present(body, "home_zip")
    if not isinstance(full_name, str) or not isinstance(email, str) or not isinstance(home_zip, str):
        return validation_error("full_name, email, home_zip must be strings")
    max_caseload = body.get("max_caseload", 2)
    if max_caseload is None:
        max_caseload = 2
    if not is_int(max_caseload) or max_caseload < 0:
        return validation_error("max_caseload must be a non-negative integer")
    for existing in store.volunteers.values():
        if existing["email"] == email:
            return validation_error("email must be unique among volunteers")
    v = {
        "full_name": full_name,
        "email": email,
        "home_zip": home_zip,
        "max_caseload": max_caseload,
        "status": "PROSPECT",
        "sworn_in_at": None,
        "deactivation_reason": None,
    }
    store.stamp_common(v)
    store.volunteers[v["id"]] = v
    return ok(s_volunteer(v), 201)


@app.route("/volunteers", methods=["GET"])
def list_volunteers():
    uid, role = get_ctx()
    require_role(role, ["ProgramAdmin", "Supervisor"])
    status = request.args.get("status")
    recs = [v for v in store.volunteers.values() if status is None or v["status"] == status]
    page, lm = paginate(recs)
    return ok([s_volunteer(v) for v in page], 200, lm)


@app.route("/volunteers/<vid>", methods=["GET"])
def get_volunteer_route(vid):
    uid, role = get_ctx()
    require_role(role, ["ProgramAdmin", "Supervisor", "Volunteer"])
    v = get_volunteer(vid)
    return ok(s_volunteer(v), 200)


@app.route("/volunteers/<vid>/start-screening", methods=["POST"])
def start_screening(vid):
    uid, role = get_ctx()
    require_role(role, ["ProgramAdmin"])
    v = get_volunteer(vid)
    if v["status"] != "PROSPECT":
        raise ApiError("ERR_INVALID_STATE", 409, "Volunteer is not in PROSPECT")
    v["status"] = "SCREENING"
    store.touch(v)
    return ok(s_volunteer(v), 200)


@app.route("/volunteers/<vid>/swear-in", methods=["POST"])
def swear_in(vid):
    uid, role = get_ctx()
    require_role(role, ["ProgramAdmin"])
    v = get_volunteer(vid)
    if v["status"] != "TRAINING":
        raise ApiError("ERR_INVALID_STATE", 409, "Volunteer is not in TRAINING")
    status, expiry = compute_background(v)
    if status != "CLEARED" or expiry is None or store.now() >= expiry:
        raise ApiError("ERR_BACKGROUND_EXPIRED", 422, "Background not cleared or expired")
    if training_hours_total(vid) < TRAINING_HOURS_REQUIRED:
        raise ApiError("ERR_TRAINING_INCOMPLETE", 422, "Training hours below requirement")
    v["status"] = "ACTIVE"
    v["sworn_in_at"] = store.now()
    store.touch(v)
    return ok(s_volunteer(v), 200)


def _cascade_end_volunteer(v, ended_reason):
    """CASCADE L1-L3 for volunteer deactivate / resign from ACTIVE."""
    for a in list(store.assignments.values()):
        if a["volunteer_id"] == v["id"] and a["status"] == "ACTIVE":
            a["status"] = "ENDED"
            a["ended_reason"] = ended_reason
            store.touch(a)
            case = store.cases.get(a["case_id"])
            if case and case["status"] == "ASSIGNED":
                case["status"] = "UNASSIGNED"
                store.touch(case)
                for r in store.court_reports.values():
                    if r["case_id"] == case["id"] and r["status"] in ("DRAFT", "RETURNED"):
                        r["status"] = "VOIDED"
                        store.touch(r)


@app.route("/volunteers/<vid>/deactivate", methods=["POST"])
def deactivate_volunteer(vid):
    uid, role = get_ctx()
    require_role(role, ["ProgramAdmin"])
    v = get_volunteer(vid)
    if v["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Volunteer is not ACTIVE")
    body = get_body()
    reason = body.get("reason")
    v["status"] = "INACTIVE"
    v["deactivation_reason"] = reason
    store.touch(v)
    _cascade_end_volunteer(v, "VOLUNTEER_DEACTIVATED")
    return ok(s_volunteer(v), 200)


@app.route("/volunteers/<vid>/resign", methods=["POST"])
def resign_volunteer(vid):
    uid, role = get_ctx()
    require_role(role, ["ProgramAdmin"])
    v = get_volunteer(vid)
    if v["status"] not in ("ACTIVE", "INACTIVE"):
        raise ApiError("ERR_INVALID_STATE", 409, "Volunteer cannot resign from this state")
    from_active = v["status"] == "ACTIVE"
    v["status"] = "RESIGNED"
    store.touch(v)
    if from_active:
        _cascade_end_volunteer(v, "VOLUNTEER_DEACTIVATED")
    return ok(s_volunteer(v), 200)


@app.route("/volunteers/<vid>/assignments", methods=["GET"])
def list_volunteer_assignments(vid):
    uid, role = get_ctx()
    require_role(role, ["ProgramAdmin", "Supervisor", "Volunteer"])
    get_volunteer(vid)
    status = request.args.get("status")
    recs = [
        a
        for a in store.assignments.values()
        if a["volunteer_id"] == vid and (status is None or a["status"] == status)
    ]
    page, lm = paginate(recs)
    return ok([s_assignment(a) for a in page], 200, lm)


@app.route("/volunteers/<vid>/visits", methods=["GET"])
def list_volunteer_visits(vid):
    uid, role = get_ctx()
    require_role(role, ["ProgramAdmin", "Supervisor", "Volunteer"])
    get_volunteer(vid)
    status = request.args.get("status")
    recs = [
        v
        for v in store.visits.values()
        if v["volunteer_id"] == vid and (status is None or v["status"] == status)
    ]
    page, lm = paginate(recs)
    return ok([s_visit(v) for v in page], 200, lm)


@app.route("/volunteers/<vid>/training-records", methods=["GET"])
def list_training_records(vid):
    uid, role = get_ctx()
    require_role(role, ["ProgramAdmin", "Supervisor", "Volunteer"])
    get_volunteer(vid)
    recs = [t for t in store.training_records.values() if t["volunteer_id"] == vid]
    page, lm = paginate(recs)
    return ok([s_training_record(t) for t in page], 200, lm)


@app.route("/volunteers/<vid>/training-records", methods=["POST"])
def create_training_record(vid):
    uid, role = get_ctx()
    require_role(role, ["ProgramAdmin", "Volunteer"])
    v = get_volunteer(vid)
    if role == "Volunteer" and uid != vid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Volunteer may only record their own training")
    body = get_body()
    module_name = require_present(body, "module_name")
    hours = require_present(body, "hours")
    completed_at = require_present(body, "completed_at")
    if not isinstance(module_name, str):
        return validation_error("module_name must be a string")
    if not is_number(hours) or hours <= 0:
        return validation_error("hours must be greater than 0")
    try:
        store.parse_dt(completed_at)
    except Exception:
        return validation_error("completed_at must be a valid datetime")
    t = {
        "volunteer_id": vid,
        "module_name": module_name,
        "hours": hours,
        "completed_at": completed_at,
    }
    store.stamp_audit(t)
    store.training_records[t["id"]] = t
    return ok(s_training_record(t), 201)


@app.route("/volunteers/<vid>/background-checks", methods=["GET"])
def list_background_checks(vid):
    uid, role = get_ctx()
    require_role(role, ["ProgramAdmin", "Supervisor"])
    get_volunteer(vid)
    status = request.args.get("status")
    recs = [
        c
        for c in store.background_checks.values()
        if c["volunteer_id"] == vid
    ]
    for c in recs:
        refresh_check(c)
    if status is not None:
        recs = [c for c in recs if c["status"] == status]
    page, lm = paginate(recs)
    return ok([s_background_check(c) for c in page], 200, lm)


@app.route("/volunteers/<vid>/background-checks", methods=["POST"])
def create_background_check(vid):
    uid, role = get_ctx()
    require_role(role, ["ProgramAdmin"])
    v = get_volunteer(vid)
    body = get_body()
    check_type = require_present(body, "check_type")
    if check_type not in ("STATE_ONLY", "STATE_AND_FEDERAL"):
        return validation_error("check_type must be STATE_ONLY or STATE_AND_FEDERAL")
    c = {
        "volunteer_id": vid,
        "check_type": check_type,
        "status": "PENDING",
        "cleared_at": None,
        "expiry_date": None,
        "flag_reason": None,
    }
    store.stamp_common(c)
    store.background_checks[c["id"]] = c
    return ok(s_background_check(c), 201)


# ---- Background check actions --------------------------------------------
@app.route("/background-checks/<bid>/clear", methods=["POST"])
def clear_background_check(bid):
    uid, role = get_ctx()
    require_role(role, ["ProgramAdmin"])
    c = get_background_check(bid)
    if c["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Background check is not PENDING")
    c["cleared_at"] = store.now()
    c["expiry_date"] = store.add_days(store.now(), BACKGROUND_VALID_DAYS)
    c["status"] = "CLEARED"
    store.touch(c)
    v = store.volunteers.get(c["volunteer_id"])
    if v and v["status"] == "SCREENING":
        cs = volunteer_checks(v["id"])
        newest = max(cs, key=lambda x: (x["created_at"], x["_seq"]))
        if newest["id"] == c["id"]:
            v["status"] = "TRAINING"
            store.touch(v)
    return ok(s_background_check(c), 200)


@app.route("/background-checks/<bid>/flag", methods=["POST"])
def flag_background_check(bid):
    uid, role = get_ctx()
    require_role(role, ["ProgramAdmin"])
    c = get_background_check(bid)
    if c["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Background check is not PENDING")
    body = get_body()
    c["flag_reason"] = body.get("reason")
    c["status"] = "FLAGGED"
    store.touch(c)
    return ok(s_background_check(c), 200)


# ---- Supervisors ----------------------------------------------------------
@app.route("/supervisors", methods=["POST"])
def create_supervisor():
    uid, role = get_ctx()
    require_role(role, ["ProgramAdmin"])
    body = get_body()
    full_name = require_present(body, "full_name")
    email = require_present(body, "email")
    if not isinstance(full_name, str) or not isinstance(email, str):
        return validation_error("full_name and email must be strings")
    for existing in store.supervisors.values():
        if existing["email"] == email:
            return validation_error("email must be unique among supervisors")
    s = {"full_name": full_name, "email": email, "status": "ACTIVE"}
    store.stamp_common(s)
    store.supervisors[s["id"]] = s
    return ok(s_supervisor(s), 201)


@app.route("/supervisors/<sid>", methods=["GET"])
def get_supervisor_route(sid):
    uid, role = get_ctx()
    require_role(role, ["ProgramAdmin", "Supervisor"])
    s = get_supervisor(sid)
    return ok(s_supervisor(s), 200)


@app.route("/supervisors/<sid>/review-notes", methods=["GET"])
def list_supervisor_review_notes(sid):
    uid, role = get_ctx()
    require_role(role, ["ProgramAdmin", "Supervisor"])
    get_supervisor(sid)
    recs = [n for n in store.review_notes.values() if n["supervisor_id"] == sid]
    page, lm = paginate(recs)
    return ok([s_review_note(n) for n in page], 200, lm)


# ---- Cases ----------------------------------------------------------------
@app.route("/cases", methods=["POST"])
def create_case():
    uid, role = get_ctx()
    require_role(role, ["ProgramAdmin"])
    body = get_body()
    child_initials = require_present(body, "child_initials")
    child_dob = require_present(body, "child_dob")
    jurisdiction = require_present(body, "jurisdiction")
    supervisor_id = require_present(body, "supervisor_id")
    if not isinstance(child_initials, str) or not isinstance(child_dob, str) or not isinstance(jurisdiction, str):
        return validation_error("child_initials, child_dob, jurisdiction must be strings")
    budget = body.get("reimbursement_budget_cents", 20000)
    if budget is None:
        budget = 20000
    if not is_int(budget) or budget < 0:
        return validation_error("reimbursement_budget_cents must be a non-negative integer")
    # Existence of referenced supervisor (priority 3) before field validity.
    get_supervisor(supervisor_id)
    c = {
        "child_initials": child_initials,
        "child_dob": child_dob,
        "jurisdiction": jurisdiction,
        "supervisor_id": supervisor_id,
        "status": "INTAKE",
        "outcome": None,
        "reimbursement_budget_cents": budget,
        "audit_compliance_pct": None,
    }
    store.stamp_common(c)
    store.cases[c["id"]] = c
    return ok(s_case(c), 201)


@app.route("/cases", methods=["GET"])
def list_cases():
    uid, role = get_ctx()
    require_role(role, ["ProgramAdmin", "Supervisor"])
    supervisor_id = request.args.get("supervisor_id")
    status = request.args.get("status")
    recs = [
        c
        for c in store.cases.values()
        if (supervisor_id is None or c["supervisor_id"] == supervisor_id)
        and (status is None or c["status"] == status)
    ]
    page, lm = paginate(recs)
    return ok([s_case(c) for c in page], 200, lm)


@app.route("/cases/<cid>", methods=["GET"])
def get_case_route(cid):
    uid, role = get_ctx()
    require_role(role, ["ProgramAdmin", "Supervisor", "Volunteer"])
    c = get_case(cid)
    return ok(s_case(c), 200)


@app.route("/cases/<cid>/assignments", methods=["POST"])
def create_assignment(cid):
    uid, role = get_ctx()
    require_role(role, ["Supervisor"])
    c = get_case(cid)
    ensure_case_supervisor(uid, c)
    body = get_body()
    volunteer_id = body.get("volunteer_id")
    expected_version = body.get("expected_case_version")
    # Existence of referenced volunteer (priority 3)
    if volunteer_id is not None:
        vol = get_volunteer(volunteer_id)
    else:
        vol = None
    # State (priority 4): case must be INTAKE or UNASSIGNED
    if c["status"] not in ("INTAKE", "UNASSIGNED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Case is not in INTAKE or UNASSIGNED")
    # State: target volunteer must be ACTIVE
    if vol is not None and vol["status"] != "ACTIVE":
        raise ApiError("ERR_VOLUNTEER_NOT_ACTIVE", 409, "Target volunteer is not ACTIVE")
    # Caseload (priority 8)
    if vol is not None and active_case_count(vol["id"]) >= vol["max_caseload"]:
        raise ApiError("ERR_CASELOAD_EXCEEDED", 409, "Volunteer caseload exceeded")
    # OCC (priority 10) + field validity
    if volunteer_id is None:
        return validation_error("volunteer_id is required")
    if expected_version is None:
        return validation_error("expected_case_version is required")
    if not is_int(expected_version):
        return validation_error("expected_case_version must be an integer")
    if expected_version != c["version"]:
        raise ApiError("ERR_STALE_CASE_VERSION", 412, "expected_case_version does not match")
    # Side effects
    prior = active_assignment_of_case(cid)
    if prior is not None:
        prior["status"] = "ENDED"
        prior["ended_reason"] = "SUPERSEDED"
        store.touch(prior)
    a = {
        "case_id": cid,
        "volunteer_id": volunteer_id,
        "status": "ACTIVE",
        "ended_reason": None,
    }
    store.stamp_common(a)
    store.assignments[a["id"]] = a
    c["status"] = "ASSIGNED"
    store.touch(c)
    return ok(s_assignment(a), 201)


@app.route("/cases/<cid>/assignments", methods=["GET"])
def list_case_assignments(cid):
    uid, role = get_ctx()
    require_role(role, ["ProgramAdmin", "Supervisor", "Volunteer"])
    get_case(cid)
    status = request.args.get("status")
    recs = [
        a
        for a in store.assignments.values()
        if a["case_id"] == cid and (status is None or a["status"] == status)
    ]
    page, lm = paginate(recs)
    return ok([s_assignment(a) for a in page], 200, lm)


@app.route("/cases/<cid>/assignments/<aid>/end", methods=["POST"])
def end_assignment(cid, aid):
    uid, role = get_ctx()
    require_role(role, ["Supervisor"])
    c = get_case(cid)
    a = get_assignment_on_case(cid, aid)
    ensure_case_supervisor(uid, c)
    if c["status"] != "ASSIGNED":
        raise ApiError("ERR_INVALID_STATE", 409, "Case is not ASSIGNED")
    if a["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Assignment is not ACTIVE")
    body = get_body()
    a["status"] = "ENDED"
    a["ended_reason"] = "MANUAL_END"
    store.touch(a)
    c["status"] = "UNASSIGNED"
    store.touch(c)
    return ok(s_assignment(a), 200)


@app.route("/cases/<cid>/close", methods=["POST"])
def close_case(cid):
    uid, role = get_ctx()
    require_role(role, ["Supervisor"])
    c = get_case(cid)
    ensure_case_supervisor(uid, c)
    if c["status"] not in ("ASSIGNED", "UNASSIGNED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Case cannot be closed from this state")
    has_logged = any(
        v["case_id"] == cid and v["status"] == "LOGGED" for v in store.visits.values()
    )
    if not has_logged:
        raise ApiError("ERR_NO_VISITS_LOGGED", 409, "Case has no LOGGED visits")
    body = get_body()
    outcome = require_present(body, "outcome")
    if outcome not in ("REUNIFICATION", "ADOPTION", "GUARDIANSHIP", "APPEAL"):
        return validation_error("invalid outcome")
    c["outcome"] = outcome
    c["audit_compliance_pct"] = compute_compliance(c, {"IN_PERSON"})
    c["status"] = "CLOSED"
    # end active assignment
    prior = active_assignment_of_case(cid)
    if prior is not None:
        prior["status"] = "ENDED"
        prior["ended_reason"] = "CASE_CLOSED"
        store.touch(prior)
    # cancel scheduled hearings
    for h in store.hearings.values():
        if h["case_id"] == cid and h["status"] == "SCHEDULED":
            h["status"] = "CANCELLED"
            store.touch(h)
    store.touch(c)
    return ok(s_case(c), 200)


@app.route("/cases/<cid>/visits", methods=["POST"])
def log_visit(cid):
    uid, role = get_ctx()
    require_role(role, ["Volunteer"])
    c = get_case(cid)
    body = get_body()
    contact_type = body.get("contact_type")
    contact_start = body.get("contact_start")
    contact_end = body.get("contact_end")
    miles = body.get("miles", 0)
    notes = body.get("notes")

    # Temporal (priority 5): visit overlap on acting volunteer's calendar
    start_dt = end_dt = None
    if isinstance(contact_start, str) and isinstance(contact_end, str):
        try:
            start_dt = store.parse_dt(contact_start)
            end_dt = store.parse_dt(contact_end)
        except Exception:
            start_dt = end_dt = None
    if start_dt is not None and end_dt is not None and end_dt > start_dt:
        for v in store.visits.values():
            if v["volunteer_id"] == uid and v["status"] == "LOGGED":
                try:
                    vs = store.parse_dt(v["contact_start"])
                    ve = store.parse_dt(v["contact_end"])
                except Exception:
                    continue
                if start_dt < ve and vs < end_dt:
                    raise ApiError("ERR_VISIT_OVERLAP", 409, "Visit overlaps an existing logged visit")

    # Referential (priority 6): acting volunteer must be case's active-assignment volunteer
    active = active_assignment_of_case(cid)
    if active is None or active["volunteer_id"] != uid:
        raise ApiError("ERR_NOT_ASSIGNED_VOLUNTEER", 409, "Not the case's active-assignment volunteer")

    # Eligibility (priority 7): background must be CLEARED and not expired
    vol = store.volunteers.get(uid)
    if vol is None:
        raise ApiError("ERR_NOT_ASSIGNED_VOLUNTEER", 409, "Acting volunteer not found")
    bstatus, bexpiry = compute_background(vol)
    if bstatus != "CLEARED" or bexpiry is None or store.now() >= bexpiry:
        raise ApiError("ERR_BACKGROUND_EXPIRED", 422, "Background not cleared or expired")

    # Field validity (priority 10)
    if contact_type not in ("IN_PERSON", "VIDEO", "PHONE", "COLLATERAL"):
        return validation_error("invalid contact_type")
    if not isinstance(contact_start, str) or not isinstance(contact_end, str):
        return validation_error("contact_start and contact_end are required")
    try:
        start_dt = store.parse_dt(contact_start)
        end_dt = store.parse_dt(contact_end)
    except Exception:
        return validation_error("invalid contact_start/contact_end")
    if not (end_dt > start_dt):
        return validation_error("contact_end must be strictly after contact_start")
    if miles is None:
        miles = 0
    if not is_number(miles) or miles < 0:
        return validation_error("miles must be >= 0")

    duration = int((end_dt - start_dt).total_seconds() // 60)
    v = {
        "case_id": cid,
        "volunteer_id": uid,
        "contact_type": contact_type,
        "contact_start": contact_start,
        "contact_end": contact_end,
        "miles": miles,
        "notes": notes,
        "status": "LOGGED",
        "duration_minutes": duration,
    }
    store.stamp_common(v)
    store.visits[v["id"]] = v
    return ok(s_visit(v), 201)


@app.route("/cases/<cid>/visits", methods=["GET"])
def list_case_visits(cid):
    uid, role = get_ctx()
    require_role(role, ["ProgramAdmin", "Supervisor", "Volunteer"])
    get_case(cid)
    status = request.args.get("status")
    recs = [
        v
        for v in store.visits.values()
        if v["case_id"] == cid and (status is None or v["status"] == status)
    ]
    page, lm = paginate(recs)
    return ok([s_visit(v) for v in page], 200, lm)


@app.route("/cases/<cid>/hearings", methods=["POST"])
def schedule_hearing(cid):
    uid, role = get_ctx()
    require_role(role, ["Supervisor"])
    c = get_case(cid)
    ensure_case_supervisor(uid, c)
    body = get_body()
    hearing_type = body.get("hearing_type")
    scheduled_at = body.get("scheduled_at")

    # Temporal (priority 5): hearing buffer conflict
    new_dt = None
    if isinstance(scheduled_at, str):
        try:
            new_dt = store.parse_dt(scheduled_at)
        except Exception:
            new_dt = None
    if new_dt is not None:
        for h in store.hearings.values():
            if h["case_id"] == cid and h["status"] == "SCHEDULED":
                try:
                    hd = store.parse_dt(h["scheduled_at"])
                except Exception:
                    continue
                if abs((new_dt - hd).total_seconds()) < HEARING_BUFFER_DAYS * 86400:
                    raise ApiError("ERR_HEARING_BUFFER_CONFLICT", 409, "Hearing within buffer of another")

    # Field validity (priority 10)
    if hearing_type not in ("STATUS", "REVIEW", "PERMANENCY", "ADJUDICATION"):
        return validation_error("invalid hearing_type")
    if not isinstance(scheduled_at, str):
        return validation_error("scheduled_at is required")
    try:
        new_dt = store.parse_dt(scheduled_at)
    except Exception:
        return validation_error("invalid scheduled_at")

    h = {
        "case_id": cid,
        "hearing_type": hearing_type,
        "scheduled_at": scheduled_at,
        "status": "SCHEDULED",
        "report_due_date": store.add_days(new_dt, -REPORT_LEAD_DAYS),
    }
    store.stamp_common(h)
    store.hearings[h["id"]] = h
    return ok(s_hearing(h), 201)


@app.route("/cases/<cid>/hearings", methods=["GET"])
def list_case_hearings(cid):
    uid, role = get_ctx()
    require_role(role, ["ProgramAdmin", "Supervisor", "Volunteer"])
    get_case(cid)
    status = request.args.get("status")
    recs = [
        h
        for h in store.hearings.values()
        if h["case_id"] == cid and (status is None or h["status"] == status)
    ]
    page, lm = paginate(recs)
    return ok([s_hearing(h) for h in page], 200, lm)


@app.route("/cases/<cid>/court-reports", methods=["POST"])
def create_court_report(cid):
    uid, role = get_ctx()
    require_role(role, ["Volunteer"])
    c = get_case(cid)
    body = get_body()
    hearing_id = body.get("hearing_id")
    content_summary = body.get("content_summary")
    recommendation = body.get("recommendation")
    # Existence of referenced hearing (priority 3)
    if hearing_id is None:
        return validation_error("hearing_id is required")
    h = get_hearing(hearing_id)
    # Referential (priority 6): hearing must belong to this case
    if h["case_id"] != cid:
        raise ApiError("ERR_HEARING_CASE_MISMATCH", 409, "Hearing does not belong to this case")
    # Field validity (priority 10)
    if not isinstance(content_summary, str) or content_summary == "":
        return validation_error("content_summary is required")
    if not isinstance(recommendation, str) or recommendation == "":
        return validation_error("recommendation is required")
    r = {
        "case_id": cid,
        "hearing_id": hearing_id,
        "author_volunteer_id": uid,
        "reviewer_supervisor_id": None,
        "content_summary": content_summary,
        "recommendation": recommendation,
        "status": "DRAFT",
        "submitted_at": None,
        "revision_count": 0,
    }
    store.stamp_common(r)
    store.court_reports[r["id"]] = r
    return ok(s_report(r), 201)


# ---- Hearing actions ------------------------------------------------------
def _hearing_transition(hid, target):
    uid, role = get_ctx()
    require_role(role, ["Supervisor"])
    h = get_hearing(hid)
    c = store.cases.get(h["case_id"])
    if c is not None:
        ensure_case_supervisor(uid, c)
    if h["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Hearing is not SCHEDULED")
    h["status"] = target
    store.touch(h)
    return ok(s_hearing(h), 200)


@app.route("/hearings/<hid>/hold", methods=["POST"])
def hold_hearing(hid):
    return _hearing_transition(hid, "HELD")


@app.route("/hearings/<hid>/continue", methods=["POST"])
def continue_hearing(hid):
    return _hearing_transition(hid, "CONTINUED")


@app.route("/hearings/<hid>/cancel", methods=["POST"])
def cancel_hearing(hid):
    return _hearing_transition(hid, "CANCELLED")


# ---- Court reports --------------------------------------------------------
@app.route("/court-reports/<rid>", methods=["GET"])
def get_report_route(rid):
    uid, role = get_ctx()
    require_role(role, ["ProgramAdmin", "Supervisor", "Volunteer"])
    r = get_report(rid)
    return ok(s_report(r), 200)


@app.route("/court-reports", methods=["GET"])
def list_reports():
    uid, role = get_ctx()
    require_role(role, ["ProgramAdmin", "Supervisor"])
    a = request.args
    recs = []
    for r in store.court_reports.values():
        if a.get("case_id") and r["case_id"] != a.get("case_id"):
            continue
        if a.get("hearing_id") and r["hearing_id"] != a.get("hearing_id"):
            continue
        if a.get("author_volunteer_id") and r["author_volunteer_id"] != a.get("author_volunteer_id"):
            continue
        if a.get("reviewer_supervisor_id") and r["reviewer_supervisor_id"] != a.get("reviewer_supervisor_id"):
            continue
        if a.get("status") and r["status"] != a.get("status"):
            continue
        recs.append(r)
    page, lm = paginate(recs)
    return ok([s_report(r) for r in page], 200, lm)


@app.route("/court-reports/<rid>/review-notes", methods=["GET"])
def list_report_review_notes(rid):
    uid, role = get_ctx()
    require_role(role, ["ProgramAdmin", "Supervisor", "Volunteer"])
    get_report(rid)
    recs = [n for n in store.review_notes.values() if n["report_id"] == rid]
    page, lm = paginate(recs)
    return ok([s_review_note(n) for n in page], 200, lm)


@app.route("/court-reports/<rid>/submit", methods=["POST"])
def submit_report(rid):
    uid, role = get_ctx()
    require_role(role, ["Volunteer"])
    r = get_report(rid)
    if uid != r["author_volunteer_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Only the author may submit the report")
    if r["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Report is not DRAFT")
    h = store.hearings.get(r["hearing_id"])
    if h is None or h["status"] != "SCHEDULED":
        raise ApiError("ERR_HEARING_NOT_SCHEDULED", 409, "Linked hearing is not SCHEDULED")
    due = store.add_days(store.parse_dt(h["scheduled_at"]), -REPORT_LEAD_DAYS)
    if store.now() > due:
        raise ApiError("ERR_REPORT_DEADLINE_PASSED", 409, "Report filing deadline passed")
    r["submitted_at"] = store.now()
    r["status"] = "SUBMITTED"
    store.touch(r)
    return ok(s_report(r), 200)


@app.route("/court-reports/<rid>/review", methods=["POST"])
def review_report(rid):
    uid, role = get_ctx()
    require_role(role, ["Supervisor"])
    r = get_report(rid)
    c = store.cases.get(r["case_id"])
    if c is not None:
        ensure_case_supervisor(uid, c)
    if r["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Report is not SUBMITTED")
    body = get_body()
    decision = require_present(body, "decision")
    if decision not in ("APPROVE", "RETURN"):
        return validation_error("decision must be APPROVE or RETURN")
    comments = body.get("comments")
    r["reviewer_supervisor_id"] = uid
    r["status"] = "APPROVED" if decision == "APPROVE" else "RETURNED"
    store.touch(r)
    note = {
        "report_id": rid,
        "supervisor_id": uid,
        "decision": decision,
        "comments": comments,
    }
    store.stamp_audit(note)
    store.review_notes[note["id"]] = note
    return ok(s_report(r), 200)


@app.route("/court-reports/<rid>/revise", methods=["POST"])
def revise_report(rid):
    uid, role = get_ctx()
    require_role(role, ["Volunteer"])
    r = get_report(rid)
    if uid != r["author_volunteer_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Only the author may revise the report")
    if r["status"] != "RETURNED":
        raise ApiError("ERR_INVALID_STATE", 409, "Report is not RETURNED")
    body = get_body()
    if "content_summary" in body and body["content_summary"] is not None:
        if not isinstance(body["content_summary"], str):
            return validation_error("content_summary must be a string")
        r["content_summary"] = body["content_summary"]
    if "recommendation" in body and body["recommendation"] is not None:
        if not isinstance(body["recommendation"], str):
            return validation_error("recommendation must be a string")
        r["recommendation"] = body["recommendation"]
    r["revision_count"] = r["revision_count"] + 1
    r["status"] = "DRAFT"
    store.touch(r)
    return ok(s_report(r), 200)


@app.route("/court-reports/<rid>/file", methods=["POST"])
def file_report(rid):
    uid, role = get_ctx()
    require_role(role, ["Supervisor"])
    r = get_report(rid)
    c = store.cases.get(r["case_id"])
    if c is not None:
        ensure_case_supervisor(uid, c)
    if r["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Report is not APPROVED")
    r["status"] = "FILED"
    store.touch(r)
    return ok(s_report(r), 200)


# ---- Visit action ---------------------------------------------------------
@app.route("/visits/<vid>/void", methods=["POST"])
def void_visit(vid):
    uid, role = get_ctx()
    require_role(role, ["Supervisor", "Volunteer"])
    v = get_visit(vid)
    if role == "Supervisor":
        c = store.cases.get(v["case_id"])
        if c is None or uid != c["supervisor_id"]:
            raise ApiError("ERR_UNAUTHORIZED", 403, "Supervisor does not own this case")
    else:  # Volunteer
        if uid != v["volunteer_id"]:
            raise ApiError("ERR_UNAUTHORIZED", 403, "Volunteer does not own this visit")
    if v["status"] != "LOGGED":
        raise ApiError("ERR_INVALID_STATE", 409, "Visit is not LOGGED")
    v["status"] = "VOIDED"
    store.touch(v)
    return ok(s_visit(v), 200)


# ---- Expense claims -------------------------------------------------------
@app.route("/expense-claims", methods=["POST"])
def submit_expense_claim():
    uid, role = get_ctx()
    require_role(role, ["Volunteer"])
    body = get_body()
    case_id = body.get("case_id")
    period_month = body.get("period_month")
    total_miles = body.get("total_miles")
    other_expense_cents = body.get("other_expense_cents", 0)
    # Existence of referenced case (priority 3)
    if case_id is None:
        return validation_error("case_id is required")
    get_case(case_id)
    # Field validity (priority 10)
    if not isinstance(period_month, str) or period_month == "":
        return validation_error("period_month is required")
    if not is_number(total_miles) or total_miles < 0:
        return validation_error("total_miles must be >= 0")
    if other_expense_cents is None:
        other_expense_cents = 0
    if not is_int(other_expense_cents) or other_expense_cents < 0:
        return validation_error("other_expense_cents must be a non-negative integer")
    est = provisional_estimate(total_miles, other_expense_cents)
    e = {
        "volunteer_id": uid,
        "case_id": case_id,
        "period_month": period_month,
        "total_miles": total_miles,
        "other_expense_cents": other_expense_cents,
        "status": "SUBMITTED",
        "estimated_reimbursement_cents": est,
        "final_reimbursement_cents": None,
    }
    store.stamp_common(e)
    store.expense_claims[e["id"]] = e
    return ok(s_expense_claim(e), 201)


@app.route("/expense-claims/<eid>", methods=["GET"])
def get_expense_claim_route(eid):
    uid, role = get_ctx()
    require_role(role, ["ProgramAdmin", "Supervisor", "Volunteer"])
    e = get_expense_claim(eid)
    return ok(s_expense_claim(e), 200)


@app.route("/expense-claims", methods=["GET"])
def list_expense_claims():
    uid, role = get_ctx()
    require_role(role, ["ProgramAdmin", "Supervisor"])
    a = request.args
    recs = []
    for e in store.expense_claims.values():
        if a.get("volunteer_id") and e["volunteer_id"] != a.get("volunteer_id"):
            continue
        if a.get("case_id") and e["case_id"] != a.get("case_id"):
            continue
        if a.get("status") and e["status"] != a.get("status"):
            continue
        recs.append(e)
    page, lm = paginate(recs)
    return ok([s_expense_claim(e) for e in page], 200, lm)


@app.route("/expense-claims/<eid>/approve", methods=["POST"])
def approve_expense_claim(eid):
    uid, role = get_ctx()
    require_role(role, ["Supervisor"])
    e = get_expense_claim(eid)
    c = store.cases.get(e["case_id"])
    if c is not None:
        ensure_case_supervisor(uid, c)
    if e["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Claim is not SUBMITTED")
    if c is not None and c["status"] == "CLOSED":
        raise ApiError("ERR_CASE_CLOSED", 409, "Case is CLOSED")
    final = final_reimbursement(e["total_miles"], e["other_expense_cents"])
    if c is not None and committed_cents(c["id"]) + final > c["reimbursement_budget_cents"]:
        raise ApiError("ERR_EXPENSE_EXCEEDS_BUDGET", 402, "Approval exceeds case budget")
    e["final_reimbursement_cents"] = final
    e["status"] = "APPROVED"
    store.touch(e)
    return ok(s_expense_claim(e), 200)


@app.route("/expense-claims/<eid>/reject", methods=["POST"])
def reject_expense_claim(eid):
    uid, role = get_ctx()
    require_role(role, ["Supervisor"])
    e = get_expense_claim(eid)
    c = store.cases.get(e["case_id"])
    if c is not None:
        ensure_case_supervisor(uid, c)
    if e["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Claim is not SUBMITTED")
    e["status"] = "REJECTED"
    store.touch(e)
    return ok(s_expense_claim(e), 200)


@app.route("/expense-claims/<eid>/pay", methods=["POST"])
def pay_expense_claim(eid):
    uid, role = get_ctx()
    require_role(role, ["Supervisor", "ProgramAdmin"])
    e = get_expense_claim(eid)
    if e["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Claim is not APPROVED")
    e["status"] = "PAID"
    store.touch(e)
    return ok(s_expense_claim(e), 200)


@app.route("/expense-claims/<eid>/void", methods=["POST"])
def void_expense_claim(eid):
    uid, role = get_ctx()
    require_role(role, ["Supervisor"])
    e = get_expense_claim(eid)
    c = store.cases.get(e["case_id"])
    if c is not None:
        ensure_case_supervisor(uid, c)
    if e["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Claim is not APPROVED")
    e["status"] = "VOIDED"
    store.touch(e)
    return ok(s_expense_claim(e), 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
