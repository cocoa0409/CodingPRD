"""Energy surveys: DRAFT -> SUBMITTED -> APPROVED | REJECTED (resubmit) (PRD 3.2)."""

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import auth, paginate, ALL_ROLES
from response import ok, ok_list
from services import core

bp = Blueprint("energy_surveys", __name__)

_ENERGY_SOURCE_KEYS = ("source_type", "magnitude", "isolation_point", "dissipation_method")


@bp.route("/energy-surveys", methods=["POST"])
def create_survey():
    user_id, _ = auth(["AuthorizedEmployee"])
    body = core.body_json()
    machine_id = core.req_str(body, "machine_id")
    sources = core.req_array(body, "energy_sources", min_len=1,
                             required_keys=_ENERGY_SOURCE_KEYS)
    note = core.opt_str(body, "note")
    m = core.get_or_404("machines", machine_id, "Machine")
    sv = core.stamp_new({
        "id": core.new_id(),
        "machine_id": m["id"],
        "surveyed_by_employee_id": user_id,
        "energy_sources": sources,
        "isolation_point_count": len(sources),
        "note": note,
        "status": "DRAFT",
    })
    db.DB["energy_surveys"][sv["id"]] = sv
    return ok(core.survey_view(sv), 201)


@bp.route("/energy-surveys", methods=["GET"])
def list_surveys():
    auth(ALL_ROLES)
    machine_id = request.args.get("machine_id")
    surveyed_by = request.args.get("surveyed_by_employee_id")
    status = request.args.get("status")
    items = list(db.DB["energy_surveys"].values())
    if machine_id is not None:
        items = [s for s in items if s["machine_id"] == machine_id]
    if surveyed_by is not None:
        items = [s for s in items if s["surveyed_by_employee_id"] == surveyed_by]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items = core.sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([core.survey_view(s) for s in page], total, limit, offset)


@bp.route("/energy-surveys/<sid>", methods=["GET"])
def get_survey(sid):
    auth(ALL_ROLES)
    sv = core.get_or_404("energy_surveys", sid, "EnergySurvey")
    return ok(core.survey_view(sv))


@bp.route("/energy-surveys/<sid>/submit", methods=["POST"])
def submit_survey(sid):
    user_id, _ = auth(["AuthorizedEmployee"])
    sv = core.get_or_404("energy_surveys", sid, "EnergySurvey")
    # Ownership (pipeline stage 5): only the surveyor may submit / resubmit.
    if sv["surveyed_by_employee_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN", 403, "Only the surveying employee may submit")
    if sv["status"] not in ("DRAFT", "REJECTED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a DRAFT or REJECTED survey can be submitted")
    sv["status"] = "SUBMITTED"
    core.touch(sv)
    return ok(core.survey_view(sv))


@bp.route("/energy-surveys/<sid>/approve", methods=["POST"])
def approve_survey(sid):
    user_id, _ = auth(["EHSManager"])
    sv = core.get_or_404("energy_surveys", sid, "EnergySurvey")
    if sv["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a SUBMITTED survey can be approved")
    # Segregation of duties (stage 8): the approver must not be the surveyor.
    if sv["surveyed_by_employee_id"] == user_id:
        raise ApiError("ERR_SELF_APPROVAL_FORBIDDEN", 409,
                       "The surveyor may not approve their own survey")
    sv["status"] = "APPROVED"
    core.touch(sv)
    return ok(core.survey_view(sv))


@bp.route("/energy-surveys/<sid>/reject", methods=["POST"])
def reject_survey(sid):
    user_id, _ = auth(["EHSManager"])
    sv = core.get_or_404("energy_surveys", sid, "EnergySurvey")
    if sv["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a SUBMITTED survey can be rejected")
    if sv["surveyed_by_employee_id"] == user_id:
        raise ApiError("ERR_SELF_APPROVAL_FORBIDDEN", 409,
                       "The surveyor may not reject their own survey")
    sv["status"] = "REJECTED"
    core.touch(sv)
    return ok(core.survey_view(sv))
