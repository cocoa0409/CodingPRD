"""Household, IncomeCertification, and EducationCompletion endpoints."""
from flask import Blueprint, jsonify

import db
import engine
from auth import require, require_household_owner
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_SO_DUTY_VIOLATION,
)
from scope import (
    get_cert_or_404, get_household_or_404, get_program_or_404,
)
from util import (
    body, bump, new_entity, ok_object, opt_str, paginated, query_str,
    req_int, req_dt, req_num, req_str, ser_cert, ser_completion, ser_household,
)

bp = Blueprint("households", __name__)

STAFF_READ = ["PlatformAdmin", "ProgramAdmin", "ComplianceOfficer",
              "LeaseManager", "IntakeSpecialist"]
STAFF_AND_HOUSEHOLD = STAFF_READ + ["Household"]


# ---------------------------------------------------------------------------
# Households
# ---------------------------------------------------------------------------

@bp.post("/programs/<pid>/households")
@require(["IntakeSpecialist"])
def create_household(pid):
    program = get_program_or_404(pid)
    if program["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Program is not ACTIVE; new households cannot be created")
    data = body()
    legal_name = req_str(data, "legal_name")
    size = req_int(data, "household_size")
    if size < 1:
        raise ApiError(ERR_INVALID_REQUEST, 400, "household_size must be >= 1")
    income = req_int(data, "annual_gross_income_cents")
    notes = opt_str(data, "notes", "")

    h = new_entity()
    h.update({
        "program_id": pid,
        "legal_name": legal_name,
        "household_size": size,
        "annual_gross_income_cents": income,
        "ami_pct": None,
        "eligibility_status": "PENDING",
        "eligibility_expires_at": None,
        "education_required": True,
        "education_completed_at": None,
        "active_lease_id": None,
        "waitlist_entry_id": None,
        "notes": notes,
        "_eligibility_lost_at": None,
    })
    db.store.households[h["id"]] = h
    return jsonify(ok_object(ser_household(h))), 201


@bp.get("/programs/<pid>/households")
@require(STAFF_READ)
def list_households(pid):
    get_program_or_404(pid)
    items = [h for h in db.store.households.values() if h["program_id"] == pid]
    status = query_str("eligibility_status")
    if status:
        items = [h for h in items if h["eligibility_status"] == status]
    return jsonify(paginated(items, ser_household)), 200


@bp.get("/programs/<pid>/households/<hid>")
@require(STAFF_AND_HOUSEHOLD)
def get_household(pid, hid):
    h = get_household_or_404(pid, hid)
    require_household_owner(h["id"])
    return jsonify(ok_object(ser_household(h))), 200


@bp.post("/programs/<pid>/households/<hid>/suspend")
@require(["LeaseManager"])
def suspend_household(pid, hid):
    h = get_household_or_404(pid, hid)
    if h["eligibility_status"] not in ("ELIGIBLE", "EXPIRED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an ELIGIBLE or EXPIRED household can be suspended")
    now = db.get_now()
    h["eligibility_status"] = "SUSPENDED"
    h["_eligibility_lost_at"] = now
    bump(h)
    for entry in db.store.waitlist.values():
        if entry["household_id"] == h["id"] and entry["status"] == "ACTIVE":
            entry["status"] = "WITHDRAWN"
            bump(entry)
            if h["waitlist_entry_id"] == entry["id"]:
                h["waitlist_entry_id"] = None
    return jsonify(ok_object(ser_household(h))), 200


@bp.post("/programs/<pid>/households/<hid>/reinstate")
@require(["LeaseManager"])
def reinstate_household(pid, hid):
    h = get_household_or_404(pid, hid)
    if h["eligibility_status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a SUSPENDED household can be reinstated")
    h["eligibility_status"] = "PENDING"
    bump(h)
    return jsonify(ok_object(ser_household(h))), 200


# ---------------------------------------------------------------------------
# IncomeCertifications
# ---------------------------------------------------------------------------

@bp.post("/programs/<pid>/households/<hid>/income-certifications")
@require(["IntakeSpecialist", "Household"])
def create_cert(pid, hid):
    h = get_household_or_404(pid, hid)
    require_household_owner(h["id"])
    program = get_program_or_404(pid)
    data = body()
    tax_year = req_int(data, "tax_year")
    reported = req_int(data, "reported_annual_income_cents")
    verified = req_int(data, "verified_annual_income_cents")
    size_at_cert = req_int(data, "household_size_at_cert")
    if size_at_cert < 1:
        raise ApiError(ERR_INVALID_REQUEST, 400, "household_size_at_cert must be >= 1")

    from flask import g
    c = new_entity()
    c.update({
        "household_id": h["id"],
        "tax_year": tax_year,
        "reported_annual_income_cents": reported,
        "verified_annual_income_cents": verified,
        "household_size_at_cert": size_at_cert,
        "ami_pct_at_cert": engine.compute_ami_pct(
            verified, program["area_median_income_cents"], size_at_cert),
        "status": "SUBMITTED",
        "rejection_reason": "",
        "reviewed_by": "",
        "submitted_by": g.user_id,
        "decided_at": None,
    })
    db.store.certs[c["id"]] = c
    return jsonify(ok_object(ser_cert(c))), 201


