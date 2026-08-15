"""Speed studies and observations (PRD §3.3; effectiveness in §3.8)."""
from flask import Blueprint, request

from auth import require_roles, ALL_ROLES
from calc import (
    aggregates, criteria_score, round_half_up_1,
    MIN_OBSERVATION_DAYS, SCORE_ELIGIBILITY_THRESHOLD,
    P85_REDUCTION_TARGET, MEAN_REDUCTION_TARGET,
)
from envelope import object_response
from errors import (
    ApiError, ERR_STUDY_INVALID_STATE, ERR_OBSERVATION_OUTSIDE_WINDOW,
    ERR_DUPLICATE_OBSERVATION_DATE, ERR_INSUFFICIENT_OBSERVATION_DAYS,
)
from helpers import get_study, paginated, recompute_observation_counts
from store import store, touch
from validate import parse_body, Struct

bp = Blueprint("studies", __name__)


@bp.get("/api/speed-studies/<studyId>")
@require_roles(*ALL_ROLES)
def get_one(studyId):
    return object_response(get_study(studyId))


@bp.get("/api/speed-studies")
@require_roles(*ALL_ROLES)
def list_studies():
    return paginated(list(store.studies.values()), {
        "request_id": request.args.get("request_id"),
        "study_type": request.args.get("study_type"),
        "status": request.args.get("status"),
    })


@bp.post("/api/speed-studies/<studyId>/observations")
@require_roles("TrafficEngineer")
def record_observation(studyId):
    study = get_study(studyId)
    data, perr = parse_body()
    s = Struct(data, perr)
    obs_date = s.get_date("observation_date")
    vehicle_count = s.get_int("vehicle_count", min=0)
    p85 = s.get_num("p85_speed_mph", positive=True)
    mean = s.get_num("mean_speed_mph", positive=True)
    is_valid = s.get_bool("is_valid", default=True)
    # Tier 5: study must be COLLECTING
    if study["status"] != "COLLECTING":
        raise ApiError(409, ERR_STUDY_INVALID_STATE,
                       "Observations can only be recorded while the study is COLLECTING")
    # Tier 7: date inside the inclusive collection window
    if obs_date is not None and not (study["window_start_date"] <= obs_date <= study["window_end_date"]):
        raise ApiError(409, ERR_OBSERVATION_OUTSIDE_WINDOW,
                       "observation_date is outside the study window")
    # Tier 8: structural, then duplicate date
    s.raise_if_errors()
    for o in store.observations.values():
        if o["study_id"] == studyId and o["observation_date"] == obs_date:
            raise ApiError(409, ERR_DUPLICATE_OBSERVATION_DATE,
                           "An observation for this date already exists in the study")
    obs = {
        "id": store.new_id(),
        "study_id": studyId,
        "observation_date": obs_date,
        "vehicle_count": vehicle_count,
        "p85_speed_mph": p85,
        "mean_speed_mph": mean,
        "is_valid": is_valid,
        "created_at": store.now,
        "_seq": store.next_seq(),
    }
    store.observations[obs["id"]] = obs
    recompute_observation_counts(study)
    touch(study)
    return object_response(obs, 201)


@bp.get("/api/speed-studies/<studyId>/observations")
@require_roles(*ALL_ROLES)
def list_observations(studyId):
    get_study(studyId)
    items = [o for o in store.observations.values() if o["study_id"] == studyId]
    return paginated(items)


@bp.post("/api/speed-studies/<studyId>/analyze")
@require_roles("TrafficEngineer")
def analyze(studyId):
    study = get_study(studyId)
    if study["status"] != "COLLECTING":
        raise ApiError(409, ERR_STUDY_INVALID_STATE,
                       "Only a COLLECTING study can be analyzed")
    if study["observation_count"] < MIN_OBSERVATION_DAYS:
        raise ApiError(409, ERR_INSUFFICIENT_OBSERVATION_DAYS,
                       "Fewer than 3 observations recorded")
    # Provisional aggregates over ALL observations, outliers included (PRD §3.3)
    obs = [o for o in store.observations.values() if o["study_id"] == studyId]
    p85, mean, adv = aggregates(obs)
    req = store.requests[study["request_id"]]
    segment = store.segments[req["street_segment_id"]]
    study["provisional_p85_mph"] = p85
    study["provisional_mean_speed_mph"] = mean
    study["provisional_avg_daily_volume"] = adv
    study["provisional_score"] = criteria_score(p85, adv, segment)
    study["status"] = "ANALYZED"
    touch(study)
    return object_response(study)


@bp.post("/api/speed-studies/<studyId>/return-for-recollection")
@require_roles("TrafficEngineer")
def return_for_recollection(studyId):
    study = get_study(studyId)
    if study["status"] != "ANALYZED":
        raise ApiError(409, ERR_STUDY_INVALID_STATE,
                       "Only an ANALYZED study can be returned for recollection")
    study["status"] = "COLLECTING"
    touch(study)
    return object_response(study)


@bp.post("/api/speed-studies/<studyId>/certify")
@require_roles("TrafficEngineer")
def certify(studyId):
    study = get_study(studyId)
    if study["status"] != "ANALYZED":
        raise ApiError(409, ERR_STUDY_INVALID_STATE,
                       "Only an ANALYZED study can be certified")
    if study["valid_observation_count"] < MIN_OBSERVATION_DAYS:
        raise ApiError(409, ERR_INSUFFICIENT_OBSERVATION_DAYS,
                       "Fewer than 3 valid observations recorded")
    # Certified aggregates over valid observations only (PRD §3.3)
    valid = [o for o in store.observations.values()
             if o["study_id"] == studyId and o["is_valid"]]
    p85, mean, adv = aggregates(valid)
    req = store.requests[study["request_id"]]
    segment = store.segments[req["street_segment_id"]]
    score = criteria_score(p85, adv, segment)
    study["certified_p85_mph"] = p85
    study["certified_mean_speed_mph"] = mean
    study["certified_avg_daily_volume"] = adv
    study["certified_score"] = score
    study["status"] = "CERTIFIED"
    touch(study)
    if study["study_type"] == "INITIAL":
        # Fork the request at the inclusive 60-point threshold (PRD §3.3)
        req["certified_score"] = score
        req["status"] = "RANKING_ELIGIBLE" if score >= SCORE_ELIGIBILITY_THRESHOLD \
            else "SCORE_INELIGIBLE"
    else:
        # Effectiveness verdicts (PRD §3.8), both rounded half-up to 1 dp
        p85_red = round_half_up_1(study["baseline_p85_mph"] - p85)
        mean_red = round_half_up_1(study["baseline_mean_speed_mph"] - mean)
        study["p85_reduction_mph"] = p85_red
        study["mean_reduction_mph"] = mean_red
        study["meets_effectiveness_target"] = p85_red >= P85_REDUCTION_TARGET
        study["meets_target_mean_variant"] = mean_red >= MEAN_REDUCTION_TARGET
        req["status"] = "EFFECTIVENESS_CERTIFIED"
    touch(req)
    return object_response(study)
