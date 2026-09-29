"""Employer partners, worksites, safety reviews and supervisors (PRD 3.1, 3.2)."""

import re

from flask import Blueprint

import derive
from auth import require
from db import add_days, apply_changes, by_created, by_created_desc, db, new_record, today_str, touch
from errors import fail
from response import created, listing, ok
from validation import (f_bool, f_date, f_enum, f_int, f_str, get_body, pagination,
                        paginate, q_enum)

bp = Blueprint("partners", __name__)

INDUSTRY_SECTORS = ("MANUFACTURING", "HEALTHCARE", "CONSTRUCTION",
                    "INFORMATION_TECHNOLOGY", "HOSPITALITY", "PUBLIC_ADMINISTRATION")
POSTURES = ("PROSPECT", "ELIGIBLE", "PROBATION", "SUSPENDED")
HAZARD_CLASSES = ("NON_HAZARDOUS", "LIMITED_HAZARD", "PROHIBITED_HAZARD")
DECISIONS = ("APPROVED", "CONDITIONAL", "FAILED")

NAICS_RE = re.compile(r"^\d{6}$")


# --------------------------------------------------------------------------
# employer partners
# --------------------------------------------------------------------------

@bp.post("/employer-partners")
def create_partner():
    require("WblCoordinator")
    body = get_body()
    legal_name = f_str(body, "legal_name")
    naics_code = f_str(body, "naics_code")
    if not NAICS_RE.match(naics_code):
        fail("ERR_INVALID_REQUEST", "Field 'naics_code' must be exactly six digits.")
    industry_sector = f_enum(body, "industry_sector", INDUSTRY_SECTORS)
    carrier = f_str(body, "workers_comp_carrier")
    policy_no = f_str(body, "workers_comp_policy_no")
    expires_on = f_date(body, "workers_comp_expires_on")

    partner = new_record()
    partner.update({
        "legal_name": legal_name,
        "naics_code": naics_code,
        "industry_sector": industry_sector,
        "workers_comp_carrier": carrier,
        "workers_comp_policy_no": policy_no,
        "workers_comp_expires_on": expires_on,
        "safety_score": 100,
        "posture": "PROSPECT",
        "substantiated_minor_count": 0,
        "substantiated_moderate_count": 0,
        "substantiated_critical_count": 0,
        "wage_liability_cents": 0,
    })
    db.employer_partners[partner["id"]] = partner
    return created(partner)


@bp.get("/employer-partners/<employerId>")
def read_partner(employerId):
    require("WblCoordinator", "SafetyReviewer", "ComplianceOfficer")
    return ok(derive.get_partner(employerId))


@bp.get("/employer-partners")
def list_partners():
    require("WblCoordinator", "SafetyReviewer", "ComplianceOfficer")
    limit, offset = pagination()
    posture = q_enum("posture", POSTURES)
    rows = by_created([p for p in db.employer_partners.values()
                       if posture is None or p["posture"] == posture])
    page, total = paginate(rows, limit, offset)
    return listing(page, total, limit, offset)


@bp.patch("/employer-partners/<employerId>/insurance")
def update_partner_insurance(employerId):
    require("WblCoordinator")
    partner = derive.get_partner(employerId)
    body = get_body()
    carrier = f_str(body, "workers_comp_carrier")
    policy_no = f_str(body, "workers_comp_policy_no")
    expires_on = f_date(body, "workers_comp_expires_on")
    apply_changes(partner, workers_comp_carrier=carrier,
                  workers_comp_policy_no=policy_no,
                  workers_comp_expires_on=expires_on)
    touch(partner)
    return ok(partner)


# --------------------------------------------------------------------------
# worksites
# --------------------------------------------------------------------------

