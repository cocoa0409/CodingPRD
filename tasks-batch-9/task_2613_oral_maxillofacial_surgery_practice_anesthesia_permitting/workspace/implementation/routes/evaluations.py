"""Pre-anesthesia evaluations: creation, signature and day-of verification."""
from flask import Blueprint

from db import clock_dt, clock_str, db, new_record, ordered, touch
from errors import ApiError
from middleware import actor_id, authorize
from routes.helpers import ALL_ROLES, scope_check, send, send_list
from services.domain import (EVALUATION_STATUSES, NPO_CLEARS_MINUTES_MIN,
                             NPO_SOLIDS_MINUTES_MIN, evaluations_of_case,
                             get_case, get_practice, path_row, referenced_row)
from services.risk import apply_final, apply_provisional
from timeutil import parse_date, whole_minutes
from validation import (q_enum, q_string, read_body, v_bool, v_enum, v_id,
                        v_instant, v_int, v_string)

bp = Blueprint("evaluations", __name__)

EVALUATOR_ROLE_TYPES = ("SURGEON", "ANESTHESIA_MONITOR")


@bp.post("/surgical-cases/<case_id>/pre-anesthesia-evaluations")
def create_evaluation(case_id):
    authorize("AnesthesiaCoordinator")
    case = path_row(db.cases, case_id)
    body = read_body(
        required=("evaluator_staff_id", "asa_class_recorded", "airway_class_recorded",
                  "expected_case_version"),
        optional=("comorbidity_count", "fasting_solids_last_at",
                  "fasting_clears_last_at", "escort_confirmed", "escort_name"),
    )
    evaluator_staff_id = v_id(body, "evaluator_staff_id")
    asa_class_recorded = v_int(body, "asa_class_recorded", minimum=1, maximum=4)
    airway_class_recorded = v_int(body, "airway_class_recorded", minimum=1, maximum=4)
    expected_case_version = v_int(body, "expected_case_version", minimum=0)
    comorbidity_count = v_int(body, "comorbidity_count", minimum=0, default=0)
    fasting_solids_last_at = v_instant(body, "fasting_solids_last_at", default=None)
    fasting_clears_last_at = v_instant(body, "fasting_clears_last_at", default=None)
    escort_confirmed = v_bool(body, "escort_confirmed", default=False)
    escort_name = v_string(body, "escort_name", min_len=1, max_len=120, default=None)

    evaluator = referenced_row(db.staff, evaluator_staff_id)
    scope_check(evaluator["practice_id"], case["practice_id"])
    if evaluator["role_type"] not in EVALUATOR_ROLE_TYPES:
        raise ApiError("ERR_INVALID_FIELD_VALUE",
                       "Field 'evaluator_staff_id' must reference a SURGEON or ANESTHESIA_MONITOR.")
    if int(case["version"]) != expected_case_version:
        raise ApiError("ERR_STALE_CASE_VERSION")

    if not escort_confirmed:
        escort_name = None

    evaluation = new_record({
        "case_id": case["id"],
        "evaluator_staff_id": evaluator_staff_id,
        "asa_class_recorded": asa_class_recorded,
        "airway_class_recorded": airway_class_recorded,
        "comorbidity_count": comorbidity_count,
        "status": "DRAFT",
        "provisional_risk_score": None,
        "final_risk_score": None,
        "risk_band": None,
        "fasting_solids_last_at": fasting_solids_last_at,
        "fasting_clears_last_at": fasting_clears_last_at,
        "npo_solids_minutes": None,
        "npo_clears_minutes": None,
        "escort_confirmed": escort_confirmed,
        "escort_name": escort_name,
        "signed_at": None,
        "verified_at": None,
    })
    apply_provisional(evaluation, case)
    db.evaluations[evaluation["id"]] = evaluation

    superseded = False
    for prior in evaluations_of_case(case["id"]):
        if prior["id"] == evaluation["id"]:
            continue
        if prior["status"] in ("SIGNED", "VERIFIED"):
            prior["status"] = "SUPERSEDED"
            touch(prior)
            superseded = True
    if superseded:
        case["clearance_status"] = "NOT_EVALUATED"
        touch(case)
    return send(evaluation, 201)


