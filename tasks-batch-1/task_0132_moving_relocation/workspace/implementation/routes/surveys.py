"""InventorySurvey + SurveyItem routes (PRD §3.2).

cubic_feet rollup recomputed on every item append (no status filter). A survey
locks once an estimate is generated from it; locked surveys reject new items
(ERR_SURVEY_LOCKED).
"""
from flask import Blueprint, request

import db
from errors import err
from middleware import authenticate, require_roles
from response import object_response, array_response
from serialize import public, public_list
from services import common
from services import calculations

bp = Blueprint("surveys", __name__)

SURVEY_METHODS = {"IN_HOME", "VIRTUAL", "SELF_REPORTED"}


@bp.route("/surveys", methods=["POST"])
def create_survey():
    user_id, role = authenticate()
    require_roles(role, {"Estimator", "PlatformAdmin"})
    body = common.get_json_body()
    common.require_fields(body, ["move_job_id", "survey_method"])

    common.lookup_fk(db.move_jobs, body["move_job_id"])
    common.require_enum(body, "survey_method", SURVEY_METHODS)

    record = db.new_common({
        "move_job_id": body["move_job_id"],
        "survey_method": body["survey_method"],
        "total_cubic_feet": 0,
        "estimated_weight_lbs": 0,
        "locked": False,
    })
    db.surveys[record["id"]] = record
    return object_response(public(record), 201)


@bp.route("/surveys/<sid>", methods=["GET"])
def get_survey(sid):
    user_id, role = authenticate()
    require_roles(role, {"Estimator", "PlatformAdmin", "Customer", "Dispatcher"})
    record = common.lookup(db.surveys, sid)
    return object_response(public(record), 200)


@bp.route("/surveys", methods=["GET"])
def list_surveys():
    user_id, role = authenticate()
    require_roles(role, {"Estimator", "PlatformAdmin", "Customer", "Dispatcher"})
    limit, offset = common.parse_pagination()
    move_job_id = request.args.get("move_job_id")
    records = list(db.surveys.values())
    if move_job_id is not None:
        records = [r for r in records if r["move_job_id"] == move_job_id]
    page, total = common.paginate(records, limit, offset)
    return array_response(public_list(page), limit, offset, total, 200)


@bp.route("/surveys/<sid>/items", methods=["POST"])
def add_survey_item(sid):
    user_id, role = authenticate()
    require_roles(role, {"Estimator", "PlatformAdmin"})
    survey = common.lookup(db.surveys, sid)

    # Survey-lock guard (priority 8) before field-level checks (PRD §3.12).
    if survey["locked"]:
        raise err("ERR_SURVEY_LOCKED", "This survey is locked and cannot accept new items.")

    body = common.get_json_body()
    common.require_fields(body, ["label", "quantity", "cubic_feet_each"])
    common.require_int_field(body, "quantity", minimum=1)
    common.require_number_field(body, "cubic_feet_each", strictly_positive=True)

    item = db.new_line_item({
        "survey_id": sid,
        "label": body["label"],
        "quantity": body["quantity"],
        "cubic_feet_each": body["cubic_feet_each"],
    })
    db.survey_items[item["id"]] = item

    # Recompute rollup over ALL items of the survey (PRD §3.2).
    items = [it for it in db.survey_items.values() if it["survey_id"] == sid]
    total_num, weight, _exact = calculations.cubic_feet_rollup(items)
    survey["total_cubic_feet"] = total_num
    survey["estimated_weight_lbs"] = weight
    db.touch(survey)

    return object_response(public(item), 201)


@bp.route("/surveys/<sid>/items", methods=["GET"])
def list_survey_items(sid):
    user_id, role = authenticate()
    require_roles(role, {"Estimator", "PlatformAdmin", "Customer", "Dispatcher"})
    common.lookup(db.surveys, sid)
    limit, offset = common.parse_pagination()
    records = [it for it in db.survey_items.values() if it["survey_id"] == sid]
    page, total = common.paginate(records, limit, offset)
    return array_response(public_list(page), limit, offset, total, 200)
