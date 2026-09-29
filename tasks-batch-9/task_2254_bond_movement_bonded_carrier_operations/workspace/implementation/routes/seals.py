"""The seal chain of custody (PRD 3.3)."""
from flask import Blueprint

from db import db, new_record, touch
from errors import ApiError
from middleware import require
from response import ok
from services import domain
import validate as v

bp = Blueprint("seals", __name__)

EVENT_TYPES = ("APPLIED", "VERIFIED_INTACT", "REPLACED",
               "BROKEN_AUTHORIZED", "BROKEN_UNAUTHORIZED")

DEAD_TRANSIT = ("CLOSED", "CANCELLED")
DEAD_CUSTODY = ("RELEASED", "GENERAL_ORDER")


@bp.route("/in-bond/seal-events", methods=["POST"])
def record_seal_event():
    user_id, role = require("BondedCarrier", "CBPOfficer")

    # Band 3 - a carrier may only touch its own movement.
    peeked = v.peek_body().get("movement_id")
    if role == "BondedCarrier" and isinstance(peeked, str):
        target = db.movements.get(peeked)
        if target is not None and target["carrier_id"] != user_id:
            raise ApiError("ERR_NOT_MOVEMENT_CARRIER")

    body = v.get_body()
    movement_id = v.req_str(body, "movement_id")
    event_type = v.req_enum(body, "event_type", EVENT_TYPES)
    seal_number = v.req_str(body, "seal_number")
    port_code = v.req_str(body, "port_code")
    if len(port_code) != 4 or not port_code.isdigit():
        raise ApiError("ERR_INVALID_REQUEST")

    movement = db.movements.get(movement_id)
    if movement is None:
        raise ApiError("ERR_MOVEMENT_NOT_FOUND")
    port = domain.port_by_code(port_code)
    if port is None:
        raise ApiError("ERR_INVALID_REQUEST")

    if role == "BondedCarrier" and movement["carrier_id"] != user_id:
        raise ApiError("ERR_NOT_MOVEMENT_CARRIER")

    # Band 9 - the movement must still be alive and in customs custody.
    if movement["transit_status"] in DEAD_TRANSIT:
        raise ApiError("ERR_MOVEMENT_INVALID_STATE")
    if movement["custody_status"] in DEAD_CUSTODY:
        raise ApiError("ERR_MOVEMENT_INVALID_STATE")

    # Band 11 - only APPLIED may be recorded before a seal exists.
    if movement["seal_number"] is None and event_type != "APPLIED":
        raise ApiError("ERR_SEAL_NOT_APPLIED")

    changed = False
    if event_type == "APPLIED":
        if movement["seal_number"] != seal_number:
            movement["seal_number"] = seal_number
            changed = True
        if movement["seal_intact"] is not True:
            movement["seal_intact"] = True
            changed = True
    elif event_type == "REPLACED":
        if movement["seal_number"] != seal_number:
            movement["seal_number"] = seal_number
            changed = True
        if movement["seal_intact"] is not True:
            movement["seal_intact"] = True
            changed = True
    elif event_type in ("BROKEN_AUTHORIZED", "BROKEN_UNAUTHORIZED"):
        if movement["seal_intact"] is not False:
            movement["seal_intact"] = False
            changed = True
    # VERIFIED_INTACT leaves seal_intact exactly as it was.

    event = new_record(full=False)
    event.update({
        "movement_id": movement["id"],
        "seal_number": seal_number,
        "event_type": event_type,
        "port_code": port_code,
        "recorded_by_user_id": user_id,
        "occurred_at": db.now,
        "resulting_seal_intact": movement["seal_intact"],
    })
    db.seal_events[event["id"]] = event

    if event_type == "BROKEN_UNAUTHORIZED":
        hold = new_record()
        hold.update({
            "movement_id": movement["id"],
            "port_id": port["id"],
            "hold_type": "SEAL_DISCREPANCY",
            "status": "OPEN",
            "scheduled_start": None,
            "scheduled_end": None,
            "reason_code": "SEAL_DISCREPANCY",
            "placed_by_user_id": "SYSTEM",
            "released_at": None,
            "findings_code": None,
            "discrepancy_pieces": 0,
            "created_by_system": True,
        })
        db.holds[hold["id"]] = hold
        if movement["custody_status"] == "BONDED":
            movement["custody_status"] = "EXAM_HOLD"
            changed = True
        if domain.apply_go_grace(movement):
            changed = True
        domain.recompute_port(port)

    if changed:
        touch(movement)
    return ok(domain.seal_event_json(event), 201)
