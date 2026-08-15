"""TrimItem and TrimRequirement endpoints (PRD §3.3, §3.4)."""

from flask import Blueprint, request

from db import store
from middleware import require_roles, ALL_ROLES, ROLE_MERCHANDISER, ROLE_MATERIALS_PLANNER
from response import success_object
from util import (
    get_body, req_str, req_int, req_num, req_country, fk_exists,
)
from errors import invalid_request, tech_pack_not_editable
from services.core import (
    base_record, touch, public, get_trim_item, get_trim_requirement,
    get_tech_pack,
)
from services.calc import trim_hold_sweep
from routes.common import list_response, active_filters

bp = Blueprint("trim", __name__)


# --- Trim items -------------------------------------------------------------
@bp.route("/trim-items", methods=["POST"])
def create_trim_item():
    require_roles([ROLE_MATERIALS_PLANNER])
    body = get_body()
    sku_code = req_str(body, "sku_code")
    description = req_str(body, "description")
    origin_country = req_country(body, "origin_country")
    unit_cost_cents = req_int(body, "unit_cost_cents", min_v=0)
    if any(t["sku_code"] == sku_code for t in store.trim_items.values()):
        raise invalid_request("sku_code must be unique")

    rec = base_record()
    rec.update({
        "sku_code": sku_code,
        "description": description,
        "origin_country": origin_country,
        "unit_cost_cents": unit_cost_cents,
        "qty_on_hand": 0,
        "qty_reserved": 0,
        "qty_available": 0,
    })
    store.trim_items[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/trim-items/<item_id>", methods=["GET"])
def get_trim_item_endpoint(item_id):
    require_roles(ALL_ROLES)
    return success_object(public(get_trim_item(item_id)))


@bp.route("/trim-items/<item_id>/receive", methods=["POST"])
def receive_trim(item_id):
    require_roles([ROLE_MATERIALS_PLANNER])
    item = get_trim_item(item_id)
    body = get_body()
    qty = req_int(body, "qty", min_v=1)
    item["qty_on_hand"] += qty
    item["qty_available"] = item["qty_on_hand"] - item["qty_reserved"]
    touch(item)
    # TRIM_HOLD sweep (PRD §3.4): held orders re-evaluated, created_at ASC.
    trim_hold_sweep()
    return success_object(public(item))


# --- Trim requirements ------------------------------------------------------
@bp.route("/trim-requirements", methods=["POST"])
def create_trim_requirement():
    require_roles([ROLE_MERCHANDISER])
    body = get_body()
    fk_exists(body, "tech_pack_id", store.tech_packs, "TechPack")
    fk_exists(body, "trim_item_id", store.trim_items, "TrimItem")
    tech_pack_id = req_str(body, "tech_pack_id")
    trim_item_id = req_str(body, "trim_item_id")
    units_per_garment = req_int(body, "units_per_garment", min_v=1)
    wastage_pct = req_num(body, "wastage_pct", ge=0, le=0.5)
    pack = get_tech_pack(tech_pack_id)
    if pack["status"] != "DRAFT":
        raise tech_pack_not_editable(
            "trim requirements may only be added while the tech pack is DRAFT")

    rec = base_record()
    rec.update({
        "tech_pack_id": tech_pack_id,
        "trim_item_id": trim_item_id,
        "units_per_garment": units_per_garment,
        "wastage_pct": wastage_pct,
    })
    store.trim_requirements[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/trim-requirements", methods=["GET"])
def list_trim_requirements():
    require_roles(ALL_ROLES)
    filters = active_filters([
        ("tech_pack_id", request.args.get("tech_pack_id")),
        ("trim_item_id", request.args.get("trim_item_id")),
    ])
    return list_response(store.trim_requirements.values(), filters)


@bp.route("/trim-requirements/<req_id>", methods=["GET"])
def get_trim_requirement_endpoint(req_id):
    require_roles(ALL_ROLES)
    return success_object(public(get_trim_requirement(req_id)))
