"""Contractor registration and the two performance-score variants (PRD 3.7)."""
from flask import Blueprint

import db
import response
import validators as v
from errors import ApiError
from middleware import endpoint
from services import derive

bp = Blueprint("contractors", __name__)


def _find_contractor(contractor_id):
    contractor = db.contractors.get(contractor_id)
    if contractor is None:
        raise ApiError("ERR_CONTRACTOR_NOT_FOUND")
    return contractor


@bp.post("/contractors")
@endpoint("PavementEngineer")
def create_contractor():
    data = v.body()
    legal_name = v.field_string(data, "legal_name", 1, 120)
    max_concurrent = v.field_int(data, "max_concurrent_projects", minimum=1,
                                 maximum=10, required=False, default=2)
    contractor = {
        "id": db.new_id(),
        "legal_name": legal_name,
        "max_concurrent_projects": max_concurrent,
        "standing": "GOOD_STANDING",
        "interim_performance_score": 100.0,
        "final_performance_score": None,
        "passed_test_count": 0,
        "failed_test_count": 0,
        "remediation_event_count": 0,
        "days_late_total": 0,
        "accepted_project_count": 0,
    }
    contractor.update(db.audit())
    db.contractors[contractor["id"]] = contractor
    return response.object_response(contractor, 201)


@bp.get("/contractors/<contractor_id>")
@endpoint("PavementEngineer", "BudgetOfficer", "Inspector", "Contractor")
def read_contractor(contractor_id):
    return response.object_response(_find_contractor(contractor_id))


@bp.get("/contractors")
@endpoint("PavementEngineer", "BudgetOfficer", "Inspector")
def list_contractors():
    rows = v.filter_rows(db.ordered(db.contractors.values()), {
        "standing": "standing",
    })
    page, meta = v.paginate(rows)
    return response.array_response(page, pagination=meta)


@bp.get("/contractors/<contractor_id>/scorecard")
@endpoint("PavementEngineer", "BudgetOfficer", "Inspector", "Contractor")
def read_scorecard(contractor_id):
    contractor = _find_contractor(contractor_id)
    interim, final = derive.scorecard(contractor)
    final_score = None if contractor["accepted_project_count"] == 0 \
        else final["composite"]
    return response.object_response({
        "contractor_id": contractor["id"],
        "standing": contractor["standing"],
        "interim_performance_score": interim["composite"],
        "final_performance_score": final_score,
        "interim_quality_component": interim["quality"],
        "interim_schedule_component": interim["schedule"],
        "interim_remediation_component": interim["remediation"],
        "final_quality_component": final["quality"],
        "final_schedule_component": final["schedule"],
        "final_remediation_component": final["remediation"],
        "passed_test_count": contractor["passed_test_count"],
        "failed_test_count": contractor["failed_test_count"],
        "remediation_event_count": contractor["remediation_event_count"],
        "days_late_total": contractor["days_late_total"],
        "accepted_project_count": contractor["accepted_project_count"],
    })
