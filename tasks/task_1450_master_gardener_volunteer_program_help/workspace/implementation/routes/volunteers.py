"""Volunteer endpoints: list, get, withdraw, reactivate."""

from flask import request, Blueprint

import db
import util
from middleware import auth_context
from errors import raise_err
from response import success_object, success_list
from services import calculations as calc

bp = Blueprint("volunteers", __name__)

ALL_ROLES = ["ProgramCoordinator", "Volunteer", "Specialist"]
PC = ["ProgramCoordinator"]


def get_volunteer_or_404(volunteer_id):
    vol = db.volunteers.get(volunteer_id)
    if vol is None:
        raise_err("ERR_NOT_FOUND", "Volunteer not found")
    return vol


@bp.route("/volunteers", methods=["GET"])
def list_volunteers():
    auth_context(ALL_ROLES)
    items = list(db.volunteers.values())
    status = request.args.get("status")
    application_id = request.args.get("application_id")
    if status is not None:
        items = [v for v in items if v["status"] == status]
    if application_id is not None:
        items = [v for v in items if v["application_id"] == application_id]
    items = util.sort_created(items)
    limit, offset = util.paginate(items, request.args)
    return success_list(items[offset:offset + limit], len(items), limit, offset)


@bp.route("/volunteers/<volunteerId>", methods=["GET"])
def get_volunteer(volunteerId):
    auth_context(ALL_ROLES)
    vol = get_volunteer_or_404(volunteerId)
    # derived recognition fields reconciled on read
    calc.recompute_recognition(vol)
    return success_object(vol)


@bp.route("/volunteers/<volunteerId>/withdraw", methods=["POST"])
def withdraw_volunteer(volunteerId):
    user_id, role = auth_context(["ProgramCoordinator", "Volunteer"])
    vol = get_volunteer_or_404(volunteerId)
    if role == "Volunteer" and user_id != vol["id"]:
        raise_err("ERR_NOT_RESOURCE_OWNER", "Volunteers may only withdraw themselves")
    if vol["status"] not in ("TRAINEE", "ACTIVE", "INACTIVE"):
        raise_err("ERR_INVALID_REQUEST", "Volunteer is already in a terminal state")
    vol["status"] = "WITHDRAWN"
    util.touch(vol)
    calc.deactivation_cascade(vol)
    return success_object(vol)


@bp.route("/volunteers/<volunteerId>/reactivate", methods=["POST"])
def reactivate_volunteer(volunteerId):
    auth_context(PC)
    vol = get_volunteer_or_404(volunteerId)
    if vol["status"] != "INACTIVE":
        raise_err("ERR_VOLUNTEER_NOT_INACTIVE", "Reactivate requires status INACTIVE")
    open_cycles = [c for c in db.program_cycles.values() if c["status"] == "OPEN"]
    if not open_cycles:
        raise_err("ERR_NO_OPEN_CYCLE", "No OPEN cycle exists for reactivation")
    open_cycles.sort(key=lambda c: (c["start_date"],), reverse=True)
    # target: latest start_date, tie broken by created_at ASC
    max_start = max(c["start_date"] for c in open_cycles)
    tied = [c for c in open_cycles if c["start_date"] == max_start]
    tied.sort(key=lambda c: c["created_at"])
    target = tied[0]
    vol["status"] = "ACTIVE"
    util.touch(vol)
    calc.provision_record(vol["id"], target["id"])
    return success_object(vol)
