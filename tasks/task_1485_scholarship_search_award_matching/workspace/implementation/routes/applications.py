"""Applications, ApplicationComponents, Reminders (PRD §3.3)."""

from flask import Blueprint, g, request

import clock
import db
from errors import raise_err
from middleware import require_roles, body
from response import success, paginate, sort_default
from services import engine, calc
from services.validate import require_fields, req_enum, opt_bool
from routes.programs import get_program_or_404, COMPONENT_TYPES

bp = Blueprint("applications", __name__)

NONTERMINAL_STATUSES = {"DRAFT", "SUBMITTED", "UNDER_REVIEW", "SELECTED", "WAITLISTED", "AWARDED"}
APP_READ_ROLES = ("ScholarshipCoordinator", "Student", "CommitteeReviewer", "FinancialAidOfficer")


def get_application_or_404(aid):
    app = db.get("applications", aid)
    if app is None:
        raise_err("ERR_NOT_FOUND", "Application not found")
    return app


def application_ownership(app):
    if g.role == "Student" and g.user_id != app["student_id"]:
        raise_err("ERR_FORBIDDEN_OWNERSHIP", "Student may only access own applications")


def get_component_or_404(cid):
    c = db.get("components", cid)
    if c is None:
        raise_err("ERR_NOT_FOUND", "ApplicationComponent not found")
    return c


def _component_ownership(component):
    if g.role == "Student":
        app = db.get("applications", component["application_id"])
        if app is None or g.user_id != app["student_id"]:
            raise_err("ERR_FORBIDDEN_OWNERSHIP", "Student may only access own components")


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

@bp.route("/api/applications", methods=["POST"])
@require_roles("ScholarshipCoordinator", "Student")
def create_application():
    data = body()
    require_fields(data, ["student_id", "program_id"])
    student_id = data["student_id"]
    program_id = data["program_id"]
    if not isinstance(student_id, str) or db.get("students", student_id) is None:
        raise_err("ERR_NOT_FOUND", "Student not found")
    if not isinstance(program_id, str) or db.get("programs", program_id) is None:
        raise_err("ERR_NOT_FOUND", "ScholarshipProgram not found")
    if g.role == "Student" and g.user_id != student_id:
        raise_err("ERR_FORBIDDEN_OWNERSHIP", "Student may only apply for themselves")

    student = db.get("students", student_id)
    program = db.get("programs", program_id)
    if student["status"] != "ACTIVE":
        raise_err("ERR_INVALID_STATE", "Student is not ACTIVE")
    if program["status"] != "OPEN":
        raise_err("ERR_PROGRAM_NOT_OPEN", "Program is not OPEN")
    for other in db.all_records("applications"):
        if (other["student_id"] == student_id and other["program_id"] == program_id
                and other["status"] in NONTERMINAL_STATUSES):
            raise_err("ERR_DUPLICATE_APPLICATION",
                      "A non-terminal application already exists for this student and program")

    provisional = calc.eligibility_match_score(student, program, student["gpa_hundredths"])
    rec = db.create_record("applications", {
        "student_id": student_id,
        "program_id": program_id,
        "status": "DRAFT",
        "provisional_match_score": float(provisional),
        "verified_match_score": None,
        "submitted_at": None,
        "returned_count": 0,
        "cycle_score": None,
        "decision_rank": None,
        "_cycle_id": None,
    })
    engine.schedule_reminders(rec, program)
    return success(db.serialize(rec), code=201)


