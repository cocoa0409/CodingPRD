"""ExemptionRequest endpoints (PRD §3.4)."""

from flask import request

import db
from db import stamp_new, touch
from errors import (
    ApiError,
    ERR_EXEMPTION_NOT_FOUND,
    ERR_EXEMPTION_NOT_RESUBMITTABLE,
    ERR_EXEMPTION_NOT_REVIEWABLE,
    ERR_OUTBREAK_ACTIVE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STUDENT_NOT_ACTIVE,
    ERR_STUDENT_NOT_FOUND,
)
from middleware import require_roles
from response import success_object, success_list
from services.evaluation import VACCINE_CODES, exemption_view, reevaluate_student
from services.validate import (
    parse_pagination, paginate, req_enum, req_string, require_body,
)

ALL_ROLES = ("HealthClerk", "SchoolNurse", "DistrictHealthOfficer", "RegistryCoordinator")
EXEMPTION_TYPES = ("MEDICAL", "RELIGIOUS")


def _active_outbreak_for(school_code, vaccine_code):
    for ev in db.outbreak_events.values():
        if ev["status"] == "ACTIVE" and ev["school_code"] == school_code \
                and ev["vaccine_code"] == vaccine_code:
            return ev
    return None


def register(app):

    @app.post("/api/students/<sid>/exemption-requests")
    def submit_exemption(sid):
        user_id, _ = require_roles("SchoolNurse", "DistrictHealthOfficer")
        student = db.students.get(sid)
        if student is None:
            raise ApiError(ERR_STUDENT_NOT_FOUND, "Student not found.", 404)
        if student["status"] == "WITHDRAWN":
            raise ApiError(
                ERR_STUDENT_NOT_ACTIVE,
                "Operation targets a Student with status WITHDRAWN.",
                409,
            )
        body = require_body(request.get_json(silent=True))
        vaccine_code = req_enum(body, "vaccine_code", VACCINE_CODES)
        exemption_type = req_enum(body, "exemption_type", EXEMPTION_TYPES)
        document_ref = req_string(body, "document_ref")

        ex = {
            "student_id": student["id"],
            "vaccine_code": vaccine_code,
            "exemption_type": exemption_type,
            "document_ref": document_ref,
            "status": "SUBMITTED",
            "submitted_by_user_id": user_id,
            "reviewed_by_user_id": None,
            "denial_reason": None,
        }
        stamp_new(ex)
        db.exemption_requests[ex["id"]] = ex
        return success_object(exemption_view(ex), status=201)

    @app.get("/api/students/<sid>/exemption-requests")
    def list_exemptions(sid):
        require_roles(*ALL_ROLES)
        student = db.students.get(sid)
        if student is None:
            raise ApiError(ERR_STUDENT_NOT_FOUND, "Student not found.", 404)
        limit, offset = parse_pagination(request.args)
        status = request.args.get("status")
        items = [e for e in db.exemption_requests.values() if e["student_id"] == sid]
        if status is not None:
            items = [e for e in items if e["status"] == status]
        items.sort(key=lambda e: (e["created_at"], e["id"]))
        page, total = paginate(items, limit, offset)
        return success_list([exemption_view(e) for e in page], limit, offset, total)

    @app.post("/api/exemption-requests/<eid>/start-review")
    def start_review(eid):
        user_id, _ = require_roles("DistrictHealthOfficer")
        ex = db.exemption_requests.get(eid)
        if ex is None:
            raise ApiError(ERR_EXEMPTION_NOT_FOUND, "Exemption request not found.", 404)
        if ex["status"] != "SUBMITTED":
            raise ApiError(
                ERR_EXEMPTION_NOT_REVIEWABLE,
                "start-review requires the request to be in SUBMITTED.",
                409,
            )
        if user_id == ex["submitted_by_user_id"]:
            raise ApiError(
                ERR_SEGREGATION_OF_DUTIES,
                "Reviewer X-User-ID equals submitted_by_user_id.",
                409,
            )
        ex["status"] = "UNDER_REVIEW"
        ex["reviewed_by_user_id"] = user_id
        touch(ex)
        return success_object(exemption_view(ex))

    @app.post("/api/exemption-requests/<eid>/approve")
    def approve_exemption(eid):
        user_id, _ = require_roles("DistrictHealthOfficer")
        ex = db.exemption_requests.get(eid)
        if ex is None:
            raise ApiError(ERR_EXEMPTION_NOT_FOUND, "Exemption request not found.", 404)
        if ex["status"] != "UNDER_REVIEW":
            raise ApiError(
                ERR_EXEMPTION_NOT_REVIEWABLE,
                "approve requires the request to be in UNDER_REVIEW.",
                409,
            )
        if user_id == ex["submitted_by_user_id"]:
            raise ApiError(
                ERR_SEGREGATION_OF_DUTIES,
                "Reviewer X-User-ID equals submitted_by_user_id.",
                409,
            )
        student = db.students.get(ex["student_id"])
        if student is not None and _active_outbreak_for(student["school_code"], ex["vaccine_code"]):
            raise ApiError(
                ERR_OUTBREAK_ACTIVE,
                "Cannot approve while an outbreak is ACTIVE for (school_code, vaccine_code).",
                409,
            )
        ex["status"] = "APPROVED"
        touch(ex)
        if student is not None:
            reevaluate_student(student)
        return success_object(exemption_view(ex))

    @app.post("/api/exemption-requests/<eid>/deny")
    def deny_exemption(eid):
        user_id, _ = require_roles("DistrictHealthOfficer")
        ex = db.exemption_requests.get(eid)
        if ex is None:
            raise ApiError(ERR_EXEMPTION_NOT_FOUND, "Exemption request not found.", 404)
        if ex["status"] != "UNDER_REVIEW":
            raise ApiError(
                ERR_EXEMPTION_NOT_REVIEWABLE,
                "deny requires the request to be in UNDER_REVIEW.",
                409,
            )
        if user_id == ex["submitted_by_user_id"]:
            raise ApiError(
                ERR_SEGREGATION_OF_DUTIES,
                "Reviewer X-User-ID equals submitted_by_user_id.",
                409,
            )
        body = require_body(request.get_json(silent=True))
        denial_reason = req_string(body, "denial_reason")
        ex["status"] = "DENIED"
        ex["denial_reason"] = denial_reason
        touch(ex)
        return success_object(exemption_view(ex))

    @app.post("/api/exemption-requests/<eid>/resubmit")
    def resubmit_exemption(eid):
        user_id, _ = require_roles("SchoolNurse", "DistrictHealthOfficer")
        ex = db.exemption_requests.get(eid)
        if ex is None:
            raise ApiError(ERR_EXEMPTION_NOT_FOUND, "Exemption request not found.", 404)
        if ex["status"] != "DENIED":
            raise ApiError(
                ERR_EXEMPTION_NOT_RESUBMITTABLE,
                "resubmit requires the request to be in DENIED.",
                409,
            )
        body = require_body(request.get_json(silent=True))
        document_ref = req_string(body, "document_ref")
        ex["status"] = "SUBMITTED"
        ex["document_ref"] = document_ref
        ex["reviewed_by_user_id"] = None
        ex["denial_reason"] = None
        ex["submitted_by_user_id"] = user_id
        touch(ex)
        return success_object(exemption_view(ex))
