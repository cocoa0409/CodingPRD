"""DischargeInstruction endpoints (PRD §3.5)."""
from flask import Blueprint

import clock
import serialize
from db import db, stamp_create
from errors import err
from middleware import authorize
from response import ok_object, ok_array
from util import add_days
from validation import get_json_body, parse_pagination, paginate, require_str
from routes.lookup import get_path

bp = Blueprint("discharge_instructions", __name__)

READ_ROLES = ["ClinicManager", "FrontDeskClerk", "Provider", "Patient"]


@bp.route("/visits/<vid>/discharge-instructions", methods=["POST"])
def create_discharge_instruction(vid):
    authorize(["Provider"])
    visit = get_path("visit", vid)
    body = get_json_body()
    require_str(body, "instructions_text")
    follow_up = body.get("follow_up_within_days", None)
    if follow_up is not None:
        if not isinstance(follow_up, int) or isinstance(follow_up, bool) or follow_up < 0:
            raise err("ERR_INVALID_REQUEST", "follow_up_within_days must be a non-negative integer")

    if follow_up is None:
        due_at = None
        status = "NONE"
    else:
        due_at = add_days(clock.now(), follow_up)
        status = "PENDING"

    instruction = stamp_create({
        "visit_id": visit["id"],
        "instructions_text": body["instructions_text"],
        "follow_up_within_days": follow_up,
        "follow_up_due_at": due_at,
        "follow_up_status": status,
    })
    db.discharge_instructions[instruction["id"]] = instruction
    return ok_object(serialize.discharge_instruction(instruction), 201)


@bp.route("/visits/<vid>/discharge-instructions", methods=["GET"])
def list_discharge_instructions(vid):
    authorize(READ_ROLES)
    visit = get_path("visit", vid)
    limit, offset = parse_pagination()
    items = [d for d in db.discharge_instructions.values() if d["visit_id"] == visit["id"]]
    items.sort(key=lambda d: (d["created_at"], d["id"]))
    page = paginate(items, limit, offset)
    return ok_array([serialize.discharge_instruction(d) for d in page], limit, offset, len(items))


@bp.route("/discharge-instructions/<did>", methods=["GET"])
def get_discharge_instruction(did):
    authorize(READ_ROLES)
    instruction = get_path("discharge_instruction", did)
    return ok_object(serialize.discharge_instruction(instruction))
