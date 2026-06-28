"""Service menu items (PRD §3.3)."""
from flask import Blueprint, request

from common import (json_body, make_record, touch, get_str, get_enum,
                    get_int, get_bool, parse_pagination, paginate)
from db import db
from errors import err, ERR_DUPLICATE_RESOURCE, ERR_INVALID_STATE
from middleware import authorize
from lookup import get_menu_item
from response import success_object, success_list
from serialize import menu_item_out

bp = Blueprint("menu_items", __name__)

READ_ROLES = {"SalonManager", "FrontDesk", "Technician"}


@bp.route("/menu-items", methods=["POST"])
def create_menu_item():
    authorize({"SalonManager"})
    body = json_body(optional=False)
    name = get_str(body, "name", required=True)
    category = get_enum(body, "category", ["MANICURE", "PEDICURE", "ENHANCEMENT"], required=True)
    duration_minutes = get_int(body, "duration_minutes", required=True, minimum=5)
    base_price_cents = get_int(body, "base_price_cents", required=True, minimum=0)
    loyalty_points_award = get_int(body, "loyalty_points_award", required=False, default=0, minimum=0)
    requires_sterile_station = get_bool(body, "requires_sterile_station", required=False, default=True)

    # uniqueness within the active set (PRD §3.3)
    for m in db.menu_items.values():
        if m["is_active"] and m["name"] == name:
            raise err(ERR_DUPLICATE_RESOURCE, "Active menu item name already exists")

    rec = make_record({
        "name": name,
        "category": category,
        "duration_minutes": duration_minutes,
        "base_price_cents": base_price_cents,
        "loyalty_points_award": loyalty_points_award,
        "requires_sterile_station": requires_sterile_station,
        "is_active": True,
    })
    db.menu_items[rec["id"]] = rec
    return success_object(menu_item_out(rec), status=201)


@bp.route("/menu-items", methods=["GET"])
def list_menu_items():
    authorize(READ_ROLES)
    items = list(db.menu_items.values())
    cat = request.args.get("category")
    if cat is not None:
        items = [m for m in items if m["category"] == cat]
    ia = request.args.get("is_active")
    if ia is not None:
        want = ia.lower() == "true"
        items = [m for m in items if m["is_active"] == want]
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_list([menu_item_out(m) for m in page], limit, offset, total)


@bp.route("/menu-items/<mid>", methods=["GET"])
def get_one_menu_item(mid):
    authorize(READ_ROLES)
    rec = get_menu_item(mid)
    return success_object(menu_item_out(rec), status=200)


@bp.route("/menu-items/<mid>/retire", methods=["POST"])
def retire_menu_item(mid):
    authorize({"SalonManager"})
    rec = get_menu_item(mid)
    if not rec["is_active"]:
        raise err(ERR_INVALID_STATE, "Menu item already retired")
    rec["is_active"] = False
    touch(rec)
    return success_object(menu_item_out(rec), status=200)
