from flask import Blueprint, request
from db import db
from middleware import require_user_context, require_role
from response import object_response, array_response
from services.common import (stamp_new, bump, public, get_json_body, require_str,
                             require_enum, paginate, sorted_by_creation)
from services.lookup import get_or_404
from errors import err

bp = Blueprint("participants", __name__)

PAY_TYPES = {"INSURANCE", "SELF_PAY", "GRANT"}


@bp.route("/participants", methods=["POST"])
def create_participant():
    _, role = require_user_context()
    require_role(role, {"ProgramManager", "ClinicalStaff"})
    body = get_json_body()
    full_name = require_str(body, "full_name")
    dob = require_str(body, "date_of_birth")
    _validate_date(dob)
    pay_type = require_enum(body, "pay_type", PAY_TYPES)
    insurance_member_id = body.get("insurance_member_id")
    grant_id = body.get("grant_id")
    if pay_type == "INSURANCE":
        if not isinstance(insurance_member_id, str) or not insurance_member_id:
            raise err("ERR_INVALID_REQUEST", "insurance_member_id required for INSURANCE")
    if pay_type == "GRANT":
        if not isinstance(grant_id, str) or not grant_id:
            raise err("ERR_INVALID_REQUEST", "grant_id required for GRANT")
        get_or_404("grants", grant_id)  # FK existence (priority 4)
    participant = stamp_new({
        "full_name": full_name, "date_of_birth": dob, "pay_type": pay_type,
        "insurance_member_id": insurance_member_id if pay_type == "INSURANCE" else None,
        "grant_id": grant_id if pay_type == "GRANT" else None,
        "no_show_strikes": 0, "status": "ACTIVE",
    })
    db.participants[participant["id"]] = participant
    return object_response(public(participant), 201)


def _validate_date(s):
    parts = s.split("-")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise err("ERR_INVALID_REQUEST", "date must be YYYY-MM-DD")
    try:
        from datetime import date
        date(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "invalid calendar date")


@bp.route("/participants", methods=["GET"])
def list_participants():
    _, role = require_user_context()
    require_role(role, {"ProgramManager", "ClinicalStaff", "PatientNavigator"})
    items = list(db.participants.values())
    for f in ("grant_id", "status"):
        val = request.args.get(f)
        if val is not None:
            items = [p for p in items if p.get(f) == val]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(items)
    return array_response([public(p) for p in page], limit, offset, total)


@bp.route("/participants/<rid>", methods=["GET"])
def get_participant(rid):
    _, role = require_user_context()
    require_role(role, {"ProgramManager", "ClinicalStaff", "PatientNavigator"})
    return object_response(public(get_or_404("participants", rid)), 200)


@bp.route("/participants/<rid>/reinstate", methods=["POST"])
def reinstate(rid):
    _, role = require_user_context()
    require_role(role, {"ProgramManager"})
    p = get_or_404("participants", rid)
    if p["status"] != "BLOCKED":
        raise err("ERR_INVALID_STATE", "Participant not BLOCKED")
    p["status"] = "ACTIVE"
    p["no_show_strikes"] = 0
    bump(p)
    return object_response(public(p), 200)
