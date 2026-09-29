"""Retailer roster, requirement envelope, global taxonomy and the logical clock."""
import re

from flask import Blueprint, g

import calc
import envelope
import recompute
import validate
from auth import ALL_ROLES, endpoint
from entities import (attribute_definition_out, get_retailer, require_attribute_key,
                      retailer_out, retailer_requirement_out)
from errors import ApiError
from store import base_row, db, fmt_dt, in_order, parse_dt, touch

bp = Blueprint("config", __name__)

RETAILER_CODE_RE = re.compile(r"^[A-Z0-9]+$")
ATTRIBUTE_KEY_RE = re.compile(r"^[a-z0-9]+(_[a-z0-9]+)*$")

RETAILER_STATUSES = ("ACTIVE", "PAUSED", "OFFBOARDED")
DATA_TYPES = ("STRING", "INTEGER", "DECIMAL", "ENUM")
TAXONOMY_GROUPS = ("CORE", "MARKETING", "VARIANT", "COMPLIANCE")
REQUIREMENT_LEVELS = ("REQUIRED", "RECOMMENDED", "OPTIONAL")


# ------------------------------------------------------------------ retailers
@bp.route("/retailers", methods=["POST"])
@endpoint(["ShelfAdmin"])
def create_retailer():
    data = validate.body()
    name = validate.req_str(data, "name", 1, 120)
    code = validate.req_str(data, "retailer_code", 3, 8, RETAILER_CODE_RE)
    status = validate.opt_enum(data, "status", RETAILER_STATUSES, "ACTIVE")
    min_image_count = validate.opt_int(data, "min_image_count", 0, None, 1)
    feed_slot_capacity = validate.opt_int(data, "feed_slot_capacity", 1, None, 10)
    max_windows = validate.opt_int(data, "max_concurrent_feed_windows", 1, None, 2)
    requires_approval = validate.opt_bool(data, "enhanced_content_requires_approval", True)
    for row in db.retailers.values():
        if row["retailer_code"] == code:
            validate.bad("retailer_code")
    retailer = base_row()
    retailer.update({
        "name": name,
        "retailer_code": code,
        "status": status,
        "min_image_count": min_image_count,
        "feed_slot_capacity": feed_slot_capacity,
        "max_concurrent_feed_windows": max_windows,
        "enhanced_content_requires_approval": requires_approval,
        "feed_slots_reserved": 0,
    })
    db.retailers[retailer["id"]] = retailer
    return envelope.created(retailer_out(retailer))


