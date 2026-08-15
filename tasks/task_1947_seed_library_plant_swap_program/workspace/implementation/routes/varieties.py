"""SeedVariety endpoints (OCC-guarded PATCH)."""

from flask import Blueprint, request
from db import db
from middleware import require_roles
from validate import (get_body, req_string, opt_string, opt_bool, opt_enum,
                      req_zones, opt_zones, req_int, parse_pagination)
from response import success_object, success_list
from errors import not_found, invalid_enum, ApiError

bp = Blueprint("varieties", __name__)

CATEGORIES = {"VEGETABLE", "HERB", "FLOWER", "NATIVE"}
VARIETY_STATUSES = {"ACTIVE", "RETIRED"}


def variety_view(v):
    return {k: v for k, v in v.items() if not k.startswith("_")}


def get_variety_or_404(variety_id):
    v = db.varieties.get(variety_id)
    if v is None:
        raise not_found("Seed variety not found.")
    return v


@bp.post("/api/seed-varieties")
def create_variety():
    require_roles("ProgramAdmin")
    body = get_body()
    variety_name = req_string(body, "variety_name")
    species = req_string(body, "species")
    category = opt_enum(body, "category", CATEGORIES)
    if category is None:
        from errors import invalid_request
        raise invalid_request("Missing required field: category")
    approved_zones = req_zones(body, "approved_zones")
    invasive_flag = opt_bool(body, "invasive_flag", default=False)
    rarity_flag = opt_bool(body, "rarity_flag", default=False)
    variety = {
        "variety_name": variety_name,
        "species": species,
        "category": category,
        "invasive_flag": invasive_flag,
        "rarity_flag": rarity_flag,
        "approved_zones": list(approved_zones),
        "status": "ACTIVE",
    }
    db.stamp_new(variety)
    db.varieties[variety["id"]] = variety
    return success_object(variety_view(variety), 201)


@bp.get("/api/seed-varieties")
def list_varieties():
    require_roles("ProgramAdmin", "Member", "Volunteer")
    limit, offset = parse_pagination()
    category = request.args.get("category")
    status_f = request.args.get("status")
    if category is not None and category not in CATEGORIES:
        raise invalid_enum("category filter not in declared set.")
    if status_f is not None and status_f not in VARIETY_STATUSES:
        raise invalid_enum("status filter not in declared set.")
    items = sorted(db.varieties.values(), key=lambda v: v["_seq"])
    if category:
        items = [v for v in items if v["category"] == category]
    if status_f:
        items = [v for v in items if v["status"] == status_f]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([variety_view(v) for v in page], limit, offset, total)


@bp.get("/api/seed-varieties/<variety_id>")
def get_variety(variety_id):
    require_roles("ProgramAdmin", "Member", "Volunteer")
    v = get_variety_or_404(variety_id)
    return success_object(variety_view(v))


@bp.patch("/api/seed-varieties/<variety_id>")
def patch_variety(variety_id):
    require_roles("ProgramAdmin")
    v = get_variety_or_404(variety_id)
    body = get_body()
    # band 4: expected version field is required (non-optional per PRD 2.7)
    expected = req_int(body, "expected_seed_variety_version")
    variety_name = opt_string(body, "variety_name")
    invasive_flag = opt_bool(body, "invasive_flag", default=None)
    rarity_flag = opt_bool(body, "rarity_flag", default=None)
    approved_zones = opt_zones(body, "approved_zones", default=None)
    new_status = opt_enum(body, "status", VARIETY_STATUSES, default=None)
    # band 13: OCC check
    if expected != v["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_seed_variety_version does not match current version.")
    if variety_name is not None:
        v["variety_name"] = variety_name
    if invasive_flag is not None:
        v["invasive_flag"] = invasive_flag
    if rarity_flag is not None:
        v["rarity_flag"] = rarity_flag
    if approved_zones is not None:
        v["approved_zones"] = list(approved_zones)
    if new_status is not None:
        v["status"] = new_status
    db.touch(v)
    return success_object(variety_view(v))
