"""ComplianceNotice endpoints (PRD §3.5)."""

from datetime import timedelta

from flask import request

import db
from db import clock, format_iso, stamp_new, touch
from errors import (
    ApiError,
    ERR_NOTICE_NOT_ALLOWED,
    ERR_NOTICE_NOT_FOUND,
    ERR_NOTICE_NOT_OPEN,
    ERR_STUDENT_NOT_FOUND,
)
from middleware import require_roles
from response import success_object, success_list
from services.evaluation import notice_view
from services.validate import (
    parse_pagination, paginate, req_enum, req_string, require_body,
)

ALL_ROLES = ("HealthClerk", "SchoolNurse", "DistrictHealthOfficer", "RegistryCoordinator")
NOTICE_TYPES = ("INITIAL_NONCOMPLIANCE", "OUTBREAK_EXCLUSION")


def register(app):

    @app.post("/api/students/<sid>/compliance-notices")
    def create_notice(sid):
        require_roles("DistrictHealthOfficer")
        student = db.students.get(sid)
        if student is None:
            raise ApiError(ERR_STUDENT_NOT_FOUND, "Student not found.", 404)
        body = require_body(request.get_json(silent=True))
        notice_type = req_enum(body, "notice_type", NOTICE_TYPES)
        # Manual creation: only INITIAL_NONCOMPLIANCE, and only against NON_COMPLIANT
        if notice_type != "INITIAL_NONCOMPLIANCE":
            raise ApiError(
                ERR_NOTICE_NOT_ALLOWED,
                "OUTBREAK_EXCLUSION notices are system-created only.",
                422,
            )
        if student["status"] != "NON_COMPLIANT":
            raise ApiError(
                ERR_NOTICE_NOT_ALLOWED,
                "Manual INITIAL_NONCOMPLIANCE notice requires Student.status == NON_COMPLIANT.",
                422,
            )
        now = clock.now()
        notice = {
            "student_id": student["id"],
            "notice_type": notice_type,
            "status": "ISSUED",
            "issue_date": format_iso(now),
            "exclusion_date": format_iso(now + timedelta(days=14)),
            "resolved_at": None,
        }
        stamp_new(notice)
        db.compliance_notices[notice["id"]] = notice
        return success_object(notice_view(notice), status=201)

    @app.get("/api/students/<sid>/compliance-notices")
    def list_notices(sid):
        require_roles(*ALL_ROLES)
        student = db.students.get(sid)
        if student is None:
            raise ApiError(ERR_STUDENT_NOT_FOUND, "Student not found.", 404)
        limit, offset = parse_pagination(request.args)
        status = request.args.get("status")
        items = [n for n in db.compliance_notices.values() if n["student_id"] == sid]
        if status is not None:
            items = [n for n in items if n["status"] == status]
        items.sort(key=lambda n: (n["created_at"], n["id"]))
        page, total = paginate(items, limit, offset)
        return success_list([notice_view(n) for n in page], limit, offset, total)

    @app.post("/api/compliance-notices/<nid>/rescind")
    def rescind_notice(nid):
        require_roles("DistrictHealthOfficer")
        notice = db.compliance_notices.get(nid)
        if notice is None:
            raise ApiError(ERR_NOTICE_NOT_FOUND, "Compliance notice not found.", 404)
        if notice["status"] != "ISSUED":
            raise ApiError(
                ERR_NOTICE_NOT_OPEN,
                "rescind requires the notice to be in ISSUED.",
                409,
            )
        body = require_body(request.get_json(silent=True))
        req_string(body, "reason")
        notice["status"] = "RESCINDED"
        notice["resolved_at"] = format_iso(clock.now())
        touch(notice)
        return success_object(notice_view(notice))
