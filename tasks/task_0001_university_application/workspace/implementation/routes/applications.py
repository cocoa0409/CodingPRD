"""Application endpoints (CRUD + workflow actions)."""
from __future__ import annotations

from flask import Blueprint, request, g

import db
from errors import (
    APIError, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_FORBIDDEN_OWNER_MISMATCH,
)
from middleware import auth_required
from response import ok_object, ok_array
from routes._helpers import (
    parse_pagination, paginate, get_body, require_fields, order_by_created_at,
)
from services import state_machines
from services.common import new_common_fields

bp = Blueprint("applications", __name__)


def _ownership(app):
    if g.user_role == "Applicant" and g.user_id != app["applicant_id"]:
        raise APIError(ERR_FORBIDDEN_OWNER_MISMATCH, 403, "Caller does not own this application")


@bp.post("/applications")
def create_application():
    auth_required({"Applicant"})()
    body = get_body()
    require_fields(body, ["applicant_id", "school_id"])
    applicant_id = body["applicant_id"]
    school_id = body["school_id"]
    # ownership before existence per priority? Validation priority puts existence (3)
    # before owner-mismatch (4). So check existence first.
    if applicant_id not in db.applicants:
        raise APIError(ERR_NOT_FOUND, 404, "Applicant not found")
    if school_id not in db.schools:
        raise APIError(ERR_NOT_FOUND, 404, "School not found")
    # owner check
    if g.user_id != applicant_id:
        raise APIError(ERR_FORBIDDEN_OWNER_MISMATCH, 403, "Caller does not own this applicant")

    common = new_common_fields()
    app = {
        **common,
        "applicant_id": applicant_id,
        "school_id": school_id,
        "status": "DRAFT",
        "admission_track_snapshot": None,
        "submitted_at": None,
        "decision_at": None,
        "enrollment_decision_at": None,
        "composite_score": None,
    }
    db.applications[app["id"]] = app
    return ok_object(app, http_status=201)


@bp.get("/applications/<aid>")
def read_application(aid):
    auth_required({"Applicant", "AdmissionsOfficer", "PlatformAdmin"})()
    app = db.applications.get(aid)
    if app is None:
        raise APIError(ERR_NOT_FOUND, 404, "Application not found")
    # Applicants can only read their own applications
    if g.user_role == "Applicant" and g.user_id != app["applicant_id"]:
        raise APIError(ERR_FORBIDDEN_OWNER_MISMATCH, 403, "Caller does not own this application")
    return ok_object(app)


@bp.get("/applications")
def list_applications():
    auth_required({"Applicant", "AdmissionsOfficer", "FinancialAidOfficer", "PlatformAdmin"})()
    applicant_id = request.args.get("applicant_id")
    school_id = request.args.get("school_id")
    status_f = request.args.get("status")
    limit, offset = parse_pagination()
    items = []
    for a in db.applications.values():
        if applicant_id and a["applicant_id"] != applicant_id:
            continue
        if school_id and a["school_id"] != school_id:
            continue
        if status_f and a["status"] != status_f:
            continue
        # Applicants can only see their own apps
        if g.user_role == "Applicant" and a["applicant_id"] != g.user_id:
            continue
        items.append(a)
    items = order_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return ok_array(page, limit, offset, total)


@bp.post("/applications/<aid>/submit")
def submit(aid):
    auth_required({"Applicant"})()
    app = db.applications.get(aid)
    if app is None:
        raise APIError(ERR_NOT_FOUND, 404, "Application not found")
    _ownership(app)
    state_machines.submit_application(app, g.user_id)
    return ok_object(app)


@bp.post("/applications/<aid>/withdraw")
def withdraw(aid):
    auth_required({"Applicant"})()
    app = db.applications.get(aid)
    if app is None:
        raise APIError(ERR_NOT_FOUND, 404, "Application not found")
    _ownership(app)
    state_machines.withdraw_application(app)
    return ok_object(app)


@bp.post("/applications/<aid>/begin-review")
def begin_review(aid):
    auth_required({"AdmissionsOfficer"})()
    app = db.applications.get(aid)
    if app is None:
        raise APIError(ERR_NOT_FOUND, 404, "Application not found")
    state_machines.begin_review(app)
    return ok_object(app)


@bp.post("/applications/<aid>/admit")
def admit(aid):
    auth_required({"AdmissionsOfficer"})()
    app = db.applications.get(aid)
    if app is None:
        raise APIError(ERR_NOT_FOUND, 404, "Application not found")
    body = get_body()
    # state precondition checked inside admit_application BEFORE OCC (per priority)
    expected_version = body.get("expected_application_version")
    state_machines.admit_application(app, expected_version)
    return ok_object(app)


@bp.post("/applications/<aid>/waitlist")
def waitlist(aid):
    auth_required({"AdmissionsOfficer"})()
    app = db.applications.get(aid)
    if app is None:
        raise APIError(ERR_NOT_FOUND, 404, "Application not found")
    state_machines.waitlist_application(app)
    return ok_object(app)


@bp.post("/applications/<aid>/deny")
def deny(aid):
    auth_required({"AdmissionsOfficer"})()
    app = db.applications.get(aid)
    if app is None:
        raise APIError(ERR_NOT_FOUND, 404, "Application not found")
    state_machines.deny_application(app)
    return ok_object(app)


@bp.post("/applications/<aid>/enroll")
def enroll(aid):
    auth_required({"Applicant"})()
    app = db.applications.get(aid)
    if app is None:
        raise APIError(ERR_NOT_FOUND, 404, "Application not found")
    _ownership(app)
    state_machines.enroll_application(app)
    return ok_object(app)


@bp.post("/applications/<aid>/decline")
def decline(aid):
    auth_required({"Applicant"})()
    app = db.applications.get(aid)
    if app is None:
        raise APIError(ERR_NOT_FOUND, 404, "Application not found")
    _ownership(app)
    state_machines.decline_application(app)
    return ok_object(app)
