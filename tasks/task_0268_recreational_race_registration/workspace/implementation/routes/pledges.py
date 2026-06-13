"""FundraisingPledge endpoints + transitions."""
from flask import Blueprint, request

from db import db, new_id
from errors import (err, ERR_RELATION_MISMATCH, ERR_INVALID_STATE,
                    ERR_NOT_RESOURCE_OWNER, ERR_NOT_FOUND)
from middleware import auth, require_role, get_json
from response import object_response
from services.store import stamp_new, serialize_generic, touch, paginate_and_respond
from services.validate import require_str, require_int, lookup

bp = Blueprint("pledges", __name__)


def _owner_check(user_id, role, owner_participant_id):
    if role == "Participant" and user_id != owner_participant_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Acting participant is not the resource owner")


@bp.route("/pledges", methods=["POST"])
def create_pledge():
    user_id, role = auth()
    require_role(role, {"Participant"})
    body = get_json()
    registration_id = require_str(body, "registration_id")
    reg = db.registrations.get(registration_id)
    if reg is None:
        raise err(ERR_NOT_FOUND, "Registration not found")
    # ownership of the targeted registration
    _owner_check(user_id, role, reg["participant_id"])

    donor_name = require_str(body, "donor_name")
    amount_cents = require_int(body, "amount_cents", minimum=1)

    # relationship: target registration must be CHARITY
    if reg["entry_type"] != "CHARITY":
        raise err(ERR_RELATION_MISMATCH, "Pledge target registration is not a CHARITY entry")

    pid = new_id()
    p = {
        "id": pid,
        "registration_id": registration_id,
        "donor_name": donor_name,
        "amount_cents": amount_cents,
        "status": "PLEDGED",
    }
    stamp_new(p)
    db.fundraising_pledges[pid] = p
    return object_response(serialize_generic(p), 201)


@bp.route("/pledges/<pledge_id>", methods=["GET"])
def get_pledge(pledge_id):
    user_id, role = auth()
    require_role(role, {"RaceDirector", "Participant"})
    p = lookup(db.fundraising_pledges, pledge_id, "FundraisingPledge")
    return object_response(serialize_generic(p), 200)


@bp.route("/pledges", methods=["GET"])
def list_pledges():
    user_id, role = auth()
    require_role(role, {"RaceDirector", "Participant"})
    items = list(db.fundraising_pledges.values())
    for f in ("registration_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [p for p in items if p.get(f) == v]
    return paginate_and_respond("pledge", items, request.args)


@bp.route("/pledges/<pledge_id>/settle", methods=["POST"])
def settle_pledge(pledge_id):
    user_id, role = auth()
    require_role(role, {"Participant"})
    p = lookup(db.fundraising_pledges, pledge_id, "FundraisingPledge")
    reg = db.registrations.get(p["registration_id"])
    _owner_check(user_id, role, reg["participant_id"] if reg else None)

    if p["status"] != "PLEDGED":
        raise err(ERR_INVALID_STATE, "Pledge must be PLEDGED to settle")
    # linked registration must be CHARITY and not CANCELLED
    if reg is None or reg["entry_type"] != "CHARITY" or reg["status"] == "CANCELLED":
        raise err(ERR_INVALID_STATE, "Linked registration is not a settleable CHARITY entry")

    p["status"] = "SETTLED"
    touch(p)
    return object_response(serialize_generic(p), 200)


@bp.route("/pledges/<pledge_id>/void", methods=["POST"])
def void_pledge(pledge_id):
    user_id, role = auth()
    require_role(role, {"Participant"})
    p = lookup(db.fundraising_pledges, pledge_id, "FundraisingPledge")
    reg = db.registrations.get(p["registration_id"])
    _owner_check(user_id, role, reg["participant_id"] if reg else None)

    if p["status"] not in ("PLEDGED", "SETTLED"):
        raise err(ERR_INVALID_STATE, "Pledge must be PLEDGED or SETTLED to void")

    p["status"] = "VOIDED"
    touch(p)
    return object_response(serialize_generic(p), 200)