@bp.get("/programs/<pid>/households/<hid>/income-certifications")
@require(STAFF_AND_HOUSEHOLD)
def list_certs(pid, hid):
    h = get_household_or_404(pid, hid)
    require_household_owner(h["id"])
    items = [c for c in db.store.certs.values() if c["household_id"] == hid]
    status = query_str("status")
    if status:
        items = [c for c in items if c["status"] == status]
    return jsonify(paginated(items, ser_cert)), 200


@bp.get("/programs/<pid>/households/<hid>/income-certifications/<cid>")
@require(STAFF_AND_HOUSEHOLD)
def get_cert(pid, hid, cid):
    h = get_household_or_404(pid, hid)
    c = get_cert_or_404(pid, hid, cid)
    require_household_owner(h["id"])
    return jsonify(ok_object(ser_cert(c))), 200


@bp.post("/programs/<pid>/households/<hid>/income-certifications/<cid>/start-review")
@require(["ComplianceOfficer"])
def start_review_cert(pid, hid, cid):
    get_household_or_404(pid, hid)
    c = get_cert_or_404(pid, hid, cid)
    if c["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a SUBMITTED certification can move to UNDER_REVIEW")
    c["status"] = "UNDER_REVIEW"
    bump(c)
    return jsonify(ok_object(ser_cert(c))), 200


@bp.post("/programs/<pid>/households/<hid>/income-certifications/<cid>/approve")
@require(["ComplianceOfficer"])
def approve_cert(pid, hid, cid):
    h = get_household_or_404(pid, hid)
    program = get_program_or_404(pid)
    c = get_cert_or_404(pid, hid, cid)
    if c["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an UNDER_REVIEW certification can be approved")
    from flask import g
    if g.user_id == c["submitted_by"]:
        raise ApiError(ERR_SO_DUTY_VIOLATION, 409,
                       "Reviewer must differ from the certification submitter")
    if c["verified_annual_income_cents"] < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "verified_annual_income_cents must be >= 0")
    now = db.get_now()
    c["status"] = "APPROVED"
    c["decided_at"] = now
    c["reviewed_by"] = g.user_id
    bump(c)
    engine.reevaluate_eligibility_on_approval(program, h, c, now)
    return jsonify(ok_object(ser_cert(c))), 200


@bp.post("/programs/<pid>/households/<hid>/income-certifications/<cid>/reject")
@require(["ComplianceOfficer"])
def reject_cert(pid, hid, cid):
    h = get_household_or_404(pid, hid)
    c = get_cert_or_404(pid, hid, cid)
    if c["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an UNDER_REVIEW certification can be rejected")
    from flask import g
    if g.user_id == c["submitted_by"]:
        raise ApiError(ERR_SO_DUTY_VIOLATION, 409,
                       "Reviewer must differ from the certification submitter")
    data = body()
    reason = req_str(data, "rejection_reason")
    now = db.get_now()
    c["status"] = "REJECTED"
    c["decided_at"] = now
    c["reviewed_by"] = g.user_id
    c["rejection_reason"] = reason
    bump(c)
    other_approved = any(
        o for o in db.store.certs.values()
        if o["household_id"] == h["id"] and o["id"] != c["id"] and o["status"] == "APPROVED"
    )
    if not other_approved and h["eligibility_status"] != "INELIGIBLE":
        if h["eligibility_status"] == "ELIGIBLE":
            h["_eligibility_lost_at"] = now
        h["eligibility_status"] = "INELIGIBLE"
        h["eligibility_expires_at"] = None
        bump(h)
    return jsonify(ok_object(ser_cert(c))), 200


# ---------------------------------------------------------------------------
# EducationCompletions
# ---------------------------------------------------------------------------

@bp.post("/programs/<pid>/households/<hid>/education-completions")
@require(["IntakeSpecialist"])
def create_completion(pid, hid):
    from decimal import Decimal
    from errors import ERR_REFERENCE_NOT_FOUND

    h = get_household_or_404(pid, hid)
    data = body()
    course_id = req_str(data, "course_id")
    completed_at = req_dt(data, "completed_at")
    score = req_num(data, "score_pct")
    if Decimal(str(score)) < Decimal("0.0") or Decimal(str(score)) > Decimal("1.0"):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "score_pct must be within [0.0, 1.0]")
    course = db.store.courses.get(course_id)
    if course is None or course["program_id"] != pid:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, 422,
                       "course_id does not resolve in this program scope")

    from flask import g
    from util import add_months
    c = new_entity(with_version=False)
    c.update({
        "household_id": h["id"],
        "course_id": course["id"],
        "completed_at": completed_at,
        "expires_at": add_months(completed_at, course["validity_months"]),
        "recorded_by": g.user_id,
        "score_pct": score,
    })
    db.store.completions[c["id"]] = c
    engine.refresh_education_completed_at(h, db.get_now())
    return jsonify(ok_object(ser_completion(c))), 201


@bp.get("/programs/<pid>/households/<hid>/education-completions")
@require(STAFF_AND_HOUSEHOLD)
def list_completions(pid, hid):
    h = get_household_or_404(pid, hid)
    require_household_owner(h["id"])
    items = [c for c in db.store.completions.values() if c["household_id"] == hid]
    return jsonify(paginated(items, ser_completion)), 200
