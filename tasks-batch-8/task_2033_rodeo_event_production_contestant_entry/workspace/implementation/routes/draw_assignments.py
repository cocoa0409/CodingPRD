"""DrawAssignment endpoints: list, get, re-ride (PRD 3.5)."""
from flask import Blueprint, request

from db import DB
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import (
    MAX_OUTS_PER_RODEO,
    get_or_404,
    ser,
    sorted_created,
    touch,
)
from util import body, pagination_args, required

bp = Blueprint("draw_assignments", __name__, url_prefix="/api")


@bp.get("/draw-assignments")
def list_draw_assignments():
    auth(ALL_ROLES)
    entry_id = request.args.get("entry_id")
    rodeo_event_id = request.args.get("rodeo_event_id")
    performance_id = request.args.get("performance_id")
    animal_id = request.args.get("animal_id")
    status = request.args.get("status")
    items = DB["draw_assignments"].values()
    if entry_id is not None:
        items = [a for a in items if a["entry_id"] == entry_id]
    if rodeo_event_id is not None:
        items = [a for a in items if a["rodeo_event_id"] == rodeo_event_id]
    if performance_id is not None:
        items = [a for a in items if a["performance_id"] == performance_id]
    if animal_id is not None:
        items = [a for a in items if a["animal_id"] == animal_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items = sorted_created(items)
    limit, offset = pagination_args()
    return ok_list(
        [ser(a) for a in items[offset : offset + limit]], len(items), limit, offset
    )


@bp.get("/draw-assignments/<draw_assignment_id>")
def get_draw_assignment(draw_assignment_id):
    auth(ALL_ROLES)
    return ok(ser(get_or_404("draw_assignments", draw_assignment_id)))


@bp.post("/draw-assignments/<draw_assignment_id>/reride")
def reride(draw_assignment_id):
    auth(["CommitteeAdmin"])
    assignment = get_or_404("draw_assignments", draw_assignment_id)
    data = body()
    animal_id = data.get("animal_id")
    if animal_id is not None:
        get_or_404("stock_animals", animal_id)
    if not isinstance(animal_id, str):
        raise ApiError("ERR_VALIDATION", 400, "Missing required field: animal_id")
    event = DB["rodeo_events"][assignment["rodeo_event_id"]]
    if event["discipline"] != "ROUGH_STOCK":
        raise ApiError(
            "ERR_VALIDATION", 400, "Re-ride applies only to rough-stock assignments"
        )
    if assignment["status"] != "PENDING":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Re-ride is not valid from status {assignment['status']}",
        )
    animal = DB["stock_animals"][animal_id]
    if (
        animal["status"] != "AVAILABLE"
        or animal["welfare_out_count"] >= MAX_OUTS_PER_RODEO
        or animal["event_code"] != event["event_code"]
    ):
        raise ApiError(
            "ERR_ANIMAL_NOT_ELIGIBLE",
            409,
            "Animal is not AVAILABLE, is over the welfare limit, or is slated "
            "for a different event",
        )
    contract = DB["stock_contracts"][animal["contract_id"]]
    if contract["status"] != "ACTIVE":
        raise ApiError(
            "ERR_CONTRACT_NOT_ACTIVE", 409, "The animal's stock contract is not ACTIVE"
        )
    old_animal = (
        DB["stock_animals"].get(assignment["animal_id"])
        if assignment["animal_id"]
        else None
    )
    if old_animal is not None and old_animal["status"] == "DRAWN":
        old_animal["status"] = "AVAILABLE"
        touch(old_animal)
    animal["status"] = "DRAWN"
    touch(animal)
    assignment["animal_id"] = animal_id
    touch(assignment)
    return ok(ser(assignment))