@bp.route("/retailers/<row_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_retailer(row_id):
    retailer = get_retailer(row_id)
    retailer["feed_slots_reserved"] = calc.feed_slots_reserved(retailer["id"])
    return envelope.ok(retailer_out(retailer))


@bp.route("/retailers", methods=["GET"])
@endpoint(ALL_ROLES)
def list_retailers():
    limit, offset = envelope.page_params()
    status = validate.request.args.get("status")
    rows = in_order(list(db.retailers.values()))
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return envelope.paged_with(rows, retailer_out, limit, offset)


@bp.route("/retailers/<row_id>", methods=["PATCH"])
@endpoint(["ShelfAdmin"])
def patch_retailer(row_id):
    data = validate.body()
    expected = validate.req_int(data, "expected_retailer_version")
    status = validate.opt_enum(data, "status", RETAILER_STATUSES)
    min_image_count = validate.opt_int(data, "min_image_count", 0)
    feed_slot_capacity = validate.opt_int(data, "feed_slot_capacity", 1)
    max_windows = validate.opt_int(data, "max_concurrent_feed_windows", 1)
    requires_approval = validate.opt_bool(data, "enhanced_content_requires_approval")
    retailer = get_retailer(row_id)
    if expected != retailer["version"]:
        raise ApiError("ERR_STALE_VERSION")
    if status is not None:
        retailer["status"] = status
    if min_image_count is not None:
        retailer["min_image_count"] = min_image_count
    if feed_slot_capacity is not None:
        retailer["feed_slot_capacity"] = feed_slot_capacity
    if max_windows is not None:
        retailer["max_concurrent_feed_windows"] = max_windows
    if requires_approval is not None:
        retailer["enhanced_content_requires_approval"] = requires_approval
    retailer["feed_slots_reserved"] = calc.feed_slots_reserved(retailer["id"])
    touch(retailer)
    recompute.recompute_product_scores_for_retailer(retailer["id"])
    return envelope.ok(retailer_out(retailer))


# --------------------------------------------------------------- requirements
@bp.route("/retailers/<row_id>/requirements", methods=["POST"])
@endpoint(["ShelfAdmin"])
def create_requirement(row_id):
    data = validate.body()
    attribute_key = validate.req_str(data, "attribute_key", 1, 40)
    level = validate.req_enum(data, "requirement_level", REQUIREMENT_LEVELS)
    max_chars_override = validate.opt_int(data, "max_chars_override", 1)
    weight_override = validate.opt_num(data, "weight_override")
    if weight_override is not None and weight_override <= 0:
        validate.bad("weight_override")
    retailer = get_retailer(row_id)
    require_attribute_key(attribute_key)
    for row in calc.requirement_rows(retailer["id"]):
        if row["attribute_key"] == attribute_key:
            raise ApiError("ERR_DUPLICATE_REQUIREMENT")
    requirement = base_row()
    requirement.update({
        "retailer_id": retailer["id"],
        "attribute_key": attribute_key,
        "requirement_level": level,
        "max_chars_override": max_chars_override,
        "weight_override": weight_override,
    })
    db.retailer_requirements[requirement["id"]] = requirement
    recompute.recompute_product_scores_for_retailer(retailer["id"])
    return envelope.created(retailer_requirement_out(requirement))


@bp.route("/retailers/<row_id>/requirements", methods=["GET"])
@endpoint(ALL_ROLES)
def list_requirements(row_id):
    limit, offset = envelope.page_params()
    retailer = get_retailer(row_id)
    rows = calc.requirement_rows(retailer["id"])
    return envelope.paged_with(rows, retailer_requirement_out, limit, offset)


# ------------------------------------------------------------------ taxonomy
@bp.route("/attribute-definitions", methods=["POST"])
@endpoint(["ShelfAdmin"])
def create_attribute_definition():
    data = validate.body()
    attribute_key = validate.req_str(data, "attribute_key", 2, 40, ATTRIBUTE_KEY_RE)
    data_type = validate.req_enum(data, "data_type", DATA_TYPES)
    taxonomy_group = validate.req_enum(data, "taxonomy_group", TAXONOMY_GROUPS)
    max_chars = validate.req_int(data, "max_chars", 1)
    base_weight = validate.req_num(data, "base_weight")
    if base_weight <= 0:
        validate.bad("base_weight")
    is_global_required = validate.opt_bool(data, "is_global_required", False)
    for row in db.attribute_definitions.values():
        if row["attribute_key"] == attribute_key:
            validate.bad("attribute_key")
    definition = base_row()
    definition.update({
        "attribute_key": attribute_key,
        "data_type": data_type,
        "taxonomy_group": taxonomy_group,
        "max_chars": max_chars,
        "base_weight": base_weight,
        "is_global_required": is_global_required,
    })
    db.attribute_definitions[definition["id"]] = definition
    return envelope.created(attribute_definition_out(definition))


@bp.route("/attribute-definitions", methods=["GET"])
@endpoint(ALL_ROLES)
def list_attribute_definitions():
    limit, offset = envelope.page_params()
    group = validate.request.args.get("taxonomy_group")
    rows = in_order(list(db.attribute_definitions.values()))
    if group is not None:
        rows = [r for r in rows if r["taxonomy_group"] == group]
    return envelope.paged_with(rows, attribute_definition_out, limit, offset)


# ---------------------------------------------------------------- the clock
@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint(["ShelfAdmin"])
def set_clock():
    data = validate.body()
    raw = validate.req_str(data, "to_iso8601", 1)
    parsed = parse_dt(raw)
    if parsed is None:
        validate.bad("to_iso8601")
    db.clock = parsed
    return envelope.ok({"current_utc": fmt_dt(parsed)})
