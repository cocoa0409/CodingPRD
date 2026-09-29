"""SurveyRound and SurveyObservation (11 endpoints).

The compound guard lives here: a round may only lock once every participating
Unit has at least one observation, and publishing writes the divergent
prevalence / incidence metrics onto each Unit.
"""

import calc
import services
from core import (
    READ_ROLES,
    ROLE_DIRECTOR,
    ROLE_WOC_NURSE,
    F,
    apply_filters,
    authorize,
    bad_request,
    bump,
    chrono,
    fail,
    filters,
    insert,
    must,
    new_row,
    now,
    ok,
    ok_list,
    pagination,
    paginate,
    parse_input,
    public,
    public_list,
    rows_of,
    store,
)
from flask import Blueprint

bp = Blueprint("survey", __name__)

ROUND_TYPES = ("PREVALENCE", "INCIDENCE")
ROUND_STATUSES = ("PLANNED", "OPEN", "LOCKED", "PUBLISHED", "CANCELLED")
OBS_STAGES = ("MUCOSAL", "STAGE_1", "STAGE_2", "STAGE_3", "STAGE_4", "DTI",
              "UNSTAGEABLE")
OBS_CLASSIFICATIONS = ("NONE", "POA", "HAPI")


@bp.post("/survey-rounds")
def create_round():
    authorize(ROLE_DIRECTOR)
    body = parse_input([
        F("round_type", "enum", required=True, enum=ROUND_TYPES),
        F("window_start", "datetime", required=True),
        F("window_end", "datetime", required=True),
        F("participating_unit_ids", "id_list", required=True, min_items=1),
    ])
    unit_ids = body["participating_unit_ids"]
    if len(unit_ids) > 20:
        bad_request("participating_unit_ids accepts at most 20 Unit ids.")
    if len(set(unit_ids)) != len(unit_ids):
        bad_request("participating_unit_ids must not repeat a Unit id.")
    if body["window_end"] <= body["window_start"]:
        bad_request("window_end must be strictly after window_start.")
    # Each element is resolved in declared order.
    for unit_id in unit_ids:
        must("units", unit_id)
    survey_round = new_row(
        "round",
        round_type=body["round_type"],
        window_start=body["window_start"],
        window_end=body["window_end"],
        participating_unit_ids=list(unit_ids),
        status="PLANNED",
        observation_count=0,
        published_at=None,
    )
    insert("survey_rounds", survey_round)
    return ok(public(survey_round), 201)


@bp.get("/survey-rounds")
def list_rounds():
    authorize(*READ_ROLES)
    limit, offset = pagination()
    active = filters({"status": ROUND_STATUSES, "round_type": ROUND_TYPES})
    rows = chrono(apply_filters(rows_of("survey_rounds"), active))
    page, total = paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


@bp.get("/survey-rounds/<round_id>")
def get_round(round_id):
    authorize(*READ_ROLES)
    return ok(public(must("survey_rounds", round_id)))


@bp.post("/survey-rounds/<round_id>/open")
def open_round(round_id):
    authorize(ROLE_DIRECTOR)
    parse_input([])
    survey_round = must("survey_rounds", round_id)
    if survey_round.get("status") != "PLANNED":
        fail("ERR_SURVEY_ROUND_NOT_OPEN")
    if services.survey_window_conflict(survey_round):
        fail("ERR_SURVEY_WINDOW_CONFLICT")
    survey_round["status"] = "OPEN"
    bump(survey_round)
    return ok(public(survey_round))


@bp.post("/survey-rounds/<round_id>/lock")
def lock_round(round_id):
    authorize(ROLE_DIRECTOR)
    parse_input([])
    survey_round = must("survey_rounds", round_id)
    if survey_round.get("status") != "OPEN":
        fail("ERR_SURVEY_ROUND_NOT_OPEN")
    covered = {o.get("unit_id") for o in rows_of("survey_observations")
               if o.get("survey_round_id") == round_id}
    for unit_id in survey_round.get("participating_unit_ids") or []:
        if unit_id not in covered:
            fail("ERR_SURVEY_UNIT_COVERAGE_INCOMPLETE")
    survey_round["status"] = "LOCKED"
    bump(survey_round)
    return ok(public(survey_round))


@bp.post("/survey-rounds/<round_id>/publish")
def publish_round(round_id):
    authorize(ROLE_DIRECTOR)
    parse_input([])
    survey_round = must("survey_rounds", round_id)
    if survey_round.get("status") != "LOCKED":
        fail("ERR_SURVEY_ROUND_NOT_OPEN")
    survey_round["published_at"] = now()
    survey_round["status"] = "PUBLISHED"
    for unit_id in survey_round.get("participating_unit_ids") or []:
        unit = store("units").get(unit_id)
        if unit is None:
            continue
        observations = services.observations_for(round_id, unit_id)
        if survey_round.get("round_type") == "PREVALENCE":
            _n, _d, rate = calc.prevalence_metric(observations)
            unit["last_prevalence_rate"] = rate
        else:
            _n, _d, rate = calc.incidence_metric(
                observations, survey_round.get("window_start"),
                survey_round.get("window_end"))
            unit["last_incidence_rate"] = rate
        bump(unit)
    bump(survey_round)
    return ok(public(survey_round))


@bp.post("/survey-rounds/<round_id>/cancel")
def cancel_round(round_id):
    authorize(ROLE_DIRECTOR)
    parse_input([F("reason", "string", required=True, min_len=1, max_len=2000)])
    survey_round = must("survey_rounds", round_id)
    if survey_round.get("status") not in ("PLANNED", "OPEN"):
        fail("ERR_SURVEY_ROUND_NOT_OPEN")
    survey_round["status"] = "CANCELLED"
    bump(survey_round)
    return ok(public(survey_round))


