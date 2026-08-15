from flask import Blueprint, request

import db
from db import new_entity, touch
from errors import ApiError, ERR_CHIP_CODE_TAKEN, ERR_CHIP_NOT_ASSIGNED
from middleware import endpoint
from response import ok
from serializers import ser_chip
from validators import get_body, get_or_404, list_page, v_enum, v_str

bp = Blueprint("chips", __name__)

_CHIP_READERS = ("RaceDirector", "RegistrationClerk", "TimingOperator")


@bp.post("/race-timing/chips")
@endpoint("RegistrationClerk")
def create_chip():
    body = get_body(("chip_code",))
    chip_code = v_str(body, "chip_code")
    if any(c["chip_code"] == chip_code for c in db.chips.values()):
        raise ApiError(ERR_CHIP_CODE_TAKEN, 409, "chip_code already exists in the fleet")
    chip = new_entity()
    chip.update(
        {"chip_code": chip_code, "status": "AVAILABLE", "current_registration_id": None}
    )
    db.chips[chip["id"]] = chip
    return ok(ser_chip(chip), 201)


@bp.get("/race-timing/chips/<chip_id>")
@endpoint(*_CHIP_READERS)
def get_chip(chip_id):
    return ok(ser_chip(get_or_404(db.chips, chip_id)))


@bp.get("/race-timing/chips")
@endpoint(*_CHIP_READERS)
def list_chips():
    items = list(db.chips.values())
    for param in ("status", "chip_code", "current_registration_id"):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c.get(param) == v]
    return list_page(items, ser_chip)


@bp.post("/race-timing/chips/<chip_id>/deassign")
@endpoint("RegistrationClerk")
def deassign_chip(chip_id):
    chip = get_or_404(db.chips, chip_id)
    body = get_body(("disposition",))
    disposition = v_enum(body, "disposition", ("RETURNED", "LOST"))
    if chip["status"] != "ASSIGNED":
        raise ApiError(ERR_CHIP_NOT_ASSIGNED, 409, "Chip is not ASSIGNED")
    reg = db.registrations.get(chip["current_registration_id"] or "")
    if disposition == "RETURNED":
        chip["status"] = "AVAILABLE"  # athlete stays CHECKED_IN
    else:
        chip["status"] = "LOST"  # terminal; athlete reverts CHECKED_IN -> CONFIRMED
    if reg is not None:
        changed = False
        if reg["chip_id"] == chip["id"]:
            reg["chip_id"] = None
            changed = True
        if disposition == "LOST" and reg["lifecycle_status"] == "CHECKED_IN":
            reg["lifecycle_status"] = "CONFIRMED"
            changed = True
        if changed:
            touch(reg)
    chip["current_registration_id"] = None
    touch(chip)
    return ok(ser_chip(chip))
