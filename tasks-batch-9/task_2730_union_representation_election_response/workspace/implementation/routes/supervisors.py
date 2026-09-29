"""Supervisor registration, lawful-communication training and prohibited-conduct findings."""

from flask import Blueprint

import auth
import calc
import clockutil
import gates
import store
import validate
from errors import ApiError
from routes import common

bp = Blueprint("supervisors", __name__)

BASE = "/labor-relations/supervisors"
LIST_ROLES = (auth.DIRECTOR, auth.ANALYST, auth.COUNSEL, auth.TRAINER, auth.BOARD)
READ_ROLES = (auth.DIRECTOR, auth.COUNSEL, auth.TRAINER, auth.SUPERVISOR, auth.BOARD)


@bp.route(BASE, methods=["POST"])
@auth.endpoint([auth.TRAINER, auth.DIRECTOR])
def create_supervisor(user_id, role):
    schema = validate.Schema(validate.body())
    petition_id = schema.reference("petition_id")
    full_name = schema.string("full_name")
    job_title = schema.string("job_title")
    span_of_control = schema.integer("span_of_control", minimum=0)
    has_hire_fire_authority = schema.boolean("has_hire_fire_authority",
                                             required=False, default=False)

    gates.must_exist("petitions", petition_id)
    for existing in store.supervisors_of(petition_id):
        if existing["full_name"] == full_name and existing["job_title"] == job_title:
            raise ApiError("ERR_DUPLICATE_SUPERVISOR",
                           "That supervisor is already registered on this case.")

    row = store.insert("supervisors", {
        "petition_id": petition_id,
        "full_name": full_name,
        "job_title": job_title,
        "span_of_control": span_of_control,
        "has_hire_fire_authority": has_hire_fire_authority,
        "training_status": "UNTRAINED",
        "modules_completed": None,
        "quiz_score": None,
        "training_attempt_count": 0,
        "certified_at": None,
        "violation_count": 0,
        "last_violation_code": None,
    })
    return common.one_created(row)


@bp.route(BASE, methods=["GET"])
@auth.endpoint(LIST_ROLES)
def list_supervisors(user_id, role):
    petition_id = validate.query_string("petition_id")
    training_status = validate.query_enum("training_status", common.TRAINING_STATUSES)
    rows = store.ordered("supervisors")
    if petition_id is not None:
        rows = [r for r in rows if r["petition_id"] == petition_id]
    if training_status is not None:
        rows = [r for r in rows if r["training_status"] == training_status]
    return common.list_response(rows)


@bp.route(BASE + "/<sid>", methods=["GET"])
@auth.endpoint(READ_ROLES)
def read_supervisor(user_id, role, sid):
    # Self-scoped identity (step 3) precedes path existence (step 6).
    if role == auth.SUPERVISOR and user_id != sid:
        raise ApiError("ERR_SUPERVISOR_IDENTITY_MISMATCH",
                       "A PlantSupervisor may only read their own record.")
    return common.one(gates.must_exist("supervisors", sid))


@bp.route(BASE + "/<sid>/train", methods=["POST"])
@auth.endpoint([auth.TRAINER])
def train_supervisor(user_id, role, sid):
    schema = validate.Schema(validate.body())
    modules_completed = schema.string_list("modules_completed")
    quiz_score = schema.integer("quiz_score", minimum=0, maximum=100)
    supervisor = gates.must_exist("supervisors", sid)

    supervisor["training_attempt_count"] += 1
    supervisor["modules_completed"] = modules_completed
    supervisor["quiz_score"] = quiz_score
    has_all_modules = all(code in modules_completed
                          for code in calc.REQUIRED_TRAINING_MODULES)
    if has_all_modules and quiz_score >= calc.TRAINING_PASS_SCORE:
        supervisor["training_status"] = "TRAINED"
        supervisor["certified_at"] = clockutil.now_dt_str()
    store.touch(supervisor)
    return common.one(supervisor)


@bp.route(BASE + "/<sid>/record-violation", methods=["POST"])
@auth.endpoint([auth.COUNSEL])
def record_violation(user_id, role, sid):
    schema = validate.Schema(validate.body())
    violation_code = schema.enum("violation_code", common.VIOLATION_CODES)
    substantiated = schema.boolean("substantiated")
    supervisor = gates.must_exist("supervisors", sid)

    if not substantiated:
        return common.one(supervisor)

    petition = store.petition(supervisor["petition_id"])
    supervisor["violation_count"] += 1
    supervisor["last_violation_code"] = violation_code
    was_trained = supervisor["training_status"] == "TRAINED"
    if was_trained:
        supervisor["certified_at"] = None
        supervisor["training_status"] = "UNTRAINED"
    store.touch(supervisor)
    if was_trained:
        gates.presenter_decertification_cascade(supervisor, petition)
    return common.one(supervisor)
