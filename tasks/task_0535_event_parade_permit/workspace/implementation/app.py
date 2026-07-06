"""Event Parade Permit API — Flask implementation.

All storage is in-memory (db.py). The store starts empty on every boot; no
entity is seeded. Every precondition a test needs is built via the API surface.
"""
import os
from datetime import timedelta

from flask import Flask, request, jsonify

from common import (
    ApiError, success, error_body, new_id, to_iso, parse_iso, money, D, CLOCK,
)
from db import db

app = Flask(__name__)

VALID_ROLES = {"Applicant", "DepartmentReviewer", "PermitOfficer"}
DEPARTMENTS = ["POLICE", "FIRE", "EMS", "PUBLIC_WORKS"]

APP_TERMINAL = {"DENIED", "CANCELLED", "CLOSED"}
APP_NON_TERMINAL = {"DRAFT", "UNDER_REVIEW", "REVISION_REQUESTED",
                    "CONDITIONALLY_APPROVED", "ISSUED"}

# Fee/deposit/coverage constants
BASE_FEE = {"SMALL": D("150.00"), "MEDIUM": D("400.00"), "LARGE": D("900.00")}
TIER2_RATE = D("0.20")
TIER3_RATE = D("0.35")
SEGMENT_FEE = D("75.00")
CLEANUP_FLOOR = {"SMALL": D("200.00"), "MEDIUM": D("500.00"), "LARGE": D("1500.00")}
PER_HEAD_RATE = D("0.10")
COI_BASE = 1000000
COI_PER_HEAD = 100
COI_CAP = 5000000
OVERHEAD_RATE = D("0.15")


# ===========================================================================
# Response helpers
# ===========================================================================
def respond(data, status=200, response_type="object", pagination=None):
    return jsonify(success(data, response_type, pagination)), status


@app.errorhandler(ApiError)
def handle_api_error(e):
    return jsonify(error_body(e.error_id, e.message)), e.http_status


@app.errorhandler(404)
def handle_404(e):
    return jsonify(error_body("ERR_NOT_FOUND", "Resource not found")), 404


@app.errorhandler(405)
def handle_405(e):
    return jsonify(error_body("ERR_METHOD_NOT_ALLOWED", "Method not allowed")), 405


# ===========================================================================
# Auth / context
# ===========================================================================
def get_context():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in VALID_ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                       "Missing or invalid user context headers")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "Role not permitted for this operation")


def body_json():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


