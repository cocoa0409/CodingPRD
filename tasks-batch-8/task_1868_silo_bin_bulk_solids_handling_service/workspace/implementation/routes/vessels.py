"""Vessel endpoints, including OCC-guarded PATCH."""
from flask import Blueprint

import errors
from db import store, new_id, now_iso
from middleware import require_auth, require_role
from response import success_object, success_list
from services import serialize, domain
from services.validate import (get_json_body, reject_unknown_fields, require_fields,
                               as_string, as_bool, as_number, as_int, as_enum,
                               check_range, parse_pagination)

bp = Blueprint("vessels", __name__)


@bp.route("/vessels", methods=["POST"])
def create_vessel():
    ctx = require_auth()
    body = get_json_body()
    allowed = {"site_id", "name", "vessel_kind", "capacity_tons", "material_name",
               "opening_inventory_tons", "reorder_point_pct", "target_fill_pct",
               "replenishment_policy", "cover_days", "default_usage_tons",
               "moisture_limit_pct", "error_basis", "full_scale_tons"}
    reject_unknown_fields(body, allowed)
    require_fields(body, ["site_id", "name", "vessel_kind", "capacity_tons",
                          "material_name", "reorder_point_pct"])

    site_id = as_string(body["site_id"], "site_id")
    name = as_string(body["name"], "name")
    vessel_kind = as_enum(body["vessel_kind"], "vessel_kind", {"SILO", "BIN", "HOPPER"})
    capacity = as_number(body["capacity_tons"], "capacity_tons")
    check_range(capacity, "capacity_tons", 0, None, min_exclusive=True)
    material_name = as_string(body["material_name"], "material_name")
    reorder_pt = as_number(body["reorder_point_pct"], "reorder_point_pct")
    check_range(reorder_pt, "reorder_point_pct", 0, 100)

    opening_inv = 0
    if "opening_inventory_tons" in body:
        opening_inv = as_number(body["opening_inventory_tons"], "opening_inventory_tons")
        check_range(opening_inv, "opening_inventory_tons", 0, None)
    target_fill = 90
    if "target_fill_pct" in body:
        target_fill = as_number(body["target_fill_pct"], "target_fill_pct")
        check_range(target_fill, "target_fill_pct", 0, 100, min_exclusive=True)
    policy = "TARGET_FILL"
    if "replenishment_policy" in body:
        policy = as_enum(body["replenishment_policy"], "replenishment_policy",
                         {"TARGET_FILL", "DAYS_OF_COVER"})
    cover_days = 7
    if "cover_days" in body:
        cover_days = as_number(body["cover_days"], "cover_days")
        check_range(cover_days, "cover_days", 0, None, min_exclusive=True)
    default_usage = 1.0
    if "default_usage_tons" in body:
        default_usage = as_number(body["default_usage_tons"], "default_usage_tons")
        check_range(default_usage, "default_usage_tons", 0, None)
    moisture_limit = 12.0
    if "moisture_limit_pct" in body:
        moisture_limit = as_number(body["moisture_limit_pct"], "moisture_limit_pct")
        check_range(moisture_limit, "moisture_limit_pct", 0, 100)
    error_basis = "OF_READING"
    if "error_basis" in body:
        error_basis = as_enum(body["error_basis"], "error_basis",
                              {"OF_READING", "OF_FULL_SCALE"})
    full_scale = None
    if "full_scale_tons" in body and body["full_scale_tons"] is not None:
        full_scale = as_number(body["full_scale_tons"], "full_scale_tons")
        check_range(full_scale, "full_scale_tons", 0, None, min_exclusive=True)
    if error_basis == "OF_FULL_SCALE" and full_scale is None:
        raise errors.validation("full_scale_tons is required when error_basis is OF_FULL_SCALE")

    require_role(ctx, {"ServiceManager"})

    site = store.sites.get(site_id)
    if site is None:
        raise errors.not_found(errors.ERR_SITE_NOT_FOUND, "Referenced site does not exist")

    ts = now_iso()
    v = {
        "id": new_id(),
        "site_id": site_id,
        "name": name,
        "vessel_kind": vessel_kind,
        "capacity_tons": capacity,
        "material_name": material_name,
        "opening_inventory_tons": opening_inv,
        "reorder_point_pct": reorder_pt,
        "target_fill_pct": target_fill,
        "replenishment_policy": policy,
        "cover_days": cover_days,
        "default_usage_tons": default_usage,
        "moisture_limit_pct": moisture_limit,
        "error_basis": error_basis,
        "full_scale_tons": full_scale,
        "scale_status": "IN_TOLERANCE",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.vessels[v["id"]] = v
    return success_object(serialize.serialize_vessel(v), status=201)


@bp.route("/vessels/<vessel_id>", methods=["GET"])
def get_vessel(vessel_id):
    require_auth()
    v = store.vessels.get(vessel_id)
    if v is None:
        raise errors.not_found(errors.ERR_VESSEL_NOT_FOUND, "Vessel not found")
    return success_object(serialize.serialize_vessel(v))


@bp.route("/vessels", methods=["GET"])
def list_vessels():
    require_auth()
    limit, offset = parse_pagination()
    from flask import request
    site_id = request.args.get("site_id")
    vessels = list(store.vessels.values())
    if site_id is not None:
        vessels = [v for v in vessels if v["site_id"] == site_id]
    vessels.sort(key=lambda v: v["created_at"])
    total = len(vessels)
    page = vessels[offset:offset + limit]
    return success_list([serialize.serialize_vessel(v) for v in page],
                        limit=limit, offset=offset, total_count=total)


@bp.route("/vessels/<vessel_id>", methods=["PATCH"])
def patch_vessel(vessel_id):
    ctx = require_auth()
    body = get_json_body()
    allowed = {"expected_vessel_version", "reorder_point_pct", "target_fill_pct",
               "moisture_limit_pct"}
    reject_unknown_fields(body, allowed)
    require_fields(body, ["expected_vessel_version"])
    expected = as_int(body["expected_vessel_version"], "expected_vessel_version")

    new_reorder = None
    if "reorder_point_pct" in body:
        new_reorder = as_number(body["reorder_point_pct"], "reorder_point_pct")
        check_range(new_reorder, "reorder_point_pct", 0, 100)
    new_target = None
    if "target_fill_pct" in body:
        new_target = as_number(body["target_fill_pct"], "target_fill_pct")
        check_range(new_target, "target_fill_pct", 0, 100, min_exclusive=True)
    new_moisture = None
    if "moisture_limit_pct" in body:
        new_moisture = as_number(body["moisture_limit_pct"], "moisture_limit_pct")
        check_range(new_moisture, "moisture_limit_pct", 0, 100)

    require_role(ctx, {"ServiceManager"})

    v = store.vessels.get(vessel_id)
    if v is None:
        raise errors.not_found(errors.ERR_VESSEL_NOT_FOUND, "Vessel not found")

    if expected != v["version"]:
        raise errors.stale_version()

    if new_reorder is not None:
        v["reorder_point_pct"] = new_reorder
    if new_target is not None:
        v["target_fill_pct"] = new_target
    if new_moisture is not None:
        v["moisture_limit_pct"] = new_moisture
    v["updated_at"] = now_iso()
    v["version"] = v["version"] + 1
    return success_object(serialize.serialize_vessel(v))
