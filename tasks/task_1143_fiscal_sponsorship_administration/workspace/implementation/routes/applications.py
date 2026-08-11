"""ProjectApplication endpoints (PRD §3.1)."""

from flask import Blueprint

from db import new_id, stamp_new, store, touch
from envelope import ok, ok_list, ok_obj
from errors import (
    ERR_APPLICATION_NOT_ACTIONABLE,
    ERR_APPLICATION_NOT_FOUND,
    ERR_MISSION_SCORE_BELOW_THRESHOLD,
    ERR_VALIDATION,
    raise_err,
)
from security import (
    READ_ROLES,
    auth,
    body,
    opt_enum,
    opt_str,
    req_enum,
    req_int,
    req_number,
    req_str,
    require_owner,
    require_role,
)
from services import MISSION_SCORE_THRESHOLD, mission_score
from decimal import Decimal

bp = Blueprint("applications", __name__)

MODELS = ("COMPREHENSIVE", "PRE_APPROVED_GRANT")
DECISIONS = ("APPROVE", "REJECT", "RETURN")
SCORE_ACTIONS = ("ADVANCE", "RETURN")


def get_application(app_id):
    app = store.applications.get(app_id)
    if app is None:
        raise_err(ERR_APPLICATION_NOT_FOUND, "application not found")
    return app


@bp.post("/fsa/applications")
def create_application():
    data = body()
    project_name = req_str(data, "project_name")
    mission_statement = req_str(data, "mission_statement")
    budget = req_int(data, "budget_estimate_cents")
    contact_email = req_str(data, "contact_email")
    requested_model = opt_enum(data, "requested_model", MODELS) or "COMPREHENSIVE"
    if budget < 0:
        raise_err(ERR_VALIDATION, "budget_estimate_cents must be >= 0")
    uid, role = auth()
    require_role(role, {"Applicant"})
    app = stamp_new({
        "id": new_id(),
        "applicant_user_id": uid,
        "project_name": project_name,
        "mission_statement": mission_statement,
        "requested_model": requested_model,
        "budget_estimate_cents": budget,
        "contact_email": contact_email,
        "status": "DRAFT",
        "purpose_pts": None,
        "benefit_pts": None,
        "capacity_pts": None,
        "risk_pts": None,
        "mission_score": None,
        "review_note": None,
        "decided_model": None,
        "submit_count": 0,
        "project_id": None,
        "agreement_id": None,
        "fund_account_id": None,
    })
    store.applications[app["id"]] = app
    return ok_obj(app, 201)


