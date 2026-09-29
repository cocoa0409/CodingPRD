"""Distress observations and their quality control (PRD 3.2)."""
from flask import Blueprint

import calc
import db
import response
import validators as v
from errors import ApiError
from middleware import endpoint
from services import derive

bp = Blueprint("observations", __name__)

QC_DECISIONS = ("ACCEPT", "FLAG", "REJECT")
_QC_TARGET = {"ACCEPT": "ACCEPTED", "FLAG": "FLAGGED", "REJECT": "REJECTED"}

READ_ROLES = ("PavementEngineer", "BudgetOfficer", "Inspector")


def _find_observation(observation_id):
    obs = db.observations.get(observation_id)
    if obs is None:
        raise ApiError("ERR_OBSERVATION_NOT_FOUND")
    return obs


@bp.post("/distress-observations")
@endpoint("PavementEngineer")
def create_observation():
    data = v.body()
    survey_id = v.field_id(data, "survey_id")
    segment_id = v.field_id(data, "segment_id")
    alligator = v.field_number(data, "alligator_cracking_sqft", minimum=0)
    longitudinal = v.field_number(data, "longitudinal_cracking_lf", minimum=0)
    rutting = v.field_number(data, "rutting_depth_in", minimum=0, maximum=4)
    patching = v.field_number(data, "patching_sqft", minimum=0)
    iri = v.field_number(data, "iri_in_per_mi", minimum=0, maximum=600)
    coverage = v.field_number(data, "sample_coverage_pct", minimum=25, maximum=100)

    survey = db.surveys.get(survey_id)
    if survey is None:
        raise ApiError("ERR_SURVEY_NOT_FOUND")
    segment = db.segments.get(segment_id)
    if segment is None:
        raise ApiError("ERR_SEGMENT_NOT_FOUND")

    if survey["survey_status"] != "OPEN":
        raise ApiError("ERR_SURVEY_NOT_OPEN")
    for existing in derive.observations_of(survey_id):
        if existing["segment_id"] == segment_id:
            raise ApiError("ERR_DUPLICATE_OBSERVATION")

    obs = {
        "id": db.new_id(),
        "survey_id": survey_id,
        "segment_id": segment_id,
        "alligator_cracking_sqft": alligator,
        "longitudinal_cracking_lf": longitudinal,
        "rutting_depth_in": rutting,
        "patching_sqft": patching,
        "iri_in_per_mi": iri,
        "sample_coverage_pct": coverage,
        "deduct_total": None,
        "measured_condition_index": None,
        "qc_status": "PENDING",
        "qc_note": None,
    }
    deduct, measured = calc.survey_measured_condition_index(segment, obs)
    obs["deduct_total"] = deduct
    obs["measured_condition_index"] = measured
    obs.update(db.audit())
    db.observations[obs["id"]] = obs
    derive.recompute_survey_counters(survey)
    return response.object_response(obs, 201)


@bp.get("/distress-observations/<observation_id>")
@endpoint(*READ_ROLES)
def read_observation(observation_id):
    return response.object_response(_find_observation(observation_id))


@bp.get("/distress-observations")
@endpoint(*READ_ROLES)
def list_observations():
    rows = v.filter_rows(db.ordered(db.observations.values()), {
        "survey_id": "survey_id",
        "segment_id": "segment_id",
        "qc_status": "qc_status",
    })
    page, meta = v.paginate(rows)
    return response.array_response(page, pagination=meta)


@bp.post("/distress-observations/<observation_id>/qc")
@endpoint("PavementEngineer")
def decide_qc(observation_id):
    data = v.body()
    decision = v.field_enum(data, "qc_decision", QC_DECISIONS)
    note = v.field_string(data, "qc_note", 1, 500, required=False)

    obs = _find_observation(observation_id)
    survey = db.surveys.get(obs["survey_id"])
    if survey is None or survey["survey_status"] != "OPEN":
        raise ApiError("ERR_SURVEY_NOT_OPEN")
    if obs["qc_status"] not in ("PENDING", "FLAGGED"):
        raise ApiError("ERR_OBSERVATION_ALREADY_DECIDED")

    updates = {"qc_status": _QC_TARGET[decision]}
    if note is not None:
        updates["qc_note"] = note
    derive.apply_updates(obs, updates)
    derive.recompute_survey_counters(survey)
    return response.object_response(obs)
