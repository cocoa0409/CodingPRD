"""Protective gear items (PRD §3.5)."""
from flask import Blueprint, request

from db import db, stamp, touch, serialize
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_GEAR_ITEM_NOT_FOUND,
    ERR_PLAYER_NOT_FOUND,
    ERR_ASSET_TAG_TAKEN,
    ERR_GEAR_NOT_IN_STOCK,
    ERR_GEAR_NOT_ISSUED,
    ERR_PLAYER_NOT_ACTIVE,
    ERR_GEAR_CERTIFICATION_EXPIRED,
    ERR_GEAR_CONDITION_NOT_ISSUABLE,
    ERR_PLAYER_GEAR_LIMIT_REACHED,
)
from middleware import endpoint
from response import success
from routes.common import ALL_ROLES, render_list
from util import parse_date, parse_dt

bp = Blueprint("gear", __name__)

ITEM_TYPES = {"HELMET", "SHOULDER_PADS", "GIRDLE_PADS", "KNEE_BRACE"}
GRADES = {"A", "B", "C", "F"}
GEAR_STATUSES = {"IN_STOCK", "ISSUED", "OUT_FOR_RECONDITIONING", "RETIRED"}
CERT_REQUIRED_TYPES = {"HELMET", "SHOULDER_PADS"}


@bp.post("/gear-items")
@endpoint("EquipmentManager")
def create_gear(ctx):
    b = ctx.body
    asset_tag = b.get("asset_tag")
    item_type = b.get("item_type")
    size_spec = b.get("size_spec")
    acquired_on = parse_date(b.get("acquired_on"))
    condition_grade = b.get("condition_grade", "A")
    certification_expires_on = b.get("certification_expires_on")
    if not isinstance(asset_tag, str) or not asset_tag:
        raise_err(ERR_INVALID_REQUEST, "asset_tag is required")
    if item_type not in ITEM_TYPES:
        raise_err(ERR_INVALID_REQUEST, "item_type is not a declared value")
    if not isinstance(size_spec, str) or not size_spec:
        raise_err(ERR_INVALID_REQUEST, "size_spec is required")
    if acquired_on is None:
        raise_err(ERR_INVALID_REQUEST, "acquired_on must be a YYYY-MM-DD date")
    if condition_grade not in GRADES:
        raise_err(ERR_INVALID_REQUEST, "condition_grade is not a declared value")
    cert = None
    if certification_expires_on is not None:
        cert = parse_dt(certification_expires_on)
        if cert is None:
            raise_err(
                ERR_INVALID_REQUEST, "certification_expires_on must be an ISO 8601 timestamp"
            )
    if any(g for g in db.gear_items.values() if g["asset_tag"] == asset_tag):
        raise_err(ERR_ASSET_TAG_TAKEN, "asset_tag already registered")
    item = stamp(
        {
            "asset_tag": asset_tag,
            "item_type": item_type,
            "size_spec": size_spec,
            "condition_grade": condition_grade,
            "certification_expires_on": cert,
            "acquired_on": acquired_on.isoformat(),
            "status": "IN_STOCK",
            "current_holder_id": None,
        }
    )
    db.gear_items[item["id"]] = item
    return success(serialize(item), 201)


@bp.get("/gear-items")
@endpoint(*ALL_ROLES)
def list_gear(ctx):
    item_type = request.args.get("item_type")
    status = request.args.get("status")
    if item_type is not None and item_type not in ITEM_TYPES:
        raise_err(ERR_INVALID_REQUEST, "item_type filter is not a declared value")
    if status is not None and status not in GEAR_STATUSES:
        raise_err(ERR_INVALID_REQUEST, "status filter is not a declared value")
    return render_list(
        db.gear_items,
        {
            "current_holder_id": request.args.get("current_holder_id"),
            "item_type": item_type,
            "status": status,
        },
    )


@bp.get("/gear-items/<item_id>")
@endpoint(*ALL_ROLES)
def get_gear(ctx, item_id):
    item = db.gear_items.get(item_id)
    if item is None:
        raise_err(ERR_GEAR_ITEM_NOT_FOUND, "gear item not found")
    return success(serialize(item))


@bp.post("/gear-items/<item_id>/issue")
@endpoint("EquipmentManager")
def issue_gear(ctx, item_id):
    b = ctx.body
    player_id = b.get("player_id")
    if not isinstance(player_id, str) or not player_id:
        raise_err(ERR_INVALID_REQUEST, "player_id is required")
    item = db.gear_items.get(item_id)
    if item is None:
        raise_err(ERR_GEAR_ITEM_NOT_FOUND, "gear item not found")
    player = db.players.get(player_id)
    if player is None:
        raise_err(ERR_PLAYER_NOT_FOUND, "player not found")
    if item["status"] != "IN_STOCK":
        raise_err(ERR_GEAR_NOT_IN_STOCK, "gear item is not IN_STOCK")
    if player["status"] != "ACTIVE":
        raise_err(ERR_PLAYER_NOT_ACTIVE, "player is not ACTIVE")
    # Safety gates (rung 6): certification before condition.
    if item["item_type"] in CERT_REQUIRED_TYPES:
        from db import clock

        cert = item["certification_expires_on"]
        if cert is None or cert <= clock():
            raise_err(
                ERR_GEAR_CERTIFICATION_EXPIRED,
                "certification missing or expired for HELMET/SHOULDER_PADS",
            )
    if item["condition_grade"] == "F":
        raise_err(ERR_GEAR_CONDITION_NOT_ISSUABLE, "grade F item is not issuable")
    if any(
        g
        for g in db.gear_items.values()
        if g["id"] != item_id
        and g["current_holder_id"] == player_id
        and g["status"] == "ISSUED"
        and g["item_type"] == item["item_type"]
    ):
        raise_err(
            ERR_PLAYER_GEAR_LIMIT_REACHED,
            "player already holds an ISSUED item of this item_type",
        )
    item["status"] = "ISSUED"
    item["current_holder_id"] = player_id
    touch(item)
    return success(serialize(item))


@bp.post("/gear-items/<item_id>/return")
@endpoint("EquipmentManager")
def return_gear(ctx, item_id):
    item = db.gear_items.get(item_id)
    if item is None:
        raise_err(ERR_GEAR_ITEM_NOT_FOUND, "gear item not found")
    if item["status"] != "ISSUED":
        raise_err(ERR_GEAR_NOT_ISSUED, "return requires gear in ISSUED")
    item["status"] = "IN_STOCK"
    item["current_holder_id"] = None
    touch(item)
    return success(serialize(item))


@bp.post("/gear-items/<item_id>/retire")
@endpoint("EquipmentManager")
def retire_gear(ctx, item_id):
    item = db.gear_items.get(item_id)
    if item is None:
        raise_err(ERR_GEAR_ITEM_NOT_FOUND, "gear item not found")
    if item["status"] != "IN_STOCK":
        raise_err(ERR_GEAR_NOT_IN_STOCK, "retire requires gear in IN_STOCK")
    item["status"] = "RETIRED"
    touch(item)
    return success(serialize(item))
