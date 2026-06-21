from flask import Blueprint, request

import db
import validate
import serialize
from response import ok_object, ok_array
from middleware import require
from services import lookup

bp = Blueprint("gpl_items", __name__)


@bp.post("/gpl-items")
@require("Admin")
def create_gpl_item():
    body = validate.get_json()
    funeral_home_id = validate.require_string(body, "funeral_home_id")
    code = validate.require_string(body, "code")
    name = validate.require_string(body, "name")
    category = validate.require_enum(body, "category", {"SERVICE", "MERCHANDISE"})
    taxable = validate.optional_bool(body, "taxable", default=False)
    non_declinable = validate.optional_bool(body, "non_declinable", default=False)
    preneed_trustable = validate.optional_bool(body, "preneed_trustable", default=True)
    unit_price_cents = validate.require_int(body, "unit_price_cents", minimum=0)

    # existence (priority 3) after request well-formedness fields parsed
    lookup.funeral_home(funeral_home_id)

    item = {
        "id": db.new_id(),
        "funeral_home_id": funeral_home_id,
        "code": code,
        "name": name,
        "category": category,
        "taxable": taxable,
        "non_declinable": non_declinable,
        "preneed_trustable": preneed_trustable,
        "unit_price_cents": unit_price_cents,
        "active": True,
    }
    db.stamp_create(item)
    db.gpl_items[item["id"]] = item
    return ok_object(serialize.gpl_item(item), 201)


@bp.get("/gpl-items/<item_id>")
@require("Admin", "Arranger")
def get_gpl_item(item_id):
    item = lookup.gpl_item(item_id)
    return ok_object(serialize.gpl_item(item), 200)


@bp.get("/gpl-items")
@require("Admin", "Arranger")
def list_gpl_items():
    limit, offset = validate.pagination()
    fh = request.args.get("funeral_home_id")
    items = list(db.gpl_items.values())
    if fh is not None:
        items = [i for i in items if i["funeral_home_id"] == fh]
    window, total = validate.paginate(items, limit, offset)
    return ok_array([serialize.gpl_item(i) for i in window], limit, offset, total)


@bp.patch("/gpl-items/<item_id>")
@require("Admin")
def update_gpl_item(item_id):
    item = lookup.gpl_item(item_id)
    body = validate.get_json()
    changed = False
    if "unit_price_cents" in body and body["unit_price_cents"] is not None:
        item["unit_price_cents"] = validate.require_int(body, "unit_price_cents", minimum=0)
        changed = True
    if "active" in body and body["active"] is not None:
        item["active"] = validate.optional_bool(body, "active")
        changed = True
    if changed:
        db.touch(item)
    return ok_object(serialize.gpl_item(item), 200)
