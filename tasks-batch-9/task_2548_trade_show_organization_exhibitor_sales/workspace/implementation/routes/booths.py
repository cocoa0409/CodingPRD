"""Booth inventory endpoints (PRD 3.2)."""
from flask import Blueprint, request

import calc
import guards
import validate
import views
from db import base_row, by_created, db, touch
from errors import ApiError
from middleware import (EXHIBITOR, FLOOR_MANAGER, SALES_REP, SHOW_DIRECTOR, authenticate)
from response import created, list_response, object_response, pagination
from validate import BOOTH_NUMBER_RE

bp = Blueprint("booths", __name__)


@bp.route("/shows/<show_id>/booths", methods=["POST"])
def create_booth(show_id):
    body = validate.body()
    booth_number = validate.text(body, "booth_number", 1, 16, pattern=BOOTH_NUMBER_RE)
    width_ft = validate.integer(body, "width_ft", minimum=1)
    depth_ft = validate.integer(body, "depth_ft", minimum=1)
    location_class = validate.enum(body, "location_class", calc.LOCATION_CLASSES)
    premium_zone = validate.enum(body, "premium_zone", calc.PREMIUM_ZONES,
                                 required=False, default="NONE")
    max_height_ft = validate.integer(body, "max_height_ft", minimum=1)

    authenticate((SHOW_DIRECTOR, FLOOR_MANAGER))
    show = guards.get_show(show_id)
    guards.require_show_status(show, ("PLANNING",))
    guards.reject_frozen_floor(show)
    guards.require_open_floor(show)

    venue_contract = db.venue_contracts[show["venue_contract_id"]]
    if max_height_ft > venue_contract["max_booth_height_ft"]:
        raise ApiError("ERR_BOOTH_HEIGHT_LIMIT",
                       "max_height_ft exceeds the hall's rigging limit")

    area_sqft = width_ft * depth_ft
    live_area = sum(b["area_sqft"] for b in calc.show_booths(show["id"])
                    if b["status"] != "MERGED")
    if live_area + area_sqft > calc.sellable_area(show):
        raise ApiError("ERR_FLOOR_INVENTORY_OVERCOMMITTED",
                       "the booth would push the floor past its sellable area")
    for booth in calc.show_booths(show["id"]):
        if booth["booth_number"] == booth_number:
            raise ApiError("ERR_DUPLICATE_BOOTH_NUMBER",
                           "booth_number %s already exists on this show" % booth_number)

    row = base_row()
    row.update({
        "show_id": show["id"],
        "space_contract_id": None,
        "combined_parent_booth_id": None,
        "booth_number": booth_number,
        "width_ft": width_ft,
        "depth_ft": depth_ft,
        "area_sqft": area_sqft,
        "location_class": location_class,
        "premium_zone": premium_zone,
        "max_height_ft": max_height_ft,
        "status": "AVAILABLE",
    })
    db.booths[row["id"]] = row
    touch(show)
    return created(views.booth_view(row))


@bp.route("/booths/<booth_id>", methods=["GET"])
def read_booth(booth_id):
    authenticate((SHOW_DIRECTOR, SALES_REP, FLOOR_MANAGER, EXHIBITOR))
    booth = guards.get_booth(booth_id)
    return object_response(views.booth_view(booth))


@bp.route("/booths", methods=["GET"])
def list_booths():
    limit, offset = pagination()
    authenticate((SHOW_DIRECTOR, SALES_REP, FLOOR_MANAGER, EXHIBITOR))
    rows = by_created(list(db.booths.values()))
    for field in ("show_id", "space_contract_id", "combined_parent_booth_id",
                  "status", "premium_zone", "location_class"):
        wanted = request.args.get(field)
        if wanted:
            rows = [r for r in rows if r[field] == wanted]
    return list_response([views.booth_view(r) for r in rows], limit, offset)


@bp.route("/booths/<booth_id>/combine", methods=["POST"])
def combine_booths(booth_id):
    body = validate.body()
    expected_show_version = validate.integer(body, "expected_show_version", minimum=0)
    booth_ids = validate.id_list(body, "booth_ids")

    authenticate((FLOOR_MANAGER, SHOW_DIRECTOR))
    survivor = guards.get_booth(booth_id)
    children = guards.get_booths(booth_ids)
    guards.reject_merged_booths([survivor])
    guards.reject_merged_booths(children)

    show = guards.get_show(survivor["show_id"])
    guards.check_show_version(show, expected_show_version)

    guards.require_booths_in_show(children, survivor["show_id"])
    if survivor["id"] in booth_ids:
        raise ApiError("ERR_INVALID_COMBINE_SET",
                       "the surviving booth may not be its own child")
    for child in children:
        if child["status"] != "AVAILABLE" or child["combined_parent_booth_id"] is not None:
            raise ApiError("ERR_BOOTH_NOT_AVAILABLE",
                           "booth %s is not available to combine" % child["booth_number"])

    for child in children:
        child["status"] = "MERGED"
        child["combined_parent_booth_id"] = survivor["id"]
        survivor["area_sqft"] += child["area_sqft"]
        touch(child)
    touch(survivor)
    touch(show)
    return object_response(views.booth_view(survivor))
