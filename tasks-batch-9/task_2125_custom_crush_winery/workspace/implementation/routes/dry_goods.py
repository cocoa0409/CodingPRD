"""Client-owned dry goods held at the facility."""

from flask import Blueprint

import domain
from auth import ALL_ROLES, FACILITY_ADMIN, guard, scope
from envelope import respond
from helpers import run_list
from store import db, new_entity, touch
from validation import v_enum, v_int, v_string

bp = Blueprint("dry_goods", __name__)

ITEM_TYPES = {"BOTTLE", "CORK", "CAPSULE", "LABEL", "CASE_BOX"}


@bp.route("/dry-goods-items", methods=["POST"])
def create_item():
    ctx = guard([FACILITY_ADMIN])
    body = ctx.body
    client_id = v_string(body, "client_id")
    sku = v_string(body, "sku")
    item_type = v_enum(body, "item_type", ITEM_TYPES)
    units_per_case = v_int(body, "units_per_case", ge=1)
    initial_units = v_int(body, "initial_units", required=False, default=0, ge=0)

    domain.get_client(client_id)

    item = new_entity({
        "client_id": client_id,
        "sku": sku,
        "item_type": item_type,
        "units_per_case": units_per_case,
        "on_hand_units": initial_units,
        "reserved_units": 0,
        "available_units": initial_units,
    })
    db.dry_goods[item["id"]] = item
    return respond(domain.serialize(item), 201)


@bp.route("/dry-goods-items/<item_id>", methods=["GET"])
def read_item(item_id):
    ctx = guard(ALL_ROLES, read_body=False)
    item = domain.get_dry_goods(item_id)
    scope(ctx, item["client_id"])
    return respond(domain.serialize(item))


@bp.route("/dry-goods-items", methods=["GET"])
def list_items():
    ctx = guard(ALL_ROLES, read_body=False)
    return run_list(db.dry_goods.values(), ctx, domain.serialize,
                    owner_fn=lambda i: i["client_id"],
                    filters=(("client_id", "client_id"), ("item_type", "item_type")))


@bp.route("/dry-goods-items/<item_id>/receipts", methods=["POST"])
def receive_units(item_id):
    ctx = guard([FACILITY_ADMIN])
    units = v_int(ctx.body, "units", gt=0)
    item = domain.get_dry_goods(item_id)

    item["on_hand_units"] = item["on_hand_units"] + units
    domain.recompute_dry_goods(item)
    touch(item)
    return respond(domain.serialize(item))
