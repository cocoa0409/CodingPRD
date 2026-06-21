"""Part item routes (PRD 3.7)."""

from flask import Blueprint, request

import db
import errors
from common import (body, new_entity, require_str, require_int, paginate,
                    get_or_404, find_dealership)
from middleware import get_auth, require_role
from response import ok, created, ok_list

bp = Blueprint("part_items", __name__)


@bp.post("/part-items")
def create_part():
    _, role = get_auth()
    require_role(role, {"ServiceAdvisor", "DealerManager"})
    data = body()
    did = data.get("dealership_id")
    find_dealership(did)
    sku = require_str(data, "sku")
    name = require_str(data, "name")
    unit_price = require_int(data, "unit_price_cents", minimum=0)
    qty_on_hand = require_int(data, "qty_on_hand", minimum=0)
    for p in db.store["part_items"].values():
        if p["dealership_id"] == did and p["sku"] == sku:
            errors.err("ERR_DUPLICATE_SKU", "sku already used in this dealership.")
    rec = new_entity({
        "dealership_id": did,
        "sku": sku,
        "name": name,
        "unit_price_cents": unit_price,
        "qty_on_hand": qty_on_hand,
        "qty_reserved": 0,
        "qty_available": qty_on_hand,
    })
    db.store["part_items"][rec["id"]] = rec
    return created(rec)


@bp.get("/part-items")
def list_parts():
    _, role = get_auth()
    require_role(role, {"DealerManager", "ServiceAdvisor"})
    items = list(db.store["part_items"].values())
    did = request.args.get("dealership_id")
    if did is not None:
        items = [p for p in items if p["dealership_id"] == did]
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@bp.get("/part-items/<part_id>")
def get_part(part_id):
    _, role = get_auth()
    require_role(role, {"DealerManager", "ServiceAdvisor"})
    rec = get_or_404("part_items", part_id)
    return ok(rec)
