"""Field observations, the fine-tuning cascade and evaluation certification
(PRD section 3.10)."""

from flask import Blueprint

import auth
import calc
import cascades
import clock
import derive
import lookups
import response
import serializers
import validators
from auth import CERTIFYING_ENGINEER, FIELD_TECHNICIAN, SIGNAL_OPS_ADMIN
from db import base_row, db, touch
from errors import fail

bp = Blueprint("observations", __name__)

TOD_PERIODS = ("AM_PEAK", "MID_DAY", "PM_PEAK", "OFF_PEAK")
FINDING_CODES = (
    "QUEUE_SPILLBACK",
    "EARLY_RETURN_TO_GREEN",
    "PED_CALL_MISSED",
    "DETECTION_FAULT",
    "PROGRESSION_BREAK",
    "NONE",
)
RESOLUTIONS = ("ADDRESSED", "DISMISSED")


@bp.route("/signal-ops/field-observations", methods=["POST"])
@auth.roles(FIELD_TECHNICIAN)
def create_observation():
    data = validators.body()
    project_id = validators.req_id(data, "project_id")
    intersection_id = validators.req_id(data, "intersection_id")
    project = lookups.project(project_id)
    intersection = lookups.intersection(intersection_id)
    tod_period = validators.req_enum(data, "tod_period", TOD_PERIODS)
    observed_at = validators.req_ts(data, "observed_at")
    finding_code = validators.req_enum(data, "finding_code", FINDING_CODES)
    requires_adjustment = validators.opt_bool(data, "requires_adjustment", False)

    lookups.not_terminal(project)
    if project["status"] != "FIELD_TUNING":
        fail("ERR_PROJECT_NOT_IN_FIELD_TUNING")

    started_at = project.get("_field_tuning_started_at") or project["created_at"]
    if observed_at < started_at or observed_at > clock.now():
        fail("ERR_OBSERVATION_OUT_OF_WINDOW")

    # The round ceiling is checked before anything at all is written.
    if requires_adjustment and project["tuning_round"] + 1 > calc.MAX_TUNING_ROUNDS:
        fail("ERR_TUNING_ROUND_LIMIT")

    row = {
        "project_id": project["id"],
        "intersection_id": intersection["id"],
        "tod_period": tod_period,
        "observed_at": observed_at,
        "finding_code": finding_code,
        "requires_adjustment": requires_adjustment,
        "resolution_status": "OPEN",
        "observer_user_id": auth.user_id(),
    }
    row.update(base_row())
    db.observations[row["id"]] = row

    if requires_adjustment:
        cascades.fine_tuning_cascade(project, intersection["id"], tod_period)

    return response.created(serializers.field_observation(row))


@bp.route("/signal-ops/field-observations/<observation_id>", methods=["PATCH"])
@auth.roles(FIELD_TECHNICIAN, SIGNAL_OPS_ADMIN)
def update_observation(observation_id):
    row = lookups.observation(observation_id)
    data = validators.body()
    resolution_status = validators.req_enum(data, "resolution_status", RESOLUTIONS)
    if row["resolution_status"] != "OPEN":
        fail("ERR_OBSERVATION_NOT_OPEN")
    row["resolution_status"] = resolution_status
    touch(row)
    return response.ok(serializers.field_observation(row))


@bp.route("/signal-ops/performance-evaluations/<evaluation_id>/certify", methods=["POST"])
@auth.roles(CERTIFYING_ENGINEER)
def certify_evaluation(evaluation_id):
    evaluation = lookups.evaluation(evaluation_id)
    validators.body()
    if evaluation["status"] != "PROVISIONAL":
        fail("ERR_EVALUATION_NOT_PROVISIONAL")
    project = db.projects.get(evaluation["project_id"])
    if project is None or project["status"] != "EVALUATION":
        fail("ERR_PROJECT_NOT_IN_EVALUATION")
    cutoff = project.get("last_tuning_completed_at")
    if cutoff is None:
        fail("ERR_INVALID_REQUEST", "The project has no completed tuning phase.")

    runs = derive.runs_of_project(project["id"])
    before = [r for r in runs if r["study_role"] == "BEFORE"]
    after = [
        r for r in runs if r["study_role"] == "AFTER" and r["recorded_at"] >= cutoff
    ]
    if not after:
        fail("ERR_NO_AFTER_STUDY")
    if not before:
        fail("ERR_BEFORE_STUDY_INCOMPLETE")

    evaluation.update(calc.performance_metrics(before, after, weighted=True))
    evaluation["metric_variant"] = "CERTIFIED_WEIGHTED"
    evaluation["certified_by_user_id"] = auth.user_id()
    evaluation["status"] = "CERTIFIED"
    touch(evaluation)
    return response.ok(serializers.performance_evaluation(evaluation))
