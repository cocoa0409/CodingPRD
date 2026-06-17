"""CabinetSpec and FinishSelection routes."""
from flask import Blueprint, request

from db import store
from errors import err
from middleware import get_user_context, require_role
from response import success, success_list
from helpers import (get_body, require_str, require_int, require_enum,
                     parse_pagination, paginate, sort_by_created)
from models import (_base_record, touch, serialize_spec, serialize_finish,
                    project_active_finish)
from lookups import get_project_in_shop, get_spec_in_project, get_finish_in_project
from calculations import panel_area_mm2
from services import recompute_estimate

bp = Blueprint("spec", __name__)


# --------------------------------------------------------------------------
# CabinetSpec
# --------------------------------------------------------------------------
@bp.route("/shops/<shop_id>/projects/<project_id>/specs", methods=["POST"])
def create_spec(shop_id, project_id):
    _, role = get_user_context()
    require_role(role, {"Designer", "ShopManager", "ShopAdmin"})
    p = get_project_in_shop(shop_id, project_id)
    body = get_body()
    label = require_str(body, "label")
    width_mm = require_int(body, "width_mm", minimum=1)
    height_mm = require_int(body, "height_mm", minimum=1)
    depth_mm = require_int(body, "depth_mm", minimum=1)
    quantity = require_int(body, "quantity", minimum=1)
    base_unit_price_cents = require_int(body, "base_unit_price_cents", minimum=0)
    material_id = require_str(body, "material_id")

    # Specs may be added only while OPEN (project DRAFT/MEASURED/QUOTED).
    # After contract lock the project's specs are LOCKED -> ERR_SPECS_LOCKED.
    if p["status"] not in ("DRAFT", "MEASURED", "QUOTED"):
        raise err("ERR_SPECS_LOCKED", "Specs are locked")

    # Cross-shop reference: material must belong to the path shop.
    material = store.materials.get(material_id)
    if material is None or material["shop_id"] != shop_id:
        raise err("ERR_CROSS_SHOP_REFERENCE", "Material belongs to a different shop")

    rec = _base_record()
    rec.update({
        "project_id": project_id,
        "label": label,
        "width_mm": width_mm,
        "height_mm": height_mm,
        "depth_mm": depth_mm,
        "quantity": quantity,
        "base_unit_price_cents": base_unit_price_cents,
        "panel_area_mm2": panel_area_mm2(width_mm, height_mm, depth_mm),
        "material_id": material_id,
        "lock_state": "OPEN",
    })
    store.specs[rec["id"]] = rec
    recompute_estimate(p)
    touch(p)
    return success(serialize_spec(rec), 201)


@bp.route("/shops/<shop_id>/projects/<project_id>/specs/<spec_id>", methods=["GET"])
def get_spec(shop_id, project_id, spec_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Designer"})
    s = get_spec_in_project(shop_id, project_id, spec_id)
    return success(serialize_spec(s), 200)


@bp.route("/shops/<shop_id>/projects/<project_id>/specs", methods=["GET"])
def list_specs(shop_id, project_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Designer"})
    get_project_in_shop(shop_id, project_id)
    limit, offset = parse_pagination()
    items = [s for s in store.specs.values() if s["project_id"] == project_id]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([serialize_spec(s) for s in page], limit, offset, total)


@bp.route("/shops/<shop_id>/projects/<project_id>/specs/<spec_id>", methods=["DELETE"])
def delete_spec(shop_id, project_id, spec_id):
    _, role = get_user_context()
    require_role(role, {"Designer", "ShopManager", "ShopAdmin"})
    p = get_project_in_shop(shop_id, project_id)
    s = get_spec_in_project(shop_id, project_id, spec_id)
    if s["lock_state"] != "OPEN":
        raise err("ERR_SPECS_LOCKED", "Spec is locked")
    del store.specs[spec_id]
    recompute_estimate(p)
    touch(p)
    return success(serialize_spec(s), 200)


@bp.route("/shops/<shop_id>/projects/<project_id>/specs-by-material", methods=["GET"])
def list_specs_by_material(shop_id, project_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Designer"})
    get_project_in_shop(shop_id, project_id)
    limit, offset = parse_pagination()
    material_id = request.args.get("material_id")
    items = [s for s in store.specs.values() if s["project_id"] == project_id]
    if material_id is not None:
        items = [s for s in items if s["material_id"] == material_id]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([serialize_spec(s) for s in page], limit, offset, total)


# --------------------------------------------------------------------------
# FinishSelection
# --------------------------------------------------------------------------
@bp.route("/shops/<shop_id>/projects/<project_id>/finish-selections", methods=["POST"])
def create_finish(shop_id, project_id):
    _, role = get_user_context()
    require_role(role, {"Designer", "ShopManager", "ShopAdmin"})
    p = get_project_in_shop(shop_id, project_id)
    body = get_body()
    finish_code = require_enum(body, "finish_code", {"RAW", "STAIN", "PAINT", "LACQUER"})
    sheen = require_enum(body, "sheen", {"MATTE", "SATIN", "GLOSS"}, required=False, default="SATIN")

    # Deactivate prior active selection
    prior = project_active_finish(project_id)
    if prior is not None:
        prior["is_active"] = False
        touch(prior)

    rec = _base_record()
    rec.update({
        "project_id": project_id,
        "finish_code": finish_code,
        "sheen": sheen,
        "is_active": True,
    })
    store.finish_selections[rec["id"]] = rec
    recompute_estimate(p)
    touch(p)
    return success(serialize_finish(rec), 201)


@bp.route("/shops/<shop_id>/projects/<project_id>/finish-selections", methods=["GET"])
def list_finishes(shop_id, project_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Designer"})
    get_project_in_shop(shop_id, project_id)
    limit, offset = parse_pagination()
    items = [f for f in store.finish_selections.values() if f["project_id"] == project_id]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([serialize_finish(f) for f in page], limit, offset, total)


@bp.route("/shops/<shop_id>/projects/<project_id>/finish-selections/<finish_id>", methods=["GET"])
def get_finish(shop_id, project_id, finish_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Designer"})
    f = get_finish_in_project(shop_id, project_id, finish_id)
    return success(serialize_finish(f), 200)
