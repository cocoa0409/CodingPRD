"""Treatment candidates and engineering overrides (PRD 3.3)."""
from flask import Blueprint

import calc
import db
import response
import validators as v
from errors import ApiError
from middleware import endpoint
from services import derive

bp = Blueprint("candidates", __name__)

READ_ROLES = ("PavementEngineer", "BudgetOfficer", "Inspector")


def _find_candidate(candidate_id):
    candidate = db.candidates.get(candidate_id)
    if candidate is None:
        raise ApiError("ERR_CANDIDATE_NOT_FOUND")
    return candidate


@bp.get("/treatment-candidates/<candidate_id>")
@endpoint(*READ_ROLES)
def read_candidate(candidate_id):
    return response.object_response(_find_candidate(candidate_id))


@bp.get("/treatment-candidates")
@endpoint(*READ_ROLES)
def list_candidates():
    rows = v.filter_rows(db.ordered(db.candidates.values()), {
        "survey_id": "survey_id",
        "segment_id": "segment_id",
        "candidate_status": "candidate_status",
        "treatment_type": "treatment_type",
    })
    page, meta = v.paginate(rows)
    return response.array_response(page, pagination=meta)


@bp.post("/treatment-candidates/<candidate_id>/override")
@endpoint("PavementEngineer")
def override_candidate(candidate_id):
    data = v.body()
    treatment_type = v.field_enum(data, "treatment_type", calc.TREATMENTS)
    override_reason = v.field_string(data, "override_reason", 1, 500)

    candidate = _find_candidate(candidate_id)
    if candidate["candidate_status"] not in ("RECOMMENDED", "OVERRIDDEN"):
        raise ApiError("ERR_CANDIDATE_NOT_OVERRIDABLE")
    if treatment_type == candidate["treatment_type"]:
        v.invalid("The requested treatment_type must differ from the current one.")
    for scenario in derive.scenarios_of_survey(candidate["survey_id"]):
        if scenario["scenario_status"] == "ADOPTED":
            raise ApiError("ERR_SURVEY_PROGRAM_LOCKED")

    segment = db.segments[candidate["segment_id"]]
    snapshot = candidate["selection_condition_index"]
    updates = {
        "treatment_type": treatment_type,
        "candidate_status": "OVERRIDDEN",
        "override_reason": override_reason,
    }
    updates.update(calc.candidate_pricing(segment, treatment_type, snapshot))
    derive.apply_updates(candidate, updates)
    return response.object_response(candidate)
