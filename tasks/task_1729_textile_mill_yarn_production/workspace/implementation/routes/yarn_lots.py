"""YarnLot endpoints."""

from decimal import Decimal

from flask import Blueprint, request

from db import db, new_id, now_iso
from errors import (
    err_invalid_state,
    err_not_found,
    err_quality_gate,
    err_reference_not_found,
)
from middleware import require_roles
from response import success_list, success_object
from serializers import serialize_yarn_lot
from services.calculations import initial_greige_yards
from services.workflows import touch
from validators import (
    apply_filters,
    get_json_body,
    get_pagination,
    req_decimal,
    req_string,
    sort_and_paginate,
)

bp = Blueprint("yarn_lots", __name__)

ALL_ROLES = ("MillPlanner", "SpinningSupervisor", "DyeHouseOperator", "QualityInspector", "CustomerServiceRep")


@bp.post("/mill/yarn-lots")
def create_yarn_lot():
    require_roles("SpinningSupervisor")
    body = get_json_body()
    recipe_id = req_string(body, "recipe_id")
    spun_weight = req_decimal(body, "spun_weight_lbs", min_value=0, min_exclusive=True)
    actual_count = req_decimal(body, "actual_yarn_count_ne", min_value=0, min_exclusive=True)

    recipe = db.blend_recipes.get(recipe_id)
    if recipe is None:
        raise err_reference_not_found("recipe_id does not resolve to an existing blend recipe")
    if recipe["status"] != "APPROVED":
        raise err_quality_gate("Yarn may only be spun from an APPROVED recipe")

    ts = now_iso()
    record = {
        "id": new_id(),
        "recipe_id": recipe["id"],
        "spun_weight_lbs": spun_weight,
        "actual_yarn_count_ne": actual_count,
        "greige_yards_available": initial_greige_yards(spun_weight, actual_count),
        "actual_cost_per_lb": None,
        "status": "GREIGE",
        "count_deviation_flag": False,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.yarn_lots[record["id"]] = record
    return success_object(serialize_yarn_lot(record), 201)


@bp.get("/mill/yarn-lots")
def list_yarn_lots():
    require_roles(*ALL_ROLES)
    limit, offset = get_pagination()
    items = apply_filters(
        list(db.yarn_lots.values()),
        {"status": request.args.get("status"), "recipe_id": request.args.get("recipe_id")},
    )
    page, total = sort_and_paginate(items, limit, offset)
    return success_list([serialize_yarn_lot(r) for r in page], limit, offset, total)


@bp.get("/mill/yarn-lots/<yid>")
def get_yarn_lot(yid):
    require_roles(*ALL_ROLES)
    record = db.yarn_lots.get(yid)
    if record is None:
        raise err_not_found("Yarn lot not found")
    return success_object(serialize_yarn_lot(record))


@bp.post("/mill/yarn-lots/<yid>/reject")
def reject_yarn_lot(yid):
    require_roles("QualityInspector")
    record = db.yarn_lots.get(yid)
    if record is None:
        raise err_not_found("Yarn lot not found")
    if record["status"] != "GREIGE":
        raise err_invalid_state("Only a GREIGE yarn lot can be rejected")
    record["status"] = "REJECTED"
    record["greige_yards_available"] = Decimal("0")
    touch(record)
    return success_object(serialize_yarn_lot(record))