@bp.route("/api/applications", methods=["GET"])
@require_roles(*APP_READ_ROLES)
def list_applications():
    items = db.all_records("applications")
    if g.role == "Student":
        items = [a for a in items if a["student_id"] == g.user_id]
    student_id = request.args.get("student_id")
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    if student_id is not None:
        items = [a for a in items if a["student_id"] == student_id]
    if program_id is not None:
        items = [a for a in items if a["program_id"] == program_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items = sort_default(items)
    page, meta = paginate(items)
    return success([db.serialize(a) for a in page], response_type="array", pagination=meta)


@bp.route("/api/applications/<aid>", methods=["GET"])
@require_roles(*APP_READ_ROLES)
def get_application(aid):
    app = get_application_or_404(aid)
    application_ownership(app)
    return success(db.serialize(app))


@bp.route("/api/applications/<aid>/submit", methods=["POST"])
@require_roles("ScholarshipCoordinator", "Student")
def submit_application(aid):
    app = get_application_or_404(aid)
    application_ownership(app)
    if app["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE", "Only a DRAFT application can be submitted")
    program = get_program_or_404(app["program_id"])
    if program["status"] != "OPEN":
        raise_err("ERR_PROGRAM_NOT_OPEN", "Program is not OPEN")
    # Business constraints (priority 10) mask the temporal deadline gate (priority 11).
    required_types = set(program.get("required_components") or [])
    for c in db.all_records("components"):
        if (c["application_id"] == aid and c["required"] and c["component_type"] in required_types
                and c["status"] not in ("ACCEPTED", "WAIVED")):
            raise_err("ERR_COMPONENT_INCOMPLETE",
                      "A required component is not ACCEPTED or WAIVED")
    student = db.get("students", app["student_id"])
    gpa_input = student["verified_gpa_hundredths"] if student.get("verified_gpa_hundredths") is not None \
        else student["gpa_hundredths"]
    verified = calc.eligibility_match_score(student, program, gpa_input)
    if program["match_policy"] == "STRICT" and verified <= 0:
        raise_err("ERR_INELIGIBLE_STUDENT", "STRICT program: a hard criterion failed")
    if clock.now() >= clock.parse_iso(program["application_close_at"]):
        raise_err("ERR_DEADLINE_PASSED", "The application deadline has passed")
    db.mutate(app, status="SUBMITTED", verified_match_score=float(verified),
              submitted_at=clock.now_iso())
    engine.suppress_reminders(aid)
    return success(db.serialize(app))


@bp.route("/api/applications/<aid>/return", methods=["POST"])
@require_roles("ScholarshipCoordinator")
def return_application(aid):
    app = get_application_or_404(aid)
    if app["status"] != "SUBMITTED":
        raise_err("ERR_INVALID_STATE", "Only a SUBMITTED application can be returned")
    db.mutate(app, status="DRAFT", returned_count=app["returned_count"] + 1)
    program = get_program_or_404(app["program_id"])
    engine.schedule_reminders(app, program)
    return success(db.serialize(app))


@bp.route("/api/applications/<aid>/withdraw", methods=["POST"])
@require_roles("ScholarshipCoordinator", "Student")
def withdraw_application(aid):
    app = get_application_or_404(aid)
    application_ownership(app)
    if app["status"] not in ("DRAFT", "SUBMITTED"):
        raise_err("ERR_INVALID_STATE", "Only a DRAFT or SUBMITTED application can be withdrawn")
    db.mutate(app, status="WITHDRAWN")
    engine.suppress_reminders(aid)
    return success(db.serialize(app))


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------

@bp.route("/api/applications/<aid>/components", methods=["POST"])
@require_roles("ScholarshipCoordinator", "Student")
def create_component(aid):
    app = get_application_or_404(aid)
    application_ownership(app)
    data = body()
    require_fields(data, ["component_type"])
    ctype = req_enum(data, "component_type", COMPONENT_TYPES)
    required = opt_bool(data, "required", True)
    content_ref = data.get("content_ref")
    if content_ref is not None and not isinstance(content_ref, str):
        raise_err("ERR_VALIDATION", "content_ref must be a string")
    if app["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE", "Components may be added only while the application is DRAFT")
    rec = db.create_record("components", {
        "application_id": aid,
        "component_type": ctype,
        "required": required,
        "status": "PENDING",
        "content_ref": content_ref,
        "received_at": None,
    })
    return success(db.serialize(rec), code=201)


@bp.route("/api/applications/<aid>/components", methods=["GET"])
@require_roles("ScholarshipCoordinator", "Student")
def list_components(aid):
    app = get_application_or_404(aid)
    application_ownership(app)
    items = [c for c in db.all_records("components") if c["application_id"] == aid]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = sort_default(items)
    page, meta = paginate(items)
    return success([db.serialize(c) for c in page], response_type="array", pagination=meta)


@bp.route("/api/components/<cid>", methods=["GET"])
@require_roles("ScholarshipCoordinator", "Student")
def get_component(cid):
    component = get_component_or_404(cid)
    _component_ownership(component)
    return success(db.serialize(component))


@bp.route("/api/components/<cid>/receive", methods=["POST"])
@require_roles("ScholarshipCoordinator", "Student")
def receive_component(cid):
    component = get_component_or_404(cid)
    _component_ownership(component)
    data = body()
    content_ref = data.get("content_ref")
    if not isinstance(content_ref, str) or not content_ref:
        raise_err("ERR_VALIDATION", "content_ref is required")
    if component["status"] not in ("PENDING", "REJECTED"):
        raise_err("ERR_INVALID_STATE", "Only a PENDING or REJECTED component can be received")
    db.mutate(component, status="RECEIVED", content_ref=content_ref,
              received_at=clock.now_iso())
    return success(db.serialize(component))


@bp.route("/api/components/<cid>/accept", methods=["POST"])
@require_roles("ScholarshipCoordinator")
def accept_component(cid):
    component = get_component_or_404(cid)
    if component["status"] != "RECEIVED":
        raise_err("ERR_INVALID_STATE", "Only a RECEIVED component can be accepted")
    db.mutate(component, status="ACCEPTED")
    return success(db.serialize(component))


@bp.route("/api/components/<cid>/reject", methods=["POST"])
@require_roles("ScholarshipCoordinator")
def reject_component(cid):
    component = get_component_or_404(cid)
    if component["status"] != "RECEIVED":
        raise_err("ERR_INVALID_STATE", "Only a RECEIVED component can be rejected")
    db.mutate(component, status="REJECTED")
    return success(db.serialize(component))


@bp.route("/api/components/<cid>/waive", methods=["POST"])
@require_roles("ScholarshipCoordinator")
def waive_component(cid):
    component = get_component_or_404(cid)
    if component["status"] != "PENDING":
        raise_err("ERR_INVALID_STATE", "Only a PENDING component can be waived")
    db.mutate(component, status="WAIVED")
    return success(db.serialize(component))


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------

@bp.route("/api/applications/<aid>/reminders", methods=["GET"])
@require_roles("ScholarshipCoordinator", "Student", "PlatformAdmin")
def list_reminders(aid):
    app = get_application_or_404(aid)
    application_ownership(app)
    items = [r for r in db.all_records("reminders") if r["application_id"] == aid]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = sort_default(items)
    page, meta = paginate(items)
    return success([db.serialize(r) for r in page], response_type="array", pagination=meta)
