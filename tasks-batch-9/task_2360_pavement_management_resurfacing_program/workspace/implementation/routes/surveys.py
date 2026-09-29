"""Condition surveys: collection, quality control, sealing, selection
(PRD 3.2, 3.3)."""
from flask import Blueprint

import calc
import clock
import db
import response
import validators as v
from errors import ApiError
from middleware import endpoint
from services import derive

bp = Blueprint("surveys", __name__)

COLLECTION_METHODS = ("AUTOMATED_LCMS", "MANUAL_WALK")


def _find_survey(survey_id):
    survey = db.surveys.get(survey_id)
    if survey is None:
        raise ApiError("ERR_SURVEY_NOT_FOUND")
    return survey


@bp.post("/condition-surveys")
@endpoint("PavementEngineer")
def create_survey():
    data = v.body()
    survey_year = v.field_int(data, "survey_year", minimum=2020, maximum=2040)
    collection_method = v.field_enum(data, "collection_method", COLLECTION_METHODS)
    survey = {
        "id": db.new_id(),
        "survey_year": survey_year,
        "collection_method": collection_method,
        "survey_status": "OPEN",
        "observation_count": 0,
        "accepted_observation_count": 0,
        "network_condition_index": None,
        "sealed_at": None,
    }
    survey.update(db.audit())
    db.surveys[survey["id"]] = survey
    return response.object_response(survey, 201)


@bp.get("/condition-surveys/<survey_id>")
@endpoint("PavementEngineer", "BudgetOfficer", "Inspector")
def read_survey(survey_id):
    return response.object_response(_find_survey(survey_id))


@bp.get("/condition-surveys")
@endpoint("PavementEngineer", "BudgetOfficer", "Inspector")
def list_surveys():
    rows = v.filter_rows(db.ordered(db.surveys.values()), {
        "survey_year": "survey_year",
        "survey_status": "survey_status",
        "collection_method": "collection_method",
    })
    page, meta = v.paginate(rows)
    return response.array_response(page, pagination=meta)


@bp.post("/condition-surveys/<survey_id>/seal")
@endpoint("PavementEngineer")
def seal_survey(survey_id):
    v.body()
    survey = _find_survey(survey_id)
    if survey["survey_status"] != "OPEN":
        raise ApiError("ERR_SURVEY_NOT_OPEN")
    rows = derive.observations_of(survey["id"])
    if any(o["qc_status"] == "PENDING" for o in rows):
        raise ApiError("ERR_OBSERVATIONS_PENDING_QC")
    accepted = [o for o in rows if o["qc_status"] == "ACCEPTED"]
    if not accepted:
        raise ApiError("ERR_SURVEY_HAS_NO_ACCEPTED_OBSERVATIONS")

    now = clock.now()
    network_index = calc.area_weighted_index([
        (db.segments[o["segment_id"]]["area_sy"], o["measured_condition_index"])
        for o in accepted
    ])
    derive.apply_updates(survey, {
        "survey_status": "SEALED",
        "sealed_at": now,
        "network_condition_index": network_index,
    })

    # Level 1 — republish measured condition on the surveyed segments.
    segment_ids = set()
    for obs in db.ordered(accepted):
        segment = db.segments[obs["segment_id"]]
        derive.set_segment_condition(
            segment, obs["measured_condition_index"], "SURVEY_MEASURED"
        )
        segment_ids.add(segment["id"])

    # Level 2 — supersede stale candidates from other surveys.
    superseded = []
    for candidate in db.ordered(db.candidates.values()):
        if (candidate["segment_id"] in segment_ids
                and candidate["candidate_status"] in ("RECOMMENDED", "OVERRIDDEN")
                and candidate["survey_id"] != survey["id"]):
            derive.apply_updates(candidate, {"candidate_status": "SUPERSEDED"})
            superseded.append(candidate)

    # Level 3 — withdraw the allocations of those candidates.
    affected = []
    for candidate in superseded:
        for alloc in db.ordered(derive.allocations_of_candidate(candidate["id"])):
            if alloc["allocation_status"] in ("FUNDED", "DEFERRED"):
                derive.apply_updates(alloc, {
                    "allocation_status": "WITHDRAWN",
                    "allocated_cents": 0,
                })
                if alloc["scenario_id"] not in affected:
                    affected.append(alloc["scenario_id"])

    # Level 4 — re-total the affected scenarios.
    for scenario_id in affected:
        scenario = db.scenarios.get(scenario_id)
        if scenario is not None:
            derive.recompute_scenario_totals(scenario)

    return response.object_response(survey)


@bp.post("/condition-surveys/<survey_id>/generate-candidates")
@endpoint("PavementEngineer")
def generate_candidates(survey_id):
    v.body()
    survey = _find_survey(survey_id)
    if survey["survey_status"] != "SEALED":
        raise ApiError("ERR_SURVEY_NOT_SEALED")
    if derive.candidates_of_survey(survey["id"]):
        raise ApiError("ERR_CANDIDATES_ALREADY_GENERATED")

    accepted = [o for o in derive.observations_of(survey["id"])
                if o["qc_status"] == "ACCEPTED"]
    pool = []
    for obs in accepted:
        segment = db.segments[obs["segment_id"]]
        if calc.D(segment["condition_index"]) < calc.D("90.0"):
            pool.append(segment)
    pool.sort(key=lambda s: (calc.D(s["condition_index"]), s["created_at"], s["_seq"]))

    created = []
    for segment in pool:
        snapshot = segment["condition_index"]
        treatment = calc.select_treatment(snapshot)
        candidate = {
            "id": db.new_id(),
            "survey_id": survey["id"],
            "segment_id": segment["id"],
            "treatment_type": treatment,
            "selection_condition_index": calc.num(snapshot, 1),
            "candidate_status": "RECOMMENDED",
            "override_reason": None,
        }
        candidate.update(calc.candidate_pricing(segment, treatment, snapshot))
        candidate.update(db.audit())
        db.candidates[candidate["id"]] = candidate
        created.append(candidate)
    return response.array_response(created, 201)