@bp.get("/survey-rounds/<round_id>/unit-report")
def round_unit_report(round_id):
    authorize(*READ_ROLES)
    survey_round = must("survey_rounds", round_id)
    window_start = survey_round.get("window_start")
    window_end = survey_round.get("window_end")
    unit_rows = []
    for unit_id in survey_round.get("participating_unit_ids") or []:
        unit = store("units").get(unit_id)
        observations = services.observations_for(round_id, unit_id)
        prev_num, prev_den, prevalence = calc.prevalence_metric(observations)
        inc_num, inc_den, incidence = calc.incidence_metric(
            observations, window_start, window_end)
        unit_rows.append({
            "unit_id": unit_id,
            "unit_code": unit.get("unit_code") if unit else None,
            "observation_count": prev_den,
            "injury_present_count": prev_num,
            "hapi_in_window_count": inc_num,
            "at_risk_count": inc_den,
            "prevalence_rate": prevalence,
            "incidence_rate": incidence,
        })
    return ok({
        "round_id": survey_round["id"],
        "round_type": survey_round.get("round_type"),
        "observation_total": len(services.observations_for(round_id)),
        "unit_rows": unit_rows,
    })


# ---------------------------------------------------------------------------
# SurveyObservation — immutable rows (no common_fields update path)
# ---------------------------------------------------------------------------
@bp.post("/survey-observations")
def create_observation():
    authorize(ROLE_WOC_NURSE)
    body = parse_input([
        F("survey_round_id", "id", required=True),
        F("unit_id", "id", required=True),
        F("patient_id", "id", required=True),
        F("observer_nurse_id", "id", required=True),
        F("observed_at", "datetime", required=True),
        F("injury_present", "bool", required=True),
        F("classification", "enum", required=True, enum=OBS_CLASSIFICATIONS),
        F("observed_stage", "enum", enum=OBS_STAGES, nullable=True),
        F("onset_at", "datetime", nullable=True),
        F("at_risk", "bool"),
    ])
    injury_present = body["injury_present"]
    observed_stage = body.get("observed_stage")
    classification = body["classification"]
    onset_at = body.get("onset_at")

    if injury_present:
        if observed_stage is None:
            bad_request("observed_stage is required when injury_present is true.")
    else:
        if observed_stage is not None:
            bad_request("observed_stage must be omitted when injury_present is false.")
        if classification != "NONE":
            bad_request("classification must be NONE when injury_present is false.")
    if classification == "HAPI":
        if onset_at is None:
            bad_request("onset_at is required when classification is HAPI.")
    elif onset_at is not None:
        bad_request("onset_at is only accepted when classification is HAPI.")

    survey_round = must("survey_rounds", body["survey_round_id"])
    unit = must("units", body["unit_id"])
    patient = must("patients", body["patient_id"])
    observer = must("woc_nurses", body["observer_nurse_id"])

    if unit["id"] != patient.get("unit_id"):
        fail("ERR_ENTITY_LINK_MISMATCH",
             "unit_id must equal the patient's unit_id.")
    if unit["id"] not in (survey_round.get("participating_unit_ids") or []):
        fail("ERR_ENTITY_LINK_MISMATCH",
             "unit_id must be a participating unit of this survey round.")
    if survey_round.get("status") != "OPEN":
        fail("ERR_SURVEY_ROUND_NOT_OPEN")
    if patient.get("status") != "ADMITTED":
        fail("ERR_PATIENT_DISCHARGED")
    if observer.get("certification_status") not in ("CANDIDATE", "CERTIFIED"):
        fail("ERR_NURSE_NOT_CERTIFIED")
    if not (survey_round.get("window_start") <= body["observed_at"]
            <= survey_round.get("window_end")):
        fail("ERR_OBSERVATION_OUTSIDE_WINDOW")
    if onset_at is not None and onset_at > body["observed_at"]:
        fail("ERR_OBSERVATION_OUTSIDE_WINDOW",
             "onset_at may not be after observed_at.")
    for existing in rows_of("survey_observations"):
        if existing.get("survey_round_id") == survey_round["id"] \
                and existing.get("patient_id") == patient["id"]:
            fail("ERR_DUPLICATE_OBSERVATION")

    observation = new_row(
        "obs",
        survey_round_id=survey_round["id"],
        unit_id=unit["id"],
        patient_id=patient["id"],
        observer_nurse_id=observer["id"],
        observed_at=body["observed_at"],
        injury_present=injury_present,
        observed_stage=observed_stage,
        classification=classification,
        onset_at=onset_at,
        at_risk=bool(body.get("at_risk", True)),
    )
    # PRD §2.4: "a survey observation is an immutable audit record and carries
    # only `id` and `created_at` — it has neither `updated_at` nor `version`".
    observation.pop("updated_at", None)
    observation.pop("version", None)
    insert("survey_observations", observation)
    survey_round["observation_count"] = int(survey_round.get("observation_count") or 0) + 1
    bump(survey_round)
    return ok(public(observation), 201)


@bp.get("/survey-observations")
def list_observations():
    authorize(*READ_ROLES)
    limit, offset = pagination()
    active = filters({
        "survey_round_id": None,
        "unit_id": None,
        "patient_id": None,
        "observer_nurse_id": None,
    })
    rows = chrono(apply_filters(rows_of("survey_observations"), active))
    page, total = paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


@bp.get("/survey-observations/<observation_id>")
def get_observation(observation_id):
    authorize(*READ_ROLES)
    return ok(public(must("survey_observations", observation_id)))
