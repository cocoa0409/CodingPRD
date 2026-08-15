"""Grower and orchard-block endpoints (PRD 3.1)."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_UNIQUE_CONSTRAINT_VIOLATION
from middleware import authorized, check_grower_scope, ALL_ROLES
from response import success_object
from routes.helpers import list_response, public, sorted_items
from services.core import new_record
from validate import get_body, req_enum, req_int, req_str, require_path_resource

bp = Blueprint("growers", __name__)

VARIETIES = {"HONEYCRISP", "GALA", "FUJI", "GRANNY_SMITH", "COSMIC_CRISP"}


@bp.post("/growers")
def create_grower():
    authorized(["Admin"])
    body = get_body()
    name = req_str(body, "name")
    grower_code = req_str(body, "grower_code")
    # uniqueness: grower_code across all growers (tier 11)
    for g in db["growers"].values():
        if g["grower_code"] == grower_code:
            raise_error(ERR_UNIQUE_CONSTRAINT_VIOLATION,
                        f"grower_code already registered: {grower_code}")
    rec = new_record("growers", {
        "name": name,
        "grower_code": grower_code,
    })
    return success_object(public(rec), status=201)


@bp.get("/growers/<rid>")
def get_grower(rid):
    caller = authorized(list(ALL_ROLES))
    # Grower self-read: the path id IS the grower scope (tier 3 before tier 4).
    check_grower_scope(caller, rid)
    rec = require_path_resource("growers", rid)
    return success_object(public(rec))


@bp.post("/growers/<rid>/blocks")
def create_block(rid):
    authorized(["Admin", "ReceivingClerk"])
    grower = require_path_resource("growers", rid)
    body = get_body()
    orchard_name = req_str(body, "orchard_name")
    block_code = req_str(body, "block_code")
    variety = req_enum(body, "variety", VARIETIES)
    storage_life_days = req_int(body, "storage_life_days", positive=True)
    # uniqueness: (grower_id, orchard_name, block_code, variety)
    for b in db["blocks"].values():
        if (b["grower_id"] == grower["id"]
                and b["orchard_name"] == orchard_name
                and b["block_code"] == block_code
                and b["variety"] == variety):
            raise_error(ERR_UNIQUE_CONSTRAINT_VIOLATION,
                        "a block already exists for this grower/orchard/block/variety")
    rec = new_record("blocks", {
        "grower_id": grower["id"],
        "orchard_name": orchard_name,
        "block_code": block_code,
        "variety": variety,
        "storage_life_days": storage_life_days,
    })
    return success_object(public(rec), status=201)


@bp.get("/growers/<rid>/blocks")
def list_blocks(rid):
    caller = authorized(list(ALL_ROLES))
    check_grower_scope(caller, rid)
    require_path_resource("growers", rid)
    items = [b for b in sorted_items("blocks") if b["grower_id"] == rid]
    return list_response(items)
