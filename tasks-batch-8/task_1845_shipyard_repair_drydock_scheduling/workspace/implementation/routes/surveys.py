"""Survey endpoints: scheduling against the surveyor's own calendar and
recording outcomes with deficiency discipline."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_OWNERSHIP_MISMATCH,
    ERR_SURVEYOR_SCHEDULE_CONFLICT,
    ERR_SURVEY_RESULT_INVALID,
)
from middleware import require_roles
from response import success_list, success_object
from services import project_ops
from services.project_ops import SURVEY_TYPES
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    optional_int,
    paginate,
    parse_iso8601,
    parse_pagination,
    require_enum,
    require_string,
    require_ts,
    sort_by_created_at,
)

bp = Blueprint("surveys", __name__)

READ_ROLES = (
    "YardAdmin",
    "ProjectManager",
    "CommercialApprover",
    "ShipownerRep",
    "ClassSurveyor",
    "EnvironmentalOfficer",
)


def get_survey_or_404(survey_id: str) -> dict:
    survey = db.surveys.get(survey_id)
    if survey is None:
        raise_err(ERR_NOT_FOUND, "Survey id does not exist")
    return survey


@bp.route("/v1/surveys", methods=["POST"])
@require_roles("ClassSurveyor")
def create_survey(_user_id: str, _role: str):
    body = get_json_body()
    # Rung 3: well-formedness.
    project_id = require_string(body, "project_id")
    survey_type = require_enum(body, "survey_type", SURVEY_TYPES)
    start_utc = require_ts(body, "scheduled_start_utc")
    end_utc = require_ts(body, "scheduled_end_utc")

    # Rung 4: the project exists.
    if project_id not in db.projects:
        raise_err(ERR_NOT_FOUND, "RepairProject id does not exist")

    start_dt = parse_iso8601(start_utc, "scheduled_start_utc")
    end_dt = parse_iso8601(end_utc, "scheduled_end_utc")

    # Rung 8: the window must be strictly positive (reported as 400).
    if not (end_dt > start_dt):
        raise_err(
            ERR_INVALID_REQUEST,
            "scheduled_end_utc must be strictly after scheduled_start_utc",
        )

    # Rung 9: closed-interval conflict against the surveyor's own SCHEDULED
    # surveys — touching endpoints count as overlap.
    for other in db.surveys.values():
        if other["surveyor_user_id"] != _user_id or other["status"] != "SCHEDULED":
            continue
        other_start = parse_iso8601(other["scheduled_start_utc"], "scheduled_start_utc")
        other_end = parse_iso8601(other["scheduled_end_utc"], "scheduled_end_utc")
        if start_dt <= other_end and other_start <= end_dt:
            raise_err(
                ERR_SURVEYOR_SCHEDULE_CONFLICT,
                "the surveyor already has a survey overlapping this interval",
            )

    survey = {
        "project_id": project_id,
        "survey_type": survey_type,
        "surveyor_user_id": _user_id,
        "scheduled_start_utc": start_utc,
        "scheduled_end_utc": end_utc,
        "result": None,
        "deficiency_count": None,
        "status": "SCHEDULED",
    }
    db.stamp_new(survey)
    db.surveys[survey["id"]] = survey
    return success_object(serialize(survey), 201)


@bp.route("/v1/surveys", methods=["GET"])
@require_roles(*READ_ROLES)
def list_surveys(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.surveys.values()))
    items = apply_filters(items, ["project_id", "surveyor_user_id", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/v1/surveys/<survey_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_survey(survey_id: str, _user_id: str, _role: str):
    return success_object(serialize(get_survey_or_404(survey_id)))


@bp.route("/v1/surveys/<survey_id>/record-result", methods=["POST"])
@require_roles("ClassSurveyor")
def record_result(survey_id: str, _user_id: str, _role: str):
    body = get_json_body()
    # Rung 3: well-formedness.
    result = require_enum(body, "result", {"PASSED", "FAILED"})
    deficiency_count = optional_int(body, "deficiency_count")

    # Rung 4: the survey exists.
    survey = get_survey_or_404(survey_id)
    # Rung 5: outcome recording is defined only from SCHEDULED.
    if survey["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "a result is already recorded for this survey")
    # Rung 6: only the booking surveyor records its outcome.
    if _user_id != survey["surveyor_user_id"]:
        raise_err(ERR_OWNERSHIP_MISMATCH, "caller is not the surveyor who booked this survey")
    # Rung 8: deficiency discipline on the outcome pair.
    if result == "PASSED":
        if deficiency_count is not None and deficiency_count != 0:
            raise_err(ERR_SURVEY_RESULT_INVALID, "PASSED requires deficiency_count omitted or 0")
    else:  # FAILED
        if deficiency_count is None or deficiency_count < 1:
            raise_err(ERR_SURVEY_RESULT_INVALID, "FAILED requires deficiency_count >= 1")

    survey["result"] = result
    survey["deficiency_count"] = deficiency_count
    survey["status"] = result
    db.touch(survey)

    # A recorded PASSED re-evaluates the project's completion gate.
    if result == "PASSED":
        project = db.projects[survey["project_id"]]
        if project_ops.try_auto_complete_project(project):
            db.touch(project)
    return success_object(serialize(survey))