# ===========================================================================
# Pagination
# ===========================================================================
def paginate(items):
    limit_raw = request.args.get("limit", None)
    offset_raw = request.args.get("offset", None)
    try:
        limit = int(limit_raw) if limit_raw is not None else 10
    except (ValueError, TypeError):
        limit = 10
    try:
        offset = int(offset_raw) if offset_raw is not None else 0
    except (ValueError, TypeError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, pagination


def sorted_by_created(items):
    return sorted(items, key=lambda x: (x["created_at"], x["id"]))


# ===========================================================================
# Common field management
# ===========================================================================
def stamp_new(obj):
    now = CLOCK.now_iso()
    obj["id"] = new_id()
    obj["created_at"] = now
    obj["updated_at"] = now
    obj["version"] = 1
    return obj


def touch(obj):
    obj["updated_at"] = CLOCK.now_iso()
    obj["version"] = obj.get("version", 1) + 1
    return obj


# ===========================================================================
# Serialization (computed fields for applications)
# ===========================================================================
def app_reviews(app_id):
    return [r for r in db.reviews.values() if r["application_id"] == app_id]


def app_segments(app_id):
    return [s for s in db.route_segments.values() if s["application_id"] == app_id]


def app_conditions(app_id):
    return [c for c in db.conditions.values() if c["application_id"] == app_id]


def app_cois(app_id):
    return [c for c in db.cois.values() if c["application_id"] == app_id]


def app_deposits(app_id):
    return [d for d in db.deposits.values() if d["application_id"] == app_id]


def app_invoices(app_id):
    return [i for i in db.invoices.values() if i["application_id"] == app_id]


def app_debriefs(app_id):
    return [d for d in db.debriefs.values() if d["application_id"] == app_id]


def compute_quorum(a):
    reviews = app_reviews(a["id"])
    by_dept = {}
    for r in reviews:
        by_dept[r["department"]] = r["status"]
    quorum = all(by_dept.get(d) == "APPROVED" for d in DEPARTMENTS) and len(reviews) >= 4
    veto = any(r["status"] == "VETOED" for r in reviews)
    return quorum, veto


def compute_coi_on_file(a):
    for c in app_cois(a["id"]):
        if c["status"] == "ACCEPTED" and c["coverage_amount"] >= a["required_coverage_min"]:
            return True
    return False


def serialize_application(a):
    quorum, veto = compute_quorum(a)
    return {
        "id": a["id"],
        "applicant_org": a["applicant_org"],
        "applicant_user_id": a["applicant_user_id"],
        "venue_id": a["venue_id"],
        "event_kind": a["event_kind"],
        "permit_class": a["permit_class"],
        "expected_attendance": a["expected_attendance"],
        "occupy_start": a["occupy_start"],
        "occupy_end": a["occupy_end"],
        "status": a["status"],
        "coi_on_file": compute_coi_on_file(a),
        "required_coverage_min": a["required_coverage_min"],
        "application_fee": a["application_fee"],
        "deposit_required": a["deposit_required"],
        "quorum_met": quorum,
        "has_veto": veto,
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


# ===========================================================================
# Calculations
# ===========================================================================
def derive_permit_class(attendance):
    if attendance <= 1000:
        return "SMALL"
    elif attendance <= 5000:
        return "MEDIUM"
    return "LARGE"


def calc_application_fee(a):
    pc = a["permit_class"]
    att = a["expected_attendance"]
    base = BASE_FEE[pc]
    surcharge = D("0")
    if att > 1000:
        surcharge += (D(min(att, 5000)) - D(1000)) * TIER2_RATE
    if att > 5000:
        surcharge += (D(att) - D(5000)) * TIER3_RATE
    surcharge = D(money(surcharge))
    seg_count = len(app_segments(a["id"]))
    closure_fee = D(money(D(seg_count) * SEGMENT_FEE))
    total = base + surcharge + closure_fee
    return money(total)


def calc_deposit(a):
    pc = a["permit_class"]
    att = a["expected_attendance"]
    floor = CLEANUP_FLOOR[pc]
    per_head = D(money(D(att) * PER_HEAD_RATE))
    return money(max(floor, per_head))


def calc_coverage_min(att):
    val = COI_BASE + max(0, att - 1000) * COI_PER_HEAD
    return min(COI_CAP, val)


def recompute_draft_derivations(a):
    a["permit_class"] = derive_permit_class(a["expected_attendance"])
    a["required_coverage_min"] = calc_coverage_min(a["expected_attendance"])
    a["application_fee"] = calc_application_fee(a)
    a["deposit_required"] = calc_deposit(a)


def calc_cost_recovery(app_id, hours_field):
    reviews = app_reviews(app_id)
    subtotal = D("0")
    for r in reviews:
        line = D(money(D(str(r["planned_personnel"])) *
                       D(str(r[hours_field])) *
                       D(str(r["hourly_rate"]))))
        subtotal += line
    total = subtotal * (D("1") + OVERHEAD_RATE)
    return money(total)


# ===========================================================================
# Lookups
# ===========================================================================
def get_applicant_or_404(aid):
    a = db.applicants.get(aid)
    if a is None:
        raise ApiError("ERR_APPLICANT_NOT_FOUND", 404, "Applicant not found")
    return a


def get_venue_or_404(vid):
    v = db.venues.get(vid)
    if v is None:
        raise ApiError("ERR_VENUE_NOT_FOUND", 404, "Venue not found")
    return v


def get_schedule_or_404(sid):
    s = db.closure_schedules.get(sid)
    if s is None:
        raise ApiError("ERR_CLOSURE_SCHEDULE_NOT_FOUND", 404, "Closure schedule not found")
    return s


def get_application_or_404(app_id):
    a = db.applications.get(app_id)
    if a is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND", 404, "Application not found")
    return a


def get_child_or_404(store, cid, app_id, err):
    obj = store.get(cid)
    if obj is None or obj["application_id"] != app_id:
        raise ApiError(err, 404, "Resource not found")
    return obj


def require_owner(a, uid):
    if a["applicant_user_id"] != uid:
        raise ApiError("ERR_NOT_APPLICATION_OWNER", 403, "Not the application owner")


# ===========================================================================
# Serializers for other entities
# ===========================================================================
def serialize_venue(v):
    return dict(v)


def serialize_schedule(s):
    return dict(s)


def serialize_applicant(a):
    return dict(a)


def serialize_segment(s):
    return dict(s)


def serialize_review(r):
    return dict(r)


def serialize_condition(c):
    return dict(c)


def serialize_coi(c):
    return dict(c)


def serialize_deposit(d):
    return dict(d)


def serialize_invoice(i):
    return dict(i)


def serialize_debrief(d):
    return dict(d)


# ===========================================================================
# APPLICANTS
# ===========================================================================
@app.route("/applicants", methods=["POST"])
def create_applicant():
    _, role = get_context()
    require_role(role, {"Applicant", "PermitOfficer"})
    b = body_json()
    obj = {
        "org_name": b.get("org_name"),
        "contact_email": b.get("contact_email"),
    }
    stamp_new(obj)
    db.applicants[obj["id"]] = obj
    return respond(serialize_applicant(obj), 201)


@app.route("/applicants/<applicant_id>", methods=["GET"])
def get_applicant(applicant_id):
    _, role = get_context()
    require_role(role, {"Applicant", "PermitOfficer"})
    a = get_applicant_or_404(applicant_id)
    return respond(serialize_applicant(a), 200)


# ===========================================================================
# VENUES
# ===========================================================================
@app.route("/venues", methods=["POST"])
def create_venue():
    _, role = get_context()
    require_role(role, {"PermitOfficer"})
    b = body_json()
    buf = b.get("setup_buffer_minutes")
    if buf is None:
        buf = 60
    obj = {
        "name": b.get("name"),
        "venue_type": b.get("venue_type"),
        "max_capacity": b.get("max_capacity"),
        "setup_buffer_minutes": buf,
        "status": "ACTIVE",
    }
    stamp_new(obj)
    db.venues[obj["id"]] = obj
    return respond(serialize_venue(obj), 201)


@app.route("/venues", methods=["GET"])
def list_venues():
    _, role = get_context()
    require_role(role, {"Applicant", "PermitOfficer", "DepartmentReviewer"})
    items = sorted_by_created(list(db.venues.values()))
    page, pg = paginate(items)
    return respond([serialize_venue(v) for v in page], 200, "array", pg)


@app.route("/venues/<venue_id>", methods=["GET"])
def get_venue(venue_id):
    _, role = get_context()
    require_role(role, {"Applicant", "PermitOfficer", "DepartmentReviewer"})
    v = get_venue_or_404(venue_id)
    return respond(serialize_venue(v), 200)


@app.route("/venues/<venue_id>/decommission", methods=["POST"])
def decommission_venue(venue_id):
    _, role = get_context()
    require_role(role, {"PermitOfficer"})
    v = get_venue_or_404(venue_id)
    v["status"] = "DECOMMISSIONED"
    touch(v)
    return respond(serialize_venue(v), 200)


# ===========================================================================
# CLOSURE SCHEDULES
# ===========================================================================
@app.route("/closure-schedules", methods=["POST"])
def create_schedule():
    _, role = get_context()
    require_role(role, {"PermitOfficer"})
    b = body_json()
    gap = b.get("min_gap_minutes")
    if gap is None:
        gap = 30
    obj = {
        "corridor_name": b.get("corridor_name"),
        "min_gap_minutes": gap,
        "status": "OPEN",
    }
    stamp_new(obj)
    db.closure_schedules[obj["id"]] = obj
    return respond(serialize_schedule(obj), 201)


@app.route("/closure-schedules", methods=["GET"])
def list_schedules():
    _, role = get_context()
    require_role(role, {"Applicant", "PermitOfficer", "DepartmentReviewer"})
    items = sorted_by_created(list(db.closure_schedules.values()))
    page, pg = paginate(items)
    return respond([serialize_schedule(s) for s in page], 200, "array", pg)


@app.route("/closure-schedules/<schedule_id>", methods=["GET"])
def get_schedule(schedule_id):
    _, role = get_context()
    require_role(role, {"Applicant", "PermitOfficer", "DepartmentReviewer"})
    s = get_schedule_or_404(schedule_id)
    return respond(serialize_schedule(s), 200)


@app.route("/closure-schedules/<schedule_id>/suspend", methods=["POST"])
def suspend_schedule(schedule_id):
    _, role = get_context()
    require_role(role, {"PermitOfficer"})
    s = get_schedule_or_404(schedule_id)
    s["status"] = "SUSPENDED"
    touch(s)
    return respond(serialize_schedule(s), 200)


# ===========================================================================
# PERMIT APPLICATIONS
# ===========================================================================
@app.route("/permit-applications", methods=["POST"])
def create_application():
    uid, role = get_context()
    require_role(role, {"Applicant"})
    b = body_json()
    # time window well-formedness
    start = parse_iso(b.get("occupy_start"))
    end = parse_iso(b.get("occupy_end"))
    if not (end > start):
        raise ApiError("ERR_INVALID_TIME_WINDOW", 422, "occupy_end must be after occupy_start")
    # A reference to a missing venue yields ERR_VENUE_NOT_FOUND (PRD §2.5).
    get_venue_or_404(b.get("venue_id"))
    att = b.get("expected_attendance")
    obj = {
        "applicant_org": b.get("applicant_org"),
        "applicant_user_id": uid,
        "venue_id": b.get("venue_id"),
        "event_kind": b.get("event_kind"),
        "expected_attendance": att,
        "occupy_start": b.get("occupy_start"),
        "occupy_end": b.get("occupy_end"),
        "status": "DRAFT",
        "permit_class": None,
        "required_coverage_min": 0,
        "application_fee": 0,
        "deposit_required": 0,
    }
    stamp_new(obj)
    recompute_draft_derivations(obj)
    db.applications[obj["id"]] = obj
    return respond(serialize_application(obj), 201)


@app.route("/permit-applications", methods=["GET"])
def list_applications():
    _, role = get_context()
    require_role(role, {"Applicant", "PermitOfficer", "DepartmentReviewer"})
    items = list(db.applications.values())
    venue_id = request.args.get("venue_id")
    applicant_user_id = request.args.get("applicant_user_id")
    if venue_id is not None:
        items = [a for a in items if a["venue_id"] == venue_id]
    if applicant_user_id is not None:
        items = [a for a in items if a["applicant_user_id"] == applicant_user_id]
    items = sorted_by_created(items)
    page, pg = paginate(items)
    return respond([serialize_application(a) for a in page], 200, "array", pg)


@app.route("/permit-applications/<app_id>", methods=["GET"])
def get_application(app_id):
    _, role = get_context()
    require_role(role, {"Applicant", "PermitOfficer", "DepartmentReviewer"})
    a = get_application_or_404(app_id)
    return respond(serialize_application(a), 200)


@app.route("/permit-applications/<app_id>", methods=["PATCH"])
def edit_application(app_id):
    uid, role = get_context()
    require_role(role, {"Applicant"})
    a = get_application_or_404(app_id)
    require_owner(a, uid)
    if a["status"] != "DRAFT":
        raise ApiError("ERR_APPLICATION_NOT_DRAFT", 409, "Application is not DRAFT")
    b = body_json()
    new_start = b["occupy_start"] if "occupy_start" in b else a["occupy_start"]
    new_end = b["occupy_end"] if "occupy_end" in b else a["occupy_end"]
    if parse_iso(new_start) >= parse_iso(new_end):
        raise ApiError("ERR_INVALID_TIME_WINDOW", 422, "occupy_end must be after occupy_start")
    if "expected_attendance" in b:
        a["expected_attendance"] = b["expected_attendance"]
    a["occupy_start"] = new_start
    a["occupy_end"] = new_end
    recompute_draft_derivations(a)
    touch(a)
    return respond(serialize_application(a), 200)


def windows_overlap_closed(a_start, a_end, b_start, b_end):
    # closed-interval overlap: touching counts as conflict
    return a_start <= b_end and b_start <= a_end


@app.route("/permit-applications/<app_id>/submit-for-review", methods=["POST"])
def submit_for_review(app_id):
    uid, role = get_context()
    require_role(role, {"Applicant"})
    a = get_application_or_404(app_id)
    require_owner(a, uid)
    # state: DRAFT or REVISION_REQUESTED
    if a["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError("ERR_APPLICATION_NOT_DRAFT", 409, "Application not submittable")
    # route plan
    segs = app_segments(app_id)
    if len(segs) < 1:
        raise ApiError("ERR_ROUTE_PLAN_EMPTY", 409, "No route segments")
    venue = db.venues.get(a["venue_id"])
    # capacity
    if venue is not None and a["expected_attendance"] > venue["max_capacity"]:
        raise ApiError("ERR_CAPACITY_EXCEEDED", 409, "Attendance exceeds venue capacity")
    # double-booking
    if venue is not None:
        buf = timedelta(minutes=venue["setup_buffer_minutes"])
        cand_start = parse_iso(a["occupy_start"]) - buf
        cand_end = parse_iso(a["occupy_end"]) + buf
        for other in db.applications.values():
            if other["id"] == a["id"]:
                continue
            if other["venue_id"] != a["venue_id"]:
                continue
            if other["status"] in APP_TERMINAL or other["status"] == "DRAFT":
                continue
            o_start = parse_iso(other["occupy_start"])
            o_end = parse_iso(other["occupy_end"])
            if windows_overlap_closed(cand_start, cand_end, o_start, o_end):
                raise ApiError("ERR_VENUE_DOUBLE_BOOKED", 409, "Venue double-booked")
    # OCC guard
    b = body_json()
    expected_venue_version = b.get("expected_venue_version")
    if venue is not None:
        if expected_venue_version != venue["version"]:
            raise ApiError("ERR_STALE_VENUE_VERSION", 412, "Stale venue version")

    from_draft = a["status"] == "DRAFT"
    a["status"] = "UNDER_REVIEW"
    if from_draft:
        for dept in DEPARTMENTS:
            r = {
                "application_id": app_id,
                "department": dept,
                "status": "PENDING",
                "planned_personnel": 0,
                "planned_hours": 0,
                "hourly_rate": 0,
                "actual_hours": 0,
                "note": None,
            }
            stamp_new(r)
            db.reviews[r["id"]] = r
        # fee/deposit/coverage already computed; freeze (no more recompute)
    else:
        # resubmit from REVISION_REQUESTED: reset CHANGES_REQUESTED reviews to PENDING
        for r in app_reviews(app_id):
            if r["status"] == "CHANGES_REQUESTED":
                r["status"] = "PENDING"
                touch(r)
    if venue is not None:
        touch(venue)
    touch(a)
    return respond(serialize_application(a), 200)


def release_planned_segments(app_id, venue, from_status_set=("PLANNED",)):
    released = False
    for s in app_segments(app_id):
        if s["status"] in from_status_set:
            s["status"] = "RELEASED"
            touch(s)
            released = True
    return released


@app.route("/permit-applications/<app_id>/cancel", methods=["POST"])
def cancel_application(app_id):
    uid, role = get_context()
    require_role(role, {"Applicant"})
    a = get_application_or_404(app_id)
    require_owner(a, uid)
    status = a["status"]
    if status not in ("DRAFT", "UNDER_REVIEW", "REVISION_REQUESTED", "CONDITIONALLY_APPROVED"):
        raise ApiError("ERR_APPLICATION_NOT_CANCELLABLE", 409, "Not cancellable")
    venue = db.venues.get(a["venue_id"])
    if status == "DRAFT":
        a["status"] = "CANCELLED"
        touch(a)
        return respond(serialize_application(a), 200)
    # UNDER_REVIEW / REVISION_REQUESTED / CONDITIONALLY_APPROVED
    release_planned_segments(app_id, venue)
    if venue is not None:
        touch(venue)
    # waive proposed conditions
    for c in app_conditions(app_id):
        if c["status"] == "PROPOSED":
            c["status"] = "WAIVED"
            touch(c)
    if status == "CONDITIONALLY_APPROVED":
        for d in app_deposits(app_id):
            if d["status"] == "HELD":
                d["forfeited_amount"] = 0
                d["refunded_amount"] = d["amount"]
                d["status"] = "REFUNDED"
                touch(d)
    a["status"] = "CANCELLED"
    touch(a)
    return respond(serialize_application(a), 200)


@app.route("/permit-applications/<app_id>/issue", methods=["POST"])
def issue_application(app_id):
    _, role = get_context()
    require_role(role, {"PermitOfficer"})
    a = get_application_or_404(app_id)
    if a["status"] != "CONDITIONALLY_APPROVED":
        raise ApiError("ERR_APPLICATION_NOT_APPROVABLE", 409, "Not approvable")
    if not compute_coi_on_file(a):
        raise ApiError("ERR_COI_NOT_ON_FILE", 409, "COI not on file")
    held = [d for d in app_deposits(app_id)
            if d["status"] == "HELD" and d["amount"] >= a["deposit_required"]]
    if not held:
        raise ApiError("ERR_DEPOSIT_NOT_HELD", 409, "Deposit not held")
    for c in app_conditions(app_id):
        if c.get("mandatory") and c["status"] != "ACKNOWLEDGED":
            raise ApiError("ERR_UNACKNOWLEDGED_CONDITIONS", 409, "Unacknowledged conditions")
    a["status"] = "ISSUED"
    for s in app_segments(app_id):
        if s["status"] == "PLANNED":
            s["status"] = "ACTIVE"
            touch(s)
    touch(a)
    return respond(serialize_application(a), 200)


# ===========================================================================
# ROUTE SEGMENTS
# ===========================================================================
def check_closure_conflict(schedule, new_start, new_end, exclude_id=None):
    min_gap = timedelta(minutes=schedule["min_gap_minutes"])
    for s in db.route_segments.values():
        if s["closure_schedule_id"] != schedule["id"]:
            continue
        if exclude_id is not None and s["id"] == exclude_id:
            continue
        if s["status"] == "RELEASED":
            continue
        # non-terminal owning application only
        owner = db.applications.get(s["application_id"])
        if owner is not None and owner["status"] in APP_TERMINAL:
            continue
        o_start = parse_iso(s["closure_start"])
        o_end = parse_iso(s["closure_end"])
        # overlap => conflict
        if new_start < o_end and o_start < new_end:
            raise ApiError("ERR_CLOSURE_CONFLICT", 409, "Closure conflict")
        # gap check on either side
        if new_start >= o_end:
            gap = new_start - o_end
        else:
            gap = o_start - new_end
        if gap < min_gap:
            raise ApiError("ERR_CLOSURE_CONFLICT", 409, "Closure conflict")


@app.route("/permit-applications/<app_id>/route-segments", methods=["POST"])
def add_route_segment(app_id):
    uid, role = get_context()
    require_role(role, {"Applicant"})
    a = get_application_or_404(app_id)
    require_owner(a, uid)
    if a["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError("ERR_APPLICATION_NOT_DRAFT", 409, "Application not editable")
    b = body_json()
    schedule = get_schedule_or_404(b.get("closure_schedule_id"))
    start = parse_iso(b.get("closure_start"))
    end = parse_iso(b.get("closure_end"))
    if not (end > start):
        raise ApiError("ERR_INVALID_TIME_WINDOW", 422, "closure_end must be after closure_start")
    if schedule["status"] == "SUSPENDED":
        raise ApiError("ERR_CLOSURE_SCHEDULE_SUSPENDED", 409, "Schedule suspended")
    check_closure_conflict(schedule, start, end)
    obj = {
        "application_id": app_id,
        "closure_schedule_id": schedule["id"],
        "segment_label": b.get("segment_label"),
        "closure_start": b.get("closure_start"),
        "closure_end": b.get("closure_end"),
        "status": "PLANNED",
    }
    stamp_new(obj)
    db.route_segments[obj["id"]] = obj
    if a["status"] == "DRAFT":
        a["application_fee"] = calc_application_fee(a)
        touch(a)
    return respond(serialize_segment(obj), 201)


@app.route("/permit-applications/<app_id>/route-segments", methods=["GET"])
def list_app_segments(app_id):
    _, role = get_context()
    require_role(role, {"Applicant", "PermitOfficer", "DepartmentReviewer"})
    get_application_or_404(app_id)
    items = sorted_by_created(app_segments(app_id))
    page, pg = paginate(items)
    return respond([serialize_segment(s) for s in page], 200, "array", pg)


@app.route("/permit-applications/<app_id>/route-segments/<segment_id>", methods=["GET"])
def get_app_segment(app_id, segment_id):
    _, role = get_context()
    require_role(role, {"Applicant", "PermitOfficer", "DepartmentReviewer"})
    get_application_or_404(app_id)
    s = get_child_or_404(db.route_segments, segment_id, app_id, "ERR_SEGMENT_NOT_FOUND")
    return respond(serialize_segment(s), 200)


@app.route("/route-segments", methods=["GET"])
def list_segments():
    _, role = get_context()
    require_role(role, {"Applicant", "PermitOfficer", "DepartmentReviewer"})
    items = list(db.route_segments.values())
    csid = request.args.get("closure_schedule_id")
    aid = request.args.get("application_id")
    if csid is not None:
        items = [s for s in items if s["closure_schedule_id"] == csid]
    if aid is not None:
        items = [s for s in items if s["application_id"] == aid]
    items = sorted_by_created(items)
    page, pg = paginate(items)
    return respond([serialize_segment(s) for s in page], 200, "array", pg)


@app.route("/route-segments/<segment_id>", methods=["GET"])
def get_segment(segment_id):
    _, role = get_context()
    require_role(role, {"Applicant", "PermitOfficer", "DepartmentReviewer"})
    s = db.route_segments.get(segment_id)
    if s is None:
        raise ApiError("ERR_SEGMENT_NOT_FOUND", 404, "Segment not found")
    return respond(serialize_segment(s), 200)


# ===========================================================================
# DEPARTMENT REVIEWS
# ===========================================================================
def reviewer_department(uid):
    return uid


def check_reviewer_dept(uid, review):
    if reviewer_department(uid) != review["department"]:
        raise ApiError("ERR_DEPARTMENT_MISMATCH", 403, "Department mismatch")


@app.route("/permit-applications/<app_id>/reviews", methods=["GET"])
def list_app_reviews(app_id):
    _, role = get_context()
    require_role(role, {"Applicant", "PermitOfficer", "DepartmentReviewer"})
    get_application_or_404(app_id)
    items = sorted_by_created(app_reviews(app_id))
    page, pg = paginate(items)
    return respond([serialize_review(r) for r in page], 200, "array", pg)


@app.route("/permit-applications/<app_id>/reviews/<review_id>", methods=["GET"])
def get_app_review(app_id, review_id):
    _, role = get_context()
    require_role(role, {"Applicant", "PermitOfficer", "DepartmentReviewer"})
    get_application_or_404(app_id)
    r = get_child_or_404(db.reviews, review_id, app_id, "ERR_REVIEW_NOT_FOUND")
    return respond(serialize_review(r), 200)


def apply_denial_cascade(a):
    venue = db.venues.get(a["venue_id"])
    for s in app_segments(a["id"]):
        if s["status"] == "PLANNED":
            s["status"] = "RELEASED"
            touch(s)
    if venue is not None:
        touch(venue)
    for c in app_conditions(a["id"]):
        if c["status"] not in ("WAIVED",):
            c["status"] = "WAIVED"
            touch(c)
    a["status"] = "DENIED"
    touch(a)


def create_or_refresh_invoice(a):
    estimate = calc_cost_recovery(a["id"], "planned_hours")
    fee = a["application_fee"]
    existing = app_invoices(a["id"])
    if existing:
        inv = existing[0]
        inv["fee_component"] = fee
        inv["cost_recovery_estimate"] = estimate
        inv["cost_recovery_actual"] = 0
        inv["balance_due"] = money(D(str(fee)) + D(str(estimate)))
        inv["status"] = "OPEN"
        touch(inv)
    else:
        inv = {
            "application_id": a["id"],
            "fee_component": fee,
            "cost_recovery_estimate": estimate,
            "cost_recovery_actual": 0,
            "balance_due": money(D(str(fee)) + D(str(estimate))),
            "status": "OPEN",
        }
        stamp_new(inv)
        db.invoices[inv["id"]] = inv


def maybe_conditionally_approve(a):
    quorum, veto = compute_quorum(a)
    if quorum and not veto and a["status"] == "UNDER_REVIEW":
        a["status"] = "CONDITIONALLY_APPROVED"
        create_or_refresh_invoice(a)
        touch(a)


@app.route("/permit-applications/<app_id>/reviews/<review_id>/approve", methods=["POST"])
def approve_review(app_id, review_id):
    uid, role = get_context()
    require_role(role, {"DepartmentReviewer"})
    a = get_application_or_404(app_id)
    r = get_child_or_404(db.reviews, review_id, app_id, "ERR_REVIEW_NOT_FOUND")
    if r["status"] != "PENDING":
        raise ApiError("ERR_REVIEW_NOT_PENDING", 409, "Review not pending")
    check_reviewer_dept(uid, r)
    if a["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_APPLICATION_NOT_UNDER_REVIEW", 409, "Application not under review")
    b = body_json()
    if "planned_personnel" in b and b["planned_personnel"] is not None:
        r["planned_personnel"] = b["planned_personnel"]
    if "planned_hours" in b and b["planned_hours"] is not None:
        r["planned_hours"] = b["planned_hours"]
    if "hourly_rate" in b and b["hourly_rate"] is not None:
        r["hourly_rate"] = b["hourly_rate"]
    r["status"] = "APPROVED"
    touch(r)
    maybe_conditionally_approve(a)
    return respond(serialize_review(r), 200)


@app.route("/permit-applications/<app_id>/reviews/<review_id>/request-changes", methods=["POST"])
def request_changes_review(app_id, review_id):
    uid, role = get_context()
    require_role(role, {"DepartmentReviewer"})
    a = get_application_or_404(app_id)
    r = get_child_or_404(db.reviews, review_id, app_id, "ERR_REVIEW_NOT_FOUND")
    if r["status"] != "PENDING":
        raise ApiError("ERR_REVIEW_NOT_PENDING", 409, "Review not pending")
    check_reviewer_dept(uid, r)
    if a["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_APPLICATION_NOT_UNDER_REVIEW", 409, "Application not under review")
    b = body_json()
    if "note" in b:
        r["note"] = b["note"]
    r["status"] = "CHANGES_REQUESTED"
    touch(r)
    a["status"] = "REVISION_REQUESTED"
    touch(a)
    return respond(serialize_review(r), 200)


@app.route("/permit-applications/<app_id>/reviews/<review_id>/veto", methods=["POST"])
def veto_review(app_id, review_id):
    uid, role = get_context()
    require_role(role, {"DepartmentReviewer"})
    a = get_application_or_404(app_id)
    r = get_child_or_404(db.reviews, review_id, app_id, "ERR_REVIEW_NOT_FOUND")
    if r["status"] != "PENDING":
        raise ApiError("ERR_REVIEW_NOT_PENDING", 409, "Review not pending")
    check_reviewer_dept(uid, r)
    if a["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_APPLICATION_NOT_UNDER_REVIEW", 409, "Application not under review")
    b = body_json()
    note = b.get("note")
    if not note:
        raise ApiError("ERR_VETO_REASON_REQUIRED", 422, "Veto reason required")
    r["note"] = note
    r["status"] = "VETOED"
    touch(r)
    apply_denial_cascade(a)
    return respond(serialize_review(r), 200)


@app.route("/permit-applications/<app_id>/reviews/<review_id>/log-actuals", methods=["POST"])
def log_actuals(app_id, review_id):
    uid, role = get_context()
    require_role(role, {"DepartmentReviewer"})
    a = get_application_or_404(app_id)
    r = get_child_or_404(db.reviews, review_id, app_id, "ERR_REVIEW_NOT_FOUND")
    check_reviewer_dept(uid, r)
    if a["status"] != "ISSUED":
        raise ApiError("ERR_APPLICATION_NOT_ISSUED", 409, "Application not issued")
    b = body_json()
    r["actual_hours"] = b.get("actual_hours", 0)
    touch(r)
    return respond(serialize_review(r), 200)


@app.route("/department-reviews", methods=["GET"])
def list_reviews():
    _, role = get_context()
    require_role(role, {"Applicant", "PermitOfficer", "DepartmentReviewer"})
    items = list(db.reviews.values())
    aid = request.args.get("application_id")
    if aid is not None:
        items = [r for r in items if r["application_id"] == aid]
    items = sorted_by_created(items)
    page, pg = paginate(items)
    return respond([serialize_review(r) for r in page], 200, "array", pg)


@app.route("/department-reviews/<review_id>", methods=["GET"])
def get_review(review_id):
    _, role = get_context()
    require_role(role, {"Applicant", "PermitOfficer", "DepartmentReviewer"})
    r = db.reviews.get(review_id)
    if r is None:
        raise ApiError("ERR_REVIEW_NOT_FOUND", 404, "Review not found")
    return respond(serialize_review(r), 200)


# ===========================================================================
# PERMIT CONDITIONS
# ===========================================================================
@app.route("/permit-applications/<app_id>/reviews/<review_id>/conditions", methods=["POST"])
def create_condition(app_id, review_id):
    uid, role = get_context()
    require_role(role, {"DepartmentReviewer"})
    a = get_application_or_404(app_id)
    r = get_child_or_404(db.reviews, review_id, app_id, "ERR_REVIEW_NOT_FOUND")
    check_reviewer_dept(uid, r)
    b = body_json()
    mandatory = b.get("mandatory")
    if mandatory is None:
        mandatory = True
    obj = {
        "application_id": app_id,
        "department_review_id": review_id,
        "text": b.get("text"),
        "mandatory": mandatory,
        "status": "PROPOSED",
    }
    stamp_new(obj)
    db.conditions[obj["id"]] = obj
    return respond(serialize_condition(obj), 201)


@app.route("/permit-applications/<app_id>/conditions", methods=["GET"])
def list_app_conditions(app_id):
    _, role = get_context()
    require_role(role, {"Applicant", "PermitOfficer", "DepartmentReviewer"})
    get_application_or_404(app_id)
    items = sorted_by_created(app_conditions(app_id))
    page, pg = paginate(items)
    return respond([serialize_condition(c) for c in page], 200, "array", pg)


@app.route("/permit-applications/<app_id>/reviews/<review_id>/conditions", methods=["GET"])
def list_review_conditions(app_id, review_id):
    _, role = get_context()
    require_role(role, {"Applicant", "PermitOfficer", "DepartmentReviewer"})
    get_application_or_404(app_id)
    get_child_or_404(db.reviews, review_id, app_id, "ERR_REVIEW_NOT_FOUND")
    items = [c for c in app_conditions(app_id) if c["department_review_id"] == review_id]
    items = sorted_by_created(items)
    page, pg = paginate(items)
    return respond([serialize_condition(c) for c in page], 200, "array", pg)


@app.route("/permit-applications/<app_id>/conditions/<condition_id>/acknowledge", methods=["POST"])
def acknowledge_condition(app_id, condition_id):
    uid, role = get_context()
    require_role(role, {"Applicant"})
    a = get_application_or_404(app_id)
    c = get_child_or_404(db.conditions, condition_id, app_id, "ERR_CONDITION_NOT_FOUND")
    require_owner(a, uid)
    if c["status"] != "PROPOSED":
        raise ApiError("ERR_CONDITION_NOT_PROPOSED", 409, "Condition not proposed")
    c["status"] = "ACKNOWLEDGED"
    touch(c)
    return respond(serialize_condition(c), 200)


@app.route("/permit-conditions", methods=["GET"])
def list_conditions():
    _, role = get_context()
    require_role(role, {"Applicant", "PermitOfficer", "DepartmentReviewer"})
    items = list(db.conditions.values())
    aid = request.args.get("application_id")
    drid = request.args.get("department_review_id")
    if aid is not None:
        items = [c for c in items if c["application_id"] == aid]
    if drid is not None:
        items = [c for c in items if c["department_review_id"] == drid]
    items = sorted_by_created(items)
    page, pg = paginate(items)
    return respond([serialize_condition(c) for c in page], 200, "array", pg)


@app.route("/permit-conditions/<condition_id>", methods=["GET"])
def get_condition(condition_id):
    _, role = get_context()
    require_role(role, {"Applicant", "PermitOfficer", "DepartmentReviewer"})
    c = db.conditions.get(condition_id)
    if c is None:
        raise ApiError("ERR_CONDITION_NOT_FOUND", 404, "Condition not found")
    return respond(serialize_condition(c), 200)


# ===========================================================================
# INSURANCE CERTIFICATES (COI)
# ===========================================================================
@app.route("/permit-applications/<app_id>/coi", methods=["POST"])
def submit_coi(app_id):
    uid, role = get_context()
    require_role(role, {"Applicant"})
    a = get_application_or_404(app_id)
    require_owner(a, uid)
    b = body_json()
    obj = {
        "application_id": app_id,
        "carrier": b.get("carrier"),
        "coverage_amount": b.get("coverage_amount"),
        "expires_at": b.get("expires_at"),
        "status": "SUBMITTED",
    }
    stamp_new(obj)
    db.cois[obj["id"]] = obj
    return respond(serialize_coi(obj), 201)


@app.route("/permit-applications/<app_id>/coi", methods=["GET"])
def list_app_cois(app_id):
    _, role = get_context()
    require_role(role, {"Applicant", "PermitOfficer", "DepartmentReviewer"})
    get_application_or_404(app_id)
    items = sorted_by_created(app_cois(app_id))
    page, pg = paginate(items)
    return respond([serialize_coi(c) for c in page], 200, "array", pg)


@app.route("/permit-applications/<app_id>/coi/<coi_id>/accept", methods=["POST"])
def accept_coi(app_id, coi_id):
    _, role = get_context()
    require_role(role, {"PermitOfficer"})
    a = get_application_or_404(app_id)
    c = get_child_or_404(db.cois, coi_id, app_id, "ERR_COI_NOT_FOUND")
    if c["status"] != "SUBMITTED":
        raise ApiError("ERR_COI_NOT_SUBMITTED", 409, "COI not submitted")
    if parse_iso(c["expires_at"]) <= parse_iso(a["occupy_end"]):
        raise ApiError("ERR_COI_EXPIRES_BEFORE_EVENT", 409, "COI expires before event")
    if c["coverage_amount"] < a["required_coverage_min"]:
        raise ApiError("ERR_COI_COVERAGE_INSUFFICIENT", 402, "COI coverage insufficient")
    # demote any previously ACCEPTED
    for other in app_cois(app_id):
        if other["id"] != coi_id and other["status"] == "ACCEPTED":
            other["status"] = "SUBMITTED"
            touch(other)
    c["status"] = "ACCEPTED"
    touch(c)
    touch(a)
    return respond(serialize_coi(c), 200)


@app.route("/permit-applications/<app_id>/coi/<coi_id>/reject", methods=["POST"])
def reject_coi(app_id, coi_id):
    _, role = get_context()
    require_role(role, {"PermitOfficer"})
    a = get_application_or_404(app_id)
    c = get_child_or_404(db.cois, coi_id, app_id, "ERR_COI_NOT_FOUND")
    if c["status"] != "SUBMITTED":
        raise ApiError("ERR_COI_NOT_SUBMITTED", 409, "COI not submitted")
    c["status"] = "REJECTED"
    touch(c)
    touch(a)
    return respond(serialize_coi(c), 200)


@app.route("/insurance-certificates", methods=["GET"])
def list_cois():
    _, role = get_context()
    require_role(role, {"Applicant", "PermitOfficer", "DepartmentReviewer"})
    items = list(db.cois.values())
    aid = request.args.get("application_id")
    if aid is not None:
        items = [c for c in items if c["application_id"] == aid]
    items = sorted_by_created(items)
    page, pg = paginate(items)
    return respond([serialize_coi(c) for c in page], 200, "array", pg)


@app.route("/insurance-certificates/<coi_id>", methods=["GET"])
def get_coi(coi_id):
    _, role = get_context()
    require_role(role, {"Applicant", "PermitOfficer", "DepartmentReviewer"})
    c = db.cois.get(coi_id)
    if c is None:
        raise ApiError("ERR_COI_NOT_FOUND", 404, "COI not found")
    return respond(serialize_coi(c), 200)


# ===========================================================================
# DEPOSIT
# ===========================================================================
@app.route("/permit-applications/<app_id>/deposit", methods=["POST"])
def pay_deposit(app_id):
    uid, role = get_context()
    require_role(role, {"Applicant"})
    a = get_application_or_404(app_id)
    require_owner(a, uid)
    b = body_json()
    amount = b.get("amount")
    if amount is None or amount < a["deposit_required"]:
        raise ApiError("ERR_DEPOSIT_UNDERFUNDED", 402, "Deposit underfunded")
    obj = {
        "application_id": app_id,
        "amount": amount,
        "status": "HELD",
        "forfeited_amount": 0,
        "refunded_amount": 0,
    }
    stamp_new(obj)
    db.deposits[obj["id"]] = obj
    return respond(serialize_deposit(obj), 201)


@app.route("/permit-applications/<app_id>/deposit", methods=["GET"])
def list_app_deposits(app_id):
    _, role = get_context()
    require_role(role, {"Applicant", "PermitOfficer", "DepartmentReviewer"})
    get_application_or_404(app_id)
    items = sorted_by_created(app_deposits(app_id))
    page, pg = paginate(items)
    return respond([serialize_deposit(d) for d in page], 200, "array", pg)


@app.route("/deposits", methods=["GET"])
def list_deposits():
    _, role = get_context()
    require_role(role, {"Applicant", "PermitOfficer", "DepartmentReviewer"})
    items = list(db.deposits.values())
    aid = request.args.get("application_id")
    if aid is not None:
        items = [d for d in items if d["application_id"] == aid]
    items = sorted_by_created(items)
    page, pg = paginate(items)
    return respond([serialize_deposit(d) for d in page], 200, "array", pg)


@app.route("/deposits/<deposit_id>", methods=["GET"])
def get_deposit(deposit_id):
    _, role = get_context()
    require_role(role, {"Applicant", "PermitOfficer", "DepartmentReviewer"})
    d = db.deposits.get(deposit_id)
    if d is None:
        raise ApiError("ERR_DEPOSIT_NOT_FOUND", 404, "Deposit not found")
    return respond(serialize_deposit(d), 200)


# ===========================================================================
# INVOICE
# ===========================================================================
@app.route("/permit-applications/<app_id>/invoice", methods=["GET"])
def list_app_invoices(app_id):
    _, role = get_context()
    require_role(role, {"Applicant", "PermitOfficer", "DepartmentReviewer"})
    get_application_or_404(app_id)
    items = sorted_by_created(app_invoices(app_id))
    page, pg = paginate(items)
    return respond([serialize_invoice(i) for i in page], 200, "array", pg)


@app.route("/invoices", methods=["GET"])
def list_invoices():
    _, role = get_context()
    require_role(role, {"Applicant", "PermitOfficer", "DepartmentReviewer"})
    items = list(db.invoices.values())
    aid = request.args.get("application_id")
    if aid is not None:
        items = [i for i in items if i["application_id"] == aid]
    items = sorted_by_created(items)
    page, pg = paginate(items)
    return respond([serialize_invoice(i) for i in page], 200, "array", pg)


@app.route("/invoices/<invoice_id>", methods=["GET"])
def get_invoice(invoice_id):
    _, role = get_context()
    require_role(role, {"Applicant", "PermitOfficer", "DepartmentReviewer"})
    i = db.invoices.get(invoice_id)
    if i is None:
        raise ApiError("ERR_INVOICE_NOT_FOUND", 404, "Invoice not found")
    return respond(serialize_invoice(i), 200)


# ===========================================================================
# CLEANUP DEBRIEF
# ===========================================================================
@app.route("/permit-applications/<app_id>/debrief", methods=["POST"])
def open_debrief(app_id):
    _, role = get_context()
    require_role(role, {"PermitOfficer"})
    a = get_application_or_404(app_id)
    if a["status"] != "ISSUED":
        raise ApiError("ERR_APPLICATION_NOT_ISSUED", 409, "Application not issued")
    b = body_json()
    obj = {
        "application_id": app_id,
        "actual_attendance": b.get("actual_attendance"),
        "cleanup_charges": b.get("cleanup_charges") if b.get("cleanup_charges") is not None else 0,
        "incident_count": b.get("incident_count") if b.get("incident_count") is not None else 0,
        "status": "OPEN",
    }
    stamp_new(obj)
    db.debriefs[obj["id"]] = obj
    return respond(serialize_debrief(obj), 201)


@app.route("/permit-applications/<app_id>/debrief", methods=["GET"])
def list_app_debriefs(app_id):
    _, role = get_context()
    require_role(role, {"Applicant", "PermitOfficer", "DepartmentReviewer"})
    get_application_or_404(app_id)
    items = sorted_by_created(app_debriefs(app_id))
    page, pg = paginate(items)
    return respond([serialize_debrief(d) for d in page], 200, "array", pg)


@app.route("/permit-applications/<app_id>/debrief/<debrief_id>/finalize", methods=["POST"])
def finalize_debrief(app_id, debrief_id):
    _, role = get_context()
    require_role(role, {"PermitOfficer"})
    a = get_application_or_404(app_id)
    d = get_child_or_404(db.debriefs, debrief_id, app_id, "ERR_DEBRIEF_NOT_FOUND")
    if a["status"] != "ISSUED":
        raise ApiError("ERR_APPLICATION_NOT_ISSUED", 409, "Application not issued")
    if d["status"] != "OPEN":
        raise ApiError("ERR_DEBRIEF_NOT_OPEN", 409, "Debrief not open")
    # cost recovery actual + invoice true-up
    actual = calc_cost_recovery(app_id, "actual_hours")
    for inv in app_invoices(app_id):
        inv["cost_recovery_actual"] = actual
        inv["balance_due"] = money(D(str(inv["fee_component"])) + D(str(actual)))
        inv["status"] = "SETTLED"
        touch(inv)
    # deposit reconciliation
    cleanup = d["cleanup_charges"] or 0
    for dep in app_deposits(app_id):
        if dep["status"] == "HELD":
            forfeited = money(min(D(str(dep["amount"])), D(str(cleanup))))
            refunded = money(D(str(dep["amount"])) - D(str(forfeited)))
            dep["forfeited_amount"] = forfeited
            dep["refunded_amount"] = refunded
            dep["status"] = "FORFEITED_PARTIAL" if cleanup > 0 else "REFUNDED"
            touch(dep)
    # release ACTIVE segments
    venue = db.venues.get(a["venue_id"])
    for s in app_segments(app_id):
        if s["status"] == "ACTIVE":
            s["status"] = "RELEASED"
            touch(s)
    if venue is not None:
        touch(venue)
    d["status"] = "FINALIZED"
    touch(d)
    a["status"] = "CLOSED"
    touch(a)
    return respond(serialize_debrief(d), 200)


@app.route("/cleanup-debriefs", methods=["GET"])
def list_debriefs():
    _, role = get_context()
    require_role(role, {"Applicant", "PermitOfficer", "DepartmentReviewer"})
    items = list(db.debriefs.values())
    aid = request.args.get("application_id")
    if aid is not None:
        items = [d for d in items if d["application_id"] == aid]
    items = sorted_by_created(items)
    page, pg = paginate(items)
    return respond([serialize_debrief(d) for d in page], 200, "array", pg)


@app.route("/cleanup-debriefs/<debrief_id>", methods=["GET"])
def get_debrief(debrief_id):
    _, role = get_context()
    require_role(role, {"Applicant", "PermitOfficer", "DepartmentReviewer"})
    d = db.debriefs.get(debrief_id)
    if d is None:
        raise ApiError("ERR_DEBRIEF_NOT_FOUND", 404, "Debrief not found")
    return respond(serialize_debrief(d), 200)


# ===========================================================================
# CLOCK
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_context()
    require_role(role, {"PermitOfficer"})
    b = body_json()
    CLOCK.current_utc = parse_iso(b.get("to_iso8601"))
    return respond({"current_utc": CLOCK.now_iso()}, 200)


# ===========================================================================
# Entry point
# ===========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