@bp.get("/pre-anesthesia-evaluations/<evaluation_id>")
def read_evaluation(evaluation_id):
    authorize(*ALL_ROLES)
    return send(path_row(db.evaluations, evaluation_id))


@bp.get("/pre-anesthesia-evaluations")
def list_evaluations():
    authorize(*ALL_ROLES)
    case_id = q_string("case_id")
    evaluator_staff_id = q_string("evaluator_staff_id")
    status = q_enum("status", EVALUATION_STATUSES)
    rows = ordered([e for e in db.evaluations.values()
                    if (case_id is None or e["case_id"] == case_id)
                    and (evaluator_staff_id is None or e["evaluator_staff_id"] == evaluator_staff_id)
                    and (status is None or e["status"] == status)])
    return send_list(rows)


@bp.post("/pre-anesthesia-evaluations/<evaluation_id>/sign")
def sign_evaluation(evaluation_id):
    authorize("AnesthesiaCoordinator")
    evaluation = path_row(db.evaluations, evaluation_id)
    case = get_case(evaluation["case_id"])

    if actor_id() != evaluation["evaluator_staff_id"]:
        raise ApiError("ERR_ACTOR_NOT_ASSIGNED")
    if evaluation["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if case is None or case["scheduling_status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    apply_provisional(evaluation, case)
    evaluation["signed_at"] = clock_str()
    evaluation["status"] = "SIGNED"
    touch(evaluation)
    case["clearance_status"] = "EVALUATED"
    touch(case)
    return send(evaluation)


@bp.post("/pre-anesthesia-evaluations/<evaluation_id>/day-of-verification")
def verify_evaluation(evaluation_id):
    authorize("AnesthesiaCoordinator")
    evaluation = path_row(db.evaluations, evaluation_id)
    body = read_body(
        required=("intent", "fasting_solids_last_at", "fasting_clears_last_at",
                  "escort_confirmed"),
        optional=("escort_name",),
    )
    intent = v_enum(body, "intent", ("CLEAR", "DEFER"))
    fasting_solids_last_at = v_instant(body, "fasting_solids_last_at")
    fasting_clears_last_at = v_instant(body, "fasting_clears_last_at")
    escort_confirmed = v_bool(body, "escort_confirmed")
    escort_name = v_string(body, "escort_name", min_len=1, max_len=120, default=None)
    case = get_case(evaluation["case_id"])

    if case is not None and actor_id() in (evaluation["evaluator_staff_id"],
                                           case["primary_surgeon_id"]):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if evaluation["status"] != "SIGNED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if case is None or case["scheduling_status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    if not escort_confirmed:
        escort_name = None
    now = clock_dt()
    evaluation["fasting_solids_last_at"] = fasting_solids_last_at
    evaluation["fasting_clears_last_at"] = fasting_clears_last_at
    evaluation["escort_confirmed"] = escort_confirmed
    evaluation["escort_name"] = escort_name
    evaluation["npo_solids_minutes"] = whole_minutes(parse_date(fasting_solids_last_at), now)
    evaluation["npo_clears_minutes"] = whole_minutes(parse_date(fasting_clears_last_at), now)
    practice = get_practice(case["practice_id"])
    apply_final(evaluation, case, practice)

    sedated = case["planned_anesthesia_level"] != "LOCAL_ONLY"
    if intent == "CLEAR":
        try:
            if sedated and (int(evaluation["npo_solids_minutes"]) < NPO_SOLIDS_MINUTES_MIN
                            or int(evaluation["npo_clears_minutes"]) < NPO_CLEARS_MINUTES_MIN):
                raise ApiError("ERR_FASTING_REQUIREMENT_UNMET")
            if sedated and (not escort_confirmed or not escort_name):
                raise ApiError("ERR_ESCORT_REQUIRED")
            if evaluation["risk_band"] == "PROHIBITIVE":
                raise ApiError("ERR_RISK_BAND_PROHIBITIVE")
        except ApiError:
            # The published score must survive a rejected attempt (PRD 3.5).
            touch(evaluation)
            raise

    evaluation["status"] = "VERIFIED"
    evaluation["verified_at"] = clock_str()
    touch(evaluation)
    case["clearance_status"] = "CLEARED" if intent == "CLEAR" else "DEFERRED"
    touch(case)
    return send(evaluation)
