"""TransferRequest endpoints + transitions."""
from flask import Blueprint, request

from db import db, new_id
from errors import (err, ERR_INVALID_STATE, ERR_NOT_RESOURCE_OWNER, ERR_NOT_FOUND,
                    ERR_REGISTRATION_CLOSED)
from middleware import auth, require_role, get_json
from response import object_response
from services.store import stamp_new, serialize_generic, touch, paginate_and_respond
from services.validate import require_str, lookup

bp = Blueprint("transfers", __name__)


@bp.route("/transfer-requests", methods=["POST"])
def create_transfer():
    user_id, role = auth()
    require_role(role, {"Participant"})
    body = get_json()
    registration_id = require_str(body, "registration_id")
    reg = db.registrations.get(registration_id)
    if reg is None:
        raise err(ERR_NOT_FOUND, "Registration not found")
    to_participant_id = require_str(body, "to_participant_id")
    to_p = db.participants.get(to_participant_id)
    if to_p is None:
        raise err(ERR_NOT_FOUND, "to_participant not found")

    # proposer must own the registration
    if role == "Participant" and user_id != reg["participant_id"]:
        raise err(ERR_NOT_RESOURCE_OWNER, "Only the current registrant may propose a transfer")

    # registration must be CONFIRMED to propose a transfer
    if reg["status"] != "CONFIRMED":
        raise err(ERR_INVALID_STATE, "Registration must be CONFIRMED to propose a transfer")

    tid = new_id()
    t = {
        "id": tid,
        "registration_id": registration_id,
        "from_participant_id": reg["participant_id"],
        "to_participant_id": to_participant_id,
        "status": "PROPOSED",
    }
    stamp_new(t)
    db.transfer_requests[tid] = t
    return object_response(serialize_generic(t), 201)


@bp.route("/transfer-requests/<transfer_request_id>", methods=["GET"])
def get_transfer(transfer_request_id):
    user_id, role = auth()
    require_role(role, {"RaceDirector", "Participant"})
    t = lookup(db.transfer_requests, transfer_request_id, "TransferRequest")
    return object_response(serialize_generic(t), 200)


@bp.route("/transfer-requests", methods=["GET"])
def list_transfers():
    user_id, role = auth()
    require_role(role, {"RaceDirector", "Participant"})
    items = list(db.transfer_requests.values())
    for f in ("registration_id", "from_participant_id", "to_participant_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [t for t in items if t.get(f) == v]
    return paginate_and_respond("transfer", items, request.args)


@bp.route("/transfer-requests/<transfer_request_id>/accept", methods=["POST"])
def accept_transfer(transfer_request_id):
    user_id, role = auth()
    require_role(role, {"Participant"})
    t = lookup(db.transfer_requests, transfer_request_id, "TransferRequest")
    # accept requires acting participant == to_participant_id
    if role == "Participant" and user_id != t["to_participant_id"]:
        raise err(ERR_NOT_RESOURCE_OWNER, "Only the recipient may accept the transfer")

    if t["status"] != "PROPOSED":
        raise err(ERR_INVALID_STATE, "Transfer must be PROPOSED to accept")

    reg = db.registrations.get(t["registration_id"])
    if reg is None:
        raise err(ERR_NOT_FOUND, "Registration not found")
    if reg["status"] != "CONFIRMED":
        raise err(ERR_INVALID_STATE, "Linked registration must be CONFIRMED")
    event = db.events.get(reg["event_id"])
    if event is None or event["status"] != "OPEN":
        raise err(ERR_REGISTRATION_CLOSED, "Owning event is not OPEN")

    # create a new CONFIRMED registration for the recipient, slot carries over
    new_rid = new_id()
    new_reg = {
        "id": new_rid,
        "event_id": reg["event_id"],
        "distance_id": reg["distance_id"],
        "wave_id": reg["wave_id"],
        "participant_id": t["to_participant_id"],
        "entry_type": "STANDARD",
        "party_size": 1,
        "promo_code": None,
        "qualifying_time_seconds": reg["qualifying_time_seconds"],
        "fundraising_minimum_cents": 0,
        "status": "CONFIRMED",
        "amount_due_cents": 0,
        "amount_paid_cents": 0,
        "processing_fee_cents": 0,
        "refund_cents": 0,
        "deferred_to_registration_id": None,
        "deferral_credit_cents": 0,
    }
    stamp_new(new_reg)
    db.registrations[new_rid] = new_reg

    reg["status"] = "TRANSFERRED"
    touch(reg)
    t["status"] = "ACCEPTED"
    touch(t)

    # slot moves not freed: confirmed_count unchanged but bump Distance.version
    distance = db.distances.get(reg["distance_id"])
    if distance is not None:
        touch(distance)

    return object_response(serialize_generic(t), 200)


@bp.route("/transfer-requests/<transfer_request_id>/reject", methods=["POST"])
def reject_transfer(transfer_request_id):
    user_id, role = auth()
    require_role(role, {"Participant"})
    t = lookup(db.transfer_requests, transfer_request_id, "TransferRequest")
    if role == "Participant" and user_id != t["to_participant_id"]:
        raise err(ERR_NOT_RESOURCE_OWNER, "Only the recipient may reject the transfer")

    if t["status"] != "PROPOSED":
        raise err(ERR_INVALID_STATE, "Transfer must be PROPOSED to reject")

    t["status"] = "REJECTED"
    touch(t)
    return object_response(serialize_generic(t), 200)


@bp.route("/transfer-requests/<transfer_request_id>/cancel", methods=["POST"])
def cancel_transfer(transfer_request_id):
    user_id, role = auth()
    require_role(role, {"Participant"})
    t = lookup(db.transfer_requests, transfer_request_id, "TransferRequest")
    if role == "Participant" and user_id != t["from_participant_id"]:
        raise err(ERR_NOT_RESOURCE_OWNER, "Only the proposer may cancel the transfer")

    if t["status"] != "PROPOSED":
        raise err(ERR_INVALID_STATE, "Transfer must be PROPOSED to cancel")

    t["status"] = "CANCELLED"
    touch(t)
    return object_response(serialize_generic(t), 200)
