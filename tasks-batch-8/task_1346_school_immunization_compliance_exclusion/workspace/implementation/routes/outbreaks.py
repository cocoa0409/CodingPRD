"""OutbreakEvent endpoints (PRD §3.6)."""

from flask import request

import db
from db import clock, format_iso, stamp_new, touch
from errors import (
    ApiError,
    ERR_OUTBREAK_ALREADY_ACTIVE,
    ERR_OUTBREAK_ALREADY_LIFTED,
    ERR_OUTBREAK_NOT_FOUND,
)
from middleware import require_roles
from response import success_object
from services.evaluation import (
    VACCINE_CODES,
    deficiency_codes,
    evaluate_requirement,
    outbreak_view,
    applicable_requirements,
)
from services.validate import req_enum, req_string, require_body


def register(app):

    @app.post("/api/outbreak-events")
    def declare_outbreak():
        require_roles("DistrictHealthOfficer")
        body = require_body(request.get_json(silent=True))
        school_code = req_string(body, "school_code")
        vaccine_code = req_enum(body, "vaccine_code", VACCINE_CODES)

        # 8d: only one ACTIVE per (school_code, vaccine_code)
        for ev in db.outbreak_events.values():
            if ev["status"] == "ACTIVE" and ev["school_code"] == school_code \
                    and ev["vaccine_code"] == vaccine_code:
                raise ApiError(
                    ERR_OUTBREAK_ALREADY_ACTIVE,
                    "An OutbreakEvent with status ACTIVE already exists for (school_code, vaccine_code).",
                    409,
                )

        now = clock.now()
        now_iso = format_iso(now)
        event = {
            "school_code": school_code,
            "vaccine_code": vaccine_code,
            "status": "ACTIVE",
            "declared_at": now_iso,
            "lifted_at": None,
        }
        stamp_new(event)
        db.outbreak_events[event["id"]] = event

        # Cascade: every APPROVED ExemptionRequest whose student's school_code
        # matches and whose vaccine_code matches -> SUSPENDED_OUTBREAK.
        affected_students = set()
        for ex in db.exemption_requests.values():
            if ex["status"] != "APPROVED":
                continue
            if ex["vaccine_code"] != vaccine_code:
                continue
            student = db.students.get(ex["student_id"])
            if student is None:
                continue
            if student["school_code"] != school_code:
                continue
            ex["status"] = "SUSPENDED_OUTBREAK"
            touch(ex)
            affected_students.add(student["id"])

        # Each affected student is re-evaluated and transitions to EXCLUDED.
        for sid in affected_students:
            student = db.students[sid]
            if student["status"] == "WITHDRAWN":
                # Withdrawn students do not transition (terminal).
                continue
            # Create OUTBREAK_EXCLUSION notice in EXCLUSION_EFFECTIVE
            notice = {
                "student_id": student["id"],
                "notice_type": "OUTBREAK_EXCLUSION",
                "status": "EXCLUSION_EFFECTIVE",
                "issue_date": now_iso,
                "exclusion_date": now_iso,
                "resolved_at": None,
            }
            stamp_new(notice)
            db.compliance_notices[notice["id"]] = notice
            student["status"] = "EXCLUDED"
            student["deficiency_vaccine_codes"] = deficiency_codes(student)
            touch(student)

        return success_object(outbreak_view(event), status=201)

    @app.post("/api/outbreak-events/<oid>/lift")
    def lift_outbreak(oid):
        require_roles("DistrictHealthOfficer")
        event = db.outbreak_events.get(oid)
        if event is None:
            raise ApiError(ERR_OUTBREAK_NOT_FOUND, "Outbreak event not found.", 404)
        if event["status"] != "ACTIVE":
            raise ApiError(
                ERR_OUTBREAK_ALREADY_LIFTED,
                "lift requires the OutbreakEvent to be ACTIVE.",
                409,
            )
        now = clock.now()
        now_iso = format_iso(now)
        event["status"] = "LIFTED"
        event["lifted_at"] = now_iso
        touch(event)

        # Reinstate suspended exemptions
        affected_students = set()
        for ex in db.exemption_requests.values():
            if ex["status"] != "SUSPENDED_OUTBREAK":
                continue
            if ex["vaccine_code"] != event["vaccine_code"]:
                continue
            student = db.students.get(ex["student_id"])
            if student is None or student["school_code"] != event["school_code"]:
                continue
            ex["status"] = "APPROVED"
            touch(ex)
            affected_students.add(student["id"])

        # Re-evaluate each affected EXCLUDED student
        for sid in affected_students:
            student = db.students[sid]
            if student["status"] != "EXCLUDED":
                continue
            codes = deficiency_codes(student)
            # Cure this student's OUTBREAK_EXCLUSION notice in EXCLUSION_EFFECTIVE
            for notice in db.compliance_notices.values():
                if notice["student_id"] == student["id"] \
                        and notice["notice_type"] == "OUTBREAK_EXCLUSION" \
                        and notice["status"] == "EXCLUSION_EFFECTIVE":
                    notice["status"] = "CURED"
                    notice["resolved_at"] = now_iso
                    touch(notice)
            if not codes:
                student["status"] = "ENROLLED_COMPLIANT"
                student["deficiency_vaccine_codes"] = []
            else:
                student["status"] = "NON_COMPLIANT"
                student["deficiency_vaccine_codes"] = codes
            touch(student)

        return success_object(outbreak_view(event))
