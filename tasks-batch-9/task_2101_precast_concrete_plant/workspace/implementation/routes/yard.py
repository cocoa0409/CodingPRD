"""The storage yard: placement, pull and restack (PRD 3.7)."""
from decimal import Decimal

from flask import Blueprint

import auth
import calc
import cascade
import constants
import db
import errors
import lookup
import response
import serialize
import validation

bp = Blueprint("yard", __name__)


@bp.post("/yard-placements")
def create_placement():
    auth.require(constants.ROLE_YARD_FOREMAN)
    body = validation.get_body()
    piece_id = validation.req_id(body, "piece_id")
    slot_id = validation.req_id(body, "yard_slot_id")
    stack_level = validation.req_int(body, "stack_level", minimum=1)
    expected_version = validation.req_int(body, "expected_yard_slot_version")

    piece = lookup.piece(piece_id)
    slot = lookup.yard_slot(slot_id)

    if expected_version != slot["version"]:
        errors.fail(errors.ERR_STALE_YARD_SLOT_VERSION,
                    "expected_yard_slot_version does not match the slot's version.")
    if piece["production_status"] != "STRIPPED":
        errors.fail(errors.ERR_PIECE_INVALID_STATE,
                    "Only a STRIPPED piece may be stored in the yard.")
    if calc.slot_status(slot) == "BLOCKED":
        errors.fail(errors.ERR_PLANT_RESOURCE_UNAVAILABLE, "The yard slot is BLOCKED.")

    weight, stacked = calc.slot_occupancy(slot)
    if weight + Decimal(piece["weight_lb"]) > Decimal(slot["capacity_weight_lb"]):
        errors.fail(errors.ERR_YARD_SLOT_CAPACITY_EXCEEDED,
                    "The slot cannot carry this piece's weight.")
    if stacked + 1 > slot["max_stack_count"]:
        errors.fail(errors.ERR_YARD_STACK_LIMIT_EXCEEDED,
                    "The slot has no stack capacity left.")

    row = db.new_row(db.store.yard_placements, {
        "piece_id": piece_id,
        "yard_slot_id": slot_id,
        "stack_level": stack_level,
        "placed_at": db.store.now_iso(),
        "released_at": None,
        "release_reason": None,
        "status": "ACTIVE",
    })
    db.mark_fresh(row)

    piece["production_status"] = "YARDED"
    db.touch(piece)
    db.touch(slot)
    return response.object_response(serialize.yard_placement(row), 201)


@bp.post("/yard-placements/<placement_id>/pull")
def pull_placement(placement_id):
    auth.require(constants.ROLE_YARD_FOREMAN)
    placement = lookup.yard_placement(placement_id)
    body = validation.get_body()
    reason = validation.req_enum(body, "release_reason", constants.RELEASE_REASONS)

    if placement["status"] != "ACTIVE":
        errors.fail(errors.ERR_YARD_PLACEMENT_INVALID_STATE,
                    "The placement has already been released.")

    cascade.release_placement(placement, reason)

    piece = db.store.pieces.get(placement["piece_id"])
    if piece is not None and piece["production_status"] == "YARDED":
        if reason == "RESTACK":
            piece["production_status"] = "STRIPPED"
            db.touch(piece)
        elif reason == "LOAD":
            piece["production_status"] = "LOADED"
            db.touch(piece)
        elif reason == "SCRAP":
            piece["production_status"] = "SCRAPPED"
            db.touch(piece)
            cascade.touch_project_of(piece)
    return response.object_response(serialize.yard_placement(placement), 200)
