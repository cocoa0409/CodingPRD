"""Contestant endpoints: register, list, get, standing updates (PRD 3.2)."""
from flask import Blueprint, request

from db import DB, new_id
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import (
    get_or_404,
    ser,
    sorted_created,
    stamp,
    suspend_contestant_cascade,
    touch,
)
from util import as_enum, as_str, body, pagination_args, required

bp = Blueprint("contestants", __name__, url_prefix="/api")


@bp.post("/contestants")
def create_contestant():
    auth(["CommitteeAdmin", "EntryOffice"])
    data = body()
    card_number = as_str(required(data, "card_number"), "card_number")
    full_name = as_str(required(data, "full_name"), "full_name")
    for c in DB["contestants"].values():
        if c["card_number"] == card_number:
            raise ApiError(
                "ERR_DUPLICATE_CARD", 409, "card_number already registered"
            )
    rec = {
        "id": new_id(),
        "card_number": card_number,
        "full_name": full_name,
        "status": "GOOD_STANDING",
    }
    stamp(rec)
    DB["contestants"][rec["id"]] = rec
    return ok(ser(rec), status=201)


@bp.get("/contestants")
def list_contestants():
    auth(ALL_ROLES)
    card_number = request.args.get("card_number")
    status = request.args.get("status")
    items = DB["contestants"].values()
    if card_number is not None:
        items = [c for c in items if c["card_number"] == card_number]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = sorted_created(items)
    limit, offset = pagination_args()
    return ok_list(
        [ser(c) for c in items[offset : offset + limit]], len(items), limit, offset
    )


@bp.get("/contestants/<contestant_id>")
def get_contestant(contestant_id):
    auth(ALL_ROLES)
    return ok(ser(get_or_404("contestants", contestant_id)))


@bp.patch("/contestants/<contestant_id>")
def patch_contestant(contestant_id):
    auth(["CommitteeAdmin"])
    contestant = get_or_404("contestants", contestant_id)
    data = body()
    status = as_enum(
        required(data, "status"), "status", {"GOOD_STANDING", "SUSPENDED"}
    )
    if status == contestant["status"]:
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Contestant is already {status}",
        )
    if status == "SUSPENDED":
        suspend_contestant_cascade(contestant["id"])
    contestant["status"] = status
    touch(contestant)
    return ok(ser(contestant))
