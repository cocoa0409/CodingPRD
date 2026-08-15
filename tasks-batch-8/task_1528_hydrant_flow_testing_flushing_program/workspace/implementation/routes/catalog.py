"""PressureZone, PrivateOwner, and Part catalog endpoints."""
from flask import Blueprint

import db
from db import new_base, touch
from errors import (
    ApiError,
    ERR_PART_NOT_FOUND,
    ERR_PART_SKU_NOT_UNIQUE,
    invalid_request,
    not_found,
)
from middleware import auth, auth_any, require_role
from response import success_list, success_object
from serializers import part_view, private_owner_view, zone_view
from services import part_available_qty
from validation import F, paginate, validate_body

bp = Blueprint("catalog", __name__)


def get_part_or_404(part_id):
    p = db.store.parts.get(part_id)
    if p is None:
        raise not_found(ERR_PART_NOT_FOUND, "Part")
    return p


@bp.post("/zones")
def create_zone():
    auth_user, role = auth()
    body = validate_body([
        F("name", "str"),
        F("cooldown_minutes", "int", required=False, default=60),
    ])
    require_role(role, {"ProgramAdmin"})
    zone = new_base()
    zone.update({"name": body["name"], "cooldown_minutes": body["cooldown_minutes"]})
    db.store.zones[zone["id"]] = zone
    return success_object(zone_view(zone), code=201)


@bp.post("/private-owners")
def create_private_owner():
    auth_user, role = auth()
    body = validate_body([
        F("name", "str"),
        F("contact_email", "str"),
    ])
    require_role(role, {"ProgramAdmin"})
    owner = new_base()
    owner.update({"name": body["name"], "contact_email": body["contact_email"]})
    db.store.private_owners[owner["id"]] = owner
    return success_object(private_owner_view(owner), code=201)


@bp.post("/parts")
def create_part():
    auth_user, role = auth()
    body = validate_body([
        F("sku", "str"),
        F("name", "str"),
        F("unit_price_cents", "int"),
        F("on_hand_qty", "int"),
    ])
    if body["on_hand_qty"] < 0:
        raise invalid_request("on_hand_qty must be >= 0")
    require_role(role, {"ProgramAdmin"})
    for p in db.store.parts.values():
        if p["sku"] == body["sku"]:
            raise ApiError(ERR_PART_SKU_NOT_UNIQUE, "sku already registered", 409)
    part = new_base()
    part.update({
        "sku": body["sku"],
        "name": body["name"],
        "unit_price_cents": body["unit_price_cents"],
        "on_hand_qty": body["on_hand_qty"],
    })
    db.store.parts[part["id"]] = part
    return success_object(part_view(part, part_available_qty(part["id"])), code=201)


@bp.get("/parts")
def list_parts():
    auth_any()
    items, meta = paginate(list(db.store.parts.values()))
    return success_list([part_view(p, part_available_qty(p["id"])) for p in items], meta)


@bp.get("/parts/<part_id>")
def get_part(part_id):
    auth_any()
    part = get_part_or_404(part_id)
    return success_object(part_view(part, part_available_qty(part["id"])))


@bp.post("/parts/<part_id>/restock")
def restock_part(part_id):
    auth_user, role = auth()
    body = validate_body([
        F("add_qty", "int"),
        F("new_unit_price_cents", "int", required=False),
    ])
    if body["add_qty"] <= 0:
        raise invalid_request("add_qty must be > 0")
    require_role(role, {"ProgramAdmin"})
    part = get_part_or_404(part_id)
    part["on_hand_qty"] += body["add_qty"]
    if body["new_unit_price_cents"] is not None:
        part["unit_price_cents"] = body["new_unit_price_cents"]
    touch(part)
    return success_object(part_view(part, part_available_qty(part["id"])))