@bp.post("/worksites")
def create_worksite():
    require("WblCoordinator")
    body = get_body()
    partner = derive.get_partner(f_str(body, "employer_partner_id"))
    site_name = f_str(body, "site_name")
    address_line = f_str(body, "address_line")
    hazard_class = f_enum(body, "hazard_class", HAZARD_CLASSES)
    has_power_machinery = f_bool(body, "has_power_machinery", required=False, default=False)
    displaces = f_bool(body, "displaces_paid_employee", required=False, default=False)
    max_concurrent = f_int(body, "max_concurrent_students", minimum=1)

    worksite = new_record()
    worksite.update({
        "employer_partner_id": partner["id"],
        "site_name": site_name,
        "address_line": address_line,
        "hazard_class": hazard_class,
        "has_power_machinery": has_power_machinery,
        "displaces_paid_employee": displaces,
        "max_concurrent_students": max_concurrent,
        "safety_status": "UNREVIEWED",
        "safety_review_expires_on": None,
        "corrective_actions_due_on": None,
        "slots_committed": 0,
    })
    db.worksites[worksite["id"]] = worksite
    return created(worksite)


@bp.get("/worksites/<worksiteId>")
def read_worksite(worksiteId):
    require("WblCoordinator", "SafetyReviewer", "ComplianceOfficer", "EmployerSupervisor")
    return ok(derive.get_worksite(worksiteId))


@bp.get("/employer-partners/<id>/worksites")
def list_partner_worksites(id):
    require("WblCoordinator", "SafetyReviewer", "ComplianceOfficer")
    partner = derive.get_partner(id)
    limit, offset = pagination()
    rows = by_created([w for w in db.worksites.values()
                       if w["employer_partner_id"] == partner["id"]])
    page, total = paginate(rows, limit, offset)
    return listing(page, total, limit, offset)


# --------------------------------------------------------------------------
# safety reviews
# --------------------------------------------------------------------------

@bp.post("/safety-reviews")
def file_safety_review():
    user_id, _role = require("SafetyReviewer")
    body = get_body()
    worksite = derive.get_worksite(f_str(body, "worksite_id"))
    machinery_guarding_ok = f_bool(body, "machinery_guarding_ok")
    hazard_findings_count = f_int(body, "hazard_findings_count", minimum=0)
    orientation_documented = f_bool(body, "orientation_documented")
    emergency_plan_on_file = f_bool(body, "emergency_plan_on_file")
    expected_version = f_int(body, "expected_worksite_version")

    if expected_version != worksite["version"]:
        fail("ERR_STALE_WORKSITE_VERSION",
             "expected_worksite_version does not match the worksite's current version.")

    # Filing supersedes any prior decided review on the same worksite.
    for prior in by_created([r for r in db.safety_reviews.values()
                             if r["worksite_id"] == worksite["id"]]):
        if prior["status"] in ("APPROVED", "CONDITIONAL"):
            prior["status"] = "SUPERSEDED"
            touch(prior)

    review = new_record()
    review.update({
        "worksite_id": worksite["id"],
        "reviewer_user_id": user_id,
        "machinery_guarding_ok": machinery_guarding_ok,
        "hazard_findings_count": hazard_findings_count,
        "orientation_documented": orientation_documented,
        "emergency_plan_on_file": emergency_plan_on_file,
        "status": "SUBMITTED",
        "decision_on": None,
        "corrective_actions_due_on": None,
        "expires_on": None,
    })
    db.safety_reviews[review["id"]] = review

    apply_changes(worksite, safety_status="UNREVIEWED",
                  safety_review_expires_on=None,
                  corrective_actions_due_on=None)
    touch(worksite)
    return created(review)