@bp.get("/fsa/applications")
def list_applications():
    uid, role = auth()
    require_role(role, READ_ROLES)
    items = list(store.applications.values())
    status = _q("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    applicant = _q("applicant_user_id")
    if applicant is not None:
        items = [a for a in items if a["applicant_user_id"] == applicant]
    return ok_list(items)


def _q(name):
    from flask import request
    v = request.args.get(name)
    return v if v is not None else None


@bp.get("/fsa/applications/<app_id>")
def get_application_route(app_id):
    uid, role = auth()
    require_role(role, READ_ROLES)
    return ok_obj(get_application(app_id))


@bp.post("/fsa/applications/<app_id>/submit")
def submit_application(app_id):
    uid, role = auth()
    require_role(role, {"Applicant"})
    app = get_application(app_id)
    require_owner(uid, app["applicant_user_id"])
    if app["status"] not in ("DRAFT", "RETURNED"):
        raise_err(ERR_APPLICATION_NOT_ACTIONABLE, "application cannot be submitted from %s" % app["status"])
    app["status"] = "SUBMITTED"
    app["submit_count"] += 1
    touch(app)
    return ok_obj(app)


@bp.post("/fsa/applications/<app_id>/mission-score")
def mission_score_route(app_id):
    data = body()
    purpose = req_number(data, "purpose_pts")
    benefit = req_number(data, "benefit_pts")
    capacity = req_number(data, "capacity_pts")
    risk = req_number(data, "risk_pts")
    action = req_enum(data, "action", SCORE_ACTIONS)
    review_note = opt_str(data, "review_note")
    for name, v in (("purpose_pts", purpose), ("benefit_pts", benefit),
                    ("capacity_pts", capacity), ("risk_pts", risk)):
        if v < 0 or v > 100:
            raise_err(ERR_VALIDATION, "%s must be between 0 and 100" % name)
    uid, role = auth()
    require_role(role, {"ProgramOfficer"})
    app = get_application(app_id)
    if app["status"] != "SUBMITTED":
        raise_err(ERR_APPLICATION_NOT_ACTIONABLE, "application is not SUBMITTED")
    score = mission_score(purpose, benefit, capacity, risk)
    if action == "ADVANCE" and score < MISSION_SCORE_THRESHOLD:
        raise_err(ERR_MISSION_SCORE_BELOW_THRESHOLD, "mission_score below 70.00")
    app["purpose_pts"] = purpose
    app["benefit_pts"] = benefit
    app["capacity_pts"] = capacity
    app["risk_pts"] = risk
    app["mission_score"] = float(score)
    if review_note is not None:
        app["review_note"] = review_note
    app["status"] = "COMPLIANCE_REVIEW" if action == "ADVANCE" else "RETURNED"
    touch(app)
    return ok_obj(app)


@bp.post("/fsa/applications/<app_id>/compliance-decision")
def compliance_decision(app_id):
    data = body()
    decision = req_str(data, "decision")
    sponsorship_model = None
    if decision == "APPROVE":
        # conditionally required (PRD §2.11 pipeline step 1)
        sponsorship_model = req_str(data, "sponsorship_model")
    elif "sponsorship_model" in data and data["sponsorship_model"] is not None:
        if not isinstance(data["sponsorship_model"], str):
            raise_err(ERR_VALIDATION, "sponsorship_model must be a string")
        sponsorship_model = data["sponsorship_model"]
    rationale = opt_str(data, "rationale")
    # enum membership (pipeline step 2)
    from security import check_enum
    check_enum(decision, "decision", DECISIONS)
    if sponsorship_model is not None:
        check_enum(sponsorship_model, "sponsorship_model", MODELS)
    uid, role = auth()
    require_role(role, {"ComplianceOfficer"})
    app = get_application(app_id)
    if app["status"] != "COMPLIANCE_REVIEW":
        raise_err(ERR_APPLICATION_NOT_ACTIONABLE, "application is not in COMPLIANCE_REVIEW")
    if rationale is not None:
        app["review_note"] = rationale
    if decision == "REJECT":
        app["status"] = "REJECTED"
        touch(app)
        return ok_obj(app)
    if decision == "RETURN":
        app["status"] = "RETURNED"
        touch(app)
        return ok_obj(app)
    # APPROVE: atomic cascade minting Project + SponsorshipAgreement + FundAccount
    app["decided_model"] = sponsorship_model
    project = stamp_new({
        "id": new_id(),
        "source_application_id": app["id"],
        "name": app["project_name"],
        "mission_statement": app["mission_statement"],
        "lead_user_id": app["applicant_user_id"],
        "status": "PROPOSED",
        "risk_score": 0,
        "oversight_posture": "NORMAL",
        "suspension_reason": None,
    })
    agreement = stamp_new({
        "id": new_id(),
        "project_id": project["id"],
        "model": sponsorship_model,
        "status": "PENDING_COUNTERSIGN",
        "spending_basis": "SETTLED",
        "amendment_note": None,
        "effective_date": None,
    })
    fund = stamp_new({
        "id": new_id(),
        "project_id": project["id"],
        "status": "PENDING",
        "currency": "USD",
        "total_received_cents": 0,
        "total_refunded_cents": 0,
        "total_fees_charged_cents": 0,
        "total_fees_reversed_cents": 0,
        "total_disbursed_cents": 0,
        "total_adjustments_cents": 0,
        "total_transferred_out_cents": 0,
        "committed_cents": 0,
        "reserved_cents": 0,
    })
    store.projects[project["id"]] = project
    store.agreements[agreement["id"]] = agreement
    store.funds[fund["id"]] = fund
    app["project_id"] = project["id"]
    app["agreement_id"] = agreement["id"]
    app["fund_account_id"] = fund["id"]
    app["status"] = "APPROVED"
    touch(app)
    return ok_obj(app)


@bp.post("/fsa/applications/<app_id>/withdraw")
def withdraw_application(app_id):
    uid, role = auth()
    require_role(role, {"Applicant"})
    app = get_application(app_id)
    require_owner(uid, app["applicant_user_id"])
    if app["status"] not in ("DRAFT", "SUBMITTED", "RETURNED", "COMPLIANCE_REVIEW"):
        raise_err(ERR_APPLICATION_NOT_ACTIONABLE, "application cannot be withdrawn from %s" % app["status"])
    app["status"] = "WITHDRAWN"
    touch(app)
    return ok_obj(app)


@bp.get("/fsa/applications/<app_id>/projects")
def application_projects(app_id):
    uid, role = auth()
    require_role(role, READ_ROLES)
    app = get_application(app_id)
    items = [p for p in store.projects.values() if p["source_application_id"] == app["id"]]
    return ok_list(items)
