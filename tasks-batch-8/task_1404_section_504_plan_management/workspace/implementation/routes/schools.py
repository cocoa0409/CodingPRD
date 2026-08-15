"""Schools: create, list, detail, compliance summary."""
from flask import Blueprint

from db import db, create_record
from middleware import body, req_str, require_roles
from response import success
from routes import list_response
from services import (coverage_pct, get_school, open_grievance_count,
                      overdue_review_count, posture_components, school_out)

bp = Blueprint("schools", __name__)


@bp.post("/schools")
@require_roles("District504Director")
def create_school():
    d = body()
    rec = create_record(db.schools, {
        "school_name": req_str(d, "school_name"),
        "district_code": req_str(d, "district_code"),
        "school_posture": "OPERATIONAL",
        "current_academic_year": req_str(d, "current_academic_year"),
    })
    return success(school_out(rec), 201)


@bp.get("/schools")
@require_roles("District504Director", "Section504Coordinator", "SchoolPrincipal", "Teacher", "Parent")
def list_schools():
    return list_response(list(db.schools.values()), school_out)


@bp.get("/schools/<schoolId>")
@require_roles("District504Director", "Section504Coordinator", "SchoolPrincipal", "Teacher", "Parent")
def get_school_detail(schoolId):
    return success(school_out(get_school(schoolId)), 200)


@bp.get("/schools/<schoolId>/compliance-summary")
@require_roles("District504Director", "Section504Coordinator", "SchoolPrincipal")
def school_compliance_summary(schoolId):
    s = get_school(schoolId)
    posture, score, open_g, overdue_r = posture_components(s["id"])
    data = {
        "posture": posture,
        "training_coverage_pct": coverage_pct(s["id"]),
        "open_grievance_count": open_g,
        "overdue_review_count": overdue_r,
        "composite_score": score,
    }
    return success(data, 200)