@bp.post("/safety-reviews/<reviewId>/decision")
def decide_safety_review(reviewId):
    require("SafetyReviewer")
    review = derive.get_review(reviewId)
    body = get_body()
    decision = f_enum(body, "decision", DECISIONS)

    if review["status"] != "SUBMITTED":
        fail("ERR_REVIEW_ALREADY_DECIDED",
             "A decision has already been recorded on this safety review.")

    guarding = review["machinery_guarding_ok"]
    findings = review["hazard_findings_count"]

    fails = (guarding is not True or findings >= 4
             or review["emergency_plan_on_file"] is not True)
    approvable = (guarding is True and findings == 0
                  and review["orientation_documented"] is True
                  and review["emergency_plan_on_file"] is True)
    conditionable = guarding is True and 1 <= findings <= 3

    worksite = derive.get_worksite(review["worksite_id"])
    decision_on = today_str()

    if decision == "APPROVED":
        if not approvable:
            fail("ERR_INVALID_REQUEST",
                 "The recorded inspection findings do not support an APPROVED decision.")
        review["status"] = "APPROVED"
        review["decision_on"] = decision_on
        review["expires_on"] = add_days(decision_on, 365)
        review["corrective_actions_due_on"] = None
        touch(review)
        apply_changes(worksite, safety_status="APPROVED",
                      safety_review_expires_on=review["expires_on"],
                      corrective_actions_due_on=None)
        touch(worksite)
    elif decision == "CONDITIONAL":
        if not conditionable:
            fail("ERR_INVALID_REQUEST",
                 "The recorded inspection findings do not support a CONDITIONAL decision.")
        review["status"] = "CONDITIONAL"
        review["decision_on"] = decision_on
        review["corrective_actions_due_on"] = add_days(decision_on, 30)
        review["expires_on"] = add_days(decision_on, 365)
        touch(review)
        apply_changes(worksite, safety_status="CONDITIONAL",
                      safety_review_expires_on=review["expires_on"],
                      corrective_actions_due_on=review["corrective_actions_due_on"])
        touch(worksite)
    else:
        if not fails:
            fail("ERR_INVALID_REQUEST",
                 "The recorded inspection findings do not support a FAILED decision.")
        review["status"] = "FAILED"
        review["decision_on"] = decision_on
        review["expires_on"] = None
        review["corrective_actions_due_on"] = None
        touch(review)
        apply_changes(worksite, safety_status="FAILED",
                      safety_review_expires_on=None)
        touch(worksite)

    partner = derive.partner_of_worksite(worksite)
    if partner is not None:
        derive.recompute_partner_safety(partner)

    if decision == "FAILED":
        derive.block_placements_of_worksite(worksite["id"])

    return ok(review)


@bp.get("/worksites/<id>/safety-reviews")
def list_worksite_reviews(id):
    require("WblCoordinator", "SafetyReviewer", "ComplianceOfficer")
    worksite = derive.get_worksite(id)
    limit, offset = pagination()
    rows = by_created_desc([r for r in db.safety_reviews.values()
                            if r["worksite_id"] == worksite["id"]])
    page, total = paginate(rows, limit, offset)
    return listing(page, total, limit, offset)


# --------------------------------------------------------------------------
# supervisors
# --------------------------------------------------------------------------

@bp.post("/supervisors")
def create_supervisor():
    require("WblCoordinator")
    body = get_body()
    worksite = derive.get_worksite(f_str(body, "worksite_id"))
    full_name = f_str(body, "full_name")
    email = f_str(body, "email")
    training_completed_on = f_date(body, "training_completed_on")
    max_student_load = f_int(body, "max_student_load", minimum=1)

    supervisor = new_record()
    supervisor.update({
        "worksite_id": worksite["id"],
        "full_name": full_name,
        "email": email,
        "training_completed_on": training_completed_on,
        "max_student_load": max_student_load,
        "active_student_load": 0,
    })
    db.supervisors[supervisor["id"]] = supervisor
    return created(supervisor)


@bp.get("/worksites/<id>/supervisors")
def list_worksite_supervisors(id):
    require("WblCoordinator", "ComplianceOfficer", "EmployerSupervisor")
    worksite = derive.get_worksite(id)
    limit, offset = pagination()
    rows = by_created([s for s in db.supervisors.values()
                       if s["worksite_id"] == worksite["id"]])
    page, total = paginate(rows, limit, offset)
    return listing(page, total, limit, offset)
