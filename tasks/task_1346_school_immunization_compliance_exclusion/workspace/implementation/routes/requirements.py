"""VaccineRequirement endpoints (PRD §3.2)."""

from flask import request

import db
from db import stamp_new
from errors import ApiError, ERR_DUPLICATE_REQUIREMENT
from middleware import require_roles
from response import success_object, success_list
from services.evaluation import GRADES, VACCINE_CODES, requirement_view
from services.validate import (
    parse_pagination, paginate, req_enum, req_int, req_list_of_strings,
    req_string, require_body,
)

ALL_ROLES = ("HealthClerk", "SchoolNurse", "DistrictHealthOfficer", "RegistryCoordinator")


def register(app):

    @app.post("/api/vaccine-requirements")
    def create_requirement():
        require_roles("DistrictHealthOfficer")
        body = require_body(request.get_json(silent=True))
        vaccine_code = req_enum(body, "vaccine_code", VACCINE_CODES)
        applies_to_grades = req_list_of_strings(body, "applies_to_grades", GRADES)
        doses_required = req_int(body, "doses_required", minimum=1)
        min_interval_days = req_int(body, "min_interval_days", minimum=0)
        min_age_months = req_int(body, "min_age_months", minimum=0)
        school_year = req_string(body, "school_year")

        # Uniqueness on (vaccine_code, school_year)
        for existing in db.vaccine_requirements.values():
            if existing["vaccine_code"] == vaccine_code \
                    and existing["school_year"] == school_year:
                raise ApiError(
                    ERR_DUPLICATE_REQUIREMENT,
                    "A VaccineRequirement already exists for (vaccine_code, school_year).",
                    409,
                )

        req = {
            "vaccine_code": vaccine_code,
            "applies_to_grades": list(applies_to_grades),
            "doses_required": doses_required,
            "min_interval_days": min_interval_days,
            "min_age_months": min_age_months,
            "school_year": school_year,
        }
        stamp_new(req)
        db.vaccine_requirements[req["id"]] = req
        return success_object(requirement_view(req), status=201)

    @app.get("/api/vaccine-requirements")
    def list_requirements():
        require_roles(*ALL_ROLES)
        limit, offset = parse_pagination(request.args)
        grade = request.args.get("grade")
        school_year = request.args.get("school_year")
        items = list(db.vaccine_requirements.values())
        if school_year is not None:
            items = [r for r in items if r["school_year"] == school_year]
        if grade is not None:
            items = [r for r in items if grade in r["applies_to_grades"]]
        items.sort(key=lambda r: (r["created_at"], r["id"]))
        page, total = paginate(items, limit, offset)
        return success_list([requirement_view(r) for r in page], limit, offset, total)
