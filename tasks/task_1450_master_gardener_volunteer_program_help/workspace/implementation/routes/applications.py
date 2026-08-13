"""Application endpoints: submit, list, get, score, decide."""

from flask import request, Blueprint

import db
import util
from middleware import auth_context
from errors import raise_err
from response import success_object, success_list
from services import calculations as calc
from routes.program_cycles import _accept_application

bp = Blueprint("applications", __name__)

ALL_ROLES = ["ProgramCoordinator", "Volunteer", "Specialist"]
PC = ["ProgramCoordinator"]


def _get_app_or_404(app_id):
    app = db.applications.get(app_id)
    if app is None:
        raise_err("ERR_NOT_FOUND", "Application not found")
    return app


@bp.route("/applications", methods=["POST"])
def create_application():
    auth_context(PC)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    for f in ("cycle_id", "applicant_name", "email", "county"):
        if f not in body:
            raise_err("ERR_INVALID_REQUEST", f"Missing required field: {f}")
        if not isinstance(body[f], str) or not body[f]:
            raise_err("ERR_INVALID_REQUEST", f"{f} must be a non-empty string")
    if "prior_gardening_years" not in body:
        raise_err("ERR_INVALID_REQUEST", "Missing required field: prior_gardening_years")
    if not isinstance(body["prior_gardening_years"], int) or isinstance(body["prior_gardening_years"], bool):
        raise_err("ERR_INVALID_REQUEST", "prior_gardening_years must be an integer")
    if body["prior_gardening_years"] < 0:
        raise_err("ERR_INVALID_FIELD_VALUE", "prior_gardening_years must be >= 0")

    cycle = db.program_cycles.get(body["cycle_id"])
    if cycle is None:
        raise_err("ERR_NOT_FOUND", "cycle_id does not resolve to an existing ProgramCycle")
    if cycle["status"] not in ("DRAFT", "OPEN"):
        raise_err("ERR_CYCLE_NOT_ACCEPTING_APPLICATIONS", "Cycle is not accepting applications")

    app = util.new_resource({
        "cycle_id": body["cycle_id"],
        "applicant_name": body["applicant_name"],
        "email": body["email"],
        "county": body["county"],
        "prior_gardening_years": body["prior_gardening_years"],
        "essay_score": None,
        "interview_score": None,
        "composite_score": None,
        "status": "SUBMITTED",
        "decided_at": None,
    })
    db.applications[app["id"]] = app
    return success_object(app, 201)


@bp.route("/applications", methods=["GET"])
def list_applications():
    auth_context(ALL_ROLES)
    items = list(db.applications.values())
    cycle_id = request.args.get("cycle_id")
    status = request.args.get("status")
    if cycle_id is not None:
        items = [a for a in items if a["cycle_id"] == cycle_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items = util.sort_created(items)
    limit, offset = util.paginate(items, request.args)
    return success_list(items[offset:offset + limit], len(items), limit, offset)


@bp.route("/applications/<applicationId>", methods=["GET"])
def get_application(applicationId):
    auth_context(ALL_ROLES)
    return success_object(_get_app_or_404(applicationId))


@bp.route("/applications/<applicationId>/score", methods=["POST"])
def score_application(applicationId):
    auth_context(PC)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    for f in ("essay_score", "interview_score"):
        if f not in body:
            raise_err("ERR_INVALID_REQUEST", f"Missing required field: {f}")
        v = body[f]
        if not isinstance(v, int) or isinstance(v, bool):
            raise_err("ERR_INVALID_REQUEST", f"{f} must be an integer")
        if v < 0 or v > 100:
            raise_err("ERR_INVALID_FIELD_VALUE", f"{f} must be 0..100")

    app = _get_app_or_404(applicationId)
    cycle = db.program_cycles.get(app["cycle_id"])
    if cycle is None:
        raise_err("ERR_NOT_FOUND", "Application's cycle not found")
    # posture (priority 7) precedes target state (priority 8)
    if cycle["status"] not in ("DRAFT", "OPEN"):
        raise_err("ERR_CYCLE_NOT_ACCEPTING_APPLICATIONS", "Cycle is not accepting application scoring")
    if app["status"] != "SUBMITTED":
        raise_err("ERR_APPLICATION_NOT_SUBMITTED", "Application must be SUBMITTED to score")

    app["essay_score"] = body["essay_score"]
    app["interview_score"] = body["interview_score"]
    app["composite_score"] = calc.composite_score(app, cycle)
    app["status"] = "SCORED"
    util.touch(app)
    return success_object(app)


@bp.route("/applications/<applicationId>/decide", methods=["POST"])
def decide_application(applicationId):
    auth_context(PC)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    if "decision" not in body:
        raise_err("ERR_INVALID_REQUEST", "Missing required field: decision")
    decision = body["decision"]
    if decision not in ("ACCEPT", "WAITLIST", "REJECT"):
        raise_err("ERR_INVALID_REQUEST", "decision must be ACCEPT, WAITLIST, or REJECT")

    app = _get_app_or_404(applicationId)
    cycle = db.program_cycles.get(app["cycle_id"])
    if cycle is None:
        raise_err("ERR_NOT_FOUND", "Application's cycle not found")
    # posture (priority 7) precedes target state (priority 8)
    if cycle["status"] not in ("DRAFT", "OPEN"):
        raise_err("ERR_CYCLE_NOT_ACCEPTING_APPLICATIONS", "Cycle is not accepting application decisions")
    valid_from = {"ACCEPT": ("SCORED", "WAITLISTED"),
                  "WAITLIST": ("SCORED",),
                  "REJECT": ("SCORED", "WAITLISTED")}
    if app["status"] not in valid_from[decision]:
        raise_err("ERR_APPLICATION_NOT_SCORED", "Application is not in a decidable state")

    if decision == "ACCEPT":
        if cycle["accepted_count"] >= cycle["admission_capacity"]:
            raise_err("ERR_NO_SEATS_AVAILABLE", "No seats available in this cycle")
        _accept_application(app, cycle)
    elif decision == "WAITLIST":
        app["status"] = "WAITLISTED"
        app["decided_at"] = util.logical_clock_iso()
        util.touch(app)
    else:  # REJECT
        app["status"] = "REJECTED"
        app["decided_at"] = util.logical_clock_iso()
        util.touch(app)
    return success_object(app)
