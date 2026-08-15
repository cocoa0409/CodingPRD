"""Crop endpoints (PRD §3.2)."""

from flask import Blueprint, request

import db
import domain
from errors import raise_err, ERR_NOT_FOUND
from helpers import (
    check_no_undeclared,
    get_body,
    ok_object,
    paginate,
    req_int,
    req_str,
    require,
)

bp = Blueprint("crops", __name__)

FM = ("FarmManager",)
READERS = ("FarmManager", "GateStaff", "FieldStaff")


@bp.post("/farm/crops")
def create_crop():
    require(FM)
    body = get_body()
    check_no_undeclared(body, {"season_id", "name", "price_per_lb_cents"})
    season_id = req_str(body, "season_id")
    name = req_str(body, "name")
    price = req_int(body, "price_per_lb_cents", min_value=1)
    if season_id not in db.seasons:
        raise_err(ERR_NOT_FOUND, "season_id does not resolve")
    crop = domain.new_entity()
    crop.update(
        {"season_id": season_id, "name": name, "price_per_lb_cents": price}
    )
    db.crops[crop["id"]] = crop
    return ok_object(domain.serialize_crop(crop), 201)


@bp.get("/farm/crops/<cid>")
def get_crop(cid):
    require(READERS)
    crop = db.crops.get(cid)
    if crop is None:
        raise_err(ERR_NOT_FOUND, "Crop not found")
    return ok_object(domain.serialize_crop(crop))


@bp.get("/farm/crops")
def list_crops():
    require(READERS)
    items = list(db.crops.values())
    season_id = request.args.get("season_id")
    if season_id is not None:
        items = [c for c in items if c["season_id"] == season_id]
    return paginate(items, domain.serialize_crop)
